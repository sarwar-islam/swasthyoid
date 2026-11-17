-- M6 schema (B5; FRD M6, owner decisions 2026-11-16). Idempotent. Applied after capture/schema.sql.

-- The one rule registry. One row per VERSION; a version's content never changes (guard below), only its status moves:
-- draft -> approved | rejected, approved -> superseded. At most one open draft and one approved version per rule, so exactly
-- one version runs. Four-eyes: a version is never approved by its author. No rule is seeded: only the clinical reviewer
-- writes rules (FRD question 7; nothing clinical lives in code).
CREATE TABLE IF NOT EXISTS rules (
    id             uuid PRIMARY KEY,
    rule_id        text NOT NULL CHECK (rule_id ~ '^[A-Z0-9][A-Z0-9-]{2,63}$'),
    version        int NOT NULL CHECK (version >= 1),
    rule_type      text NOT NULL CHECK (rule_type IN ('ddi', 'allergy', 'duplicate', 'drug_disease', 'class_lookback',
                                                      'vital_threshold', 'red_flag', 'emergency_message')),
    severity       text CHECK (severity IS NULL OR severity IN ('contraindicated', 'major', 'moderate', 'minor')),
    status         text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'rejected', 'superseded')),
    definition     jsonb NOT NULL CHECK (jsonb_typeof(definition) = 'object' AND definition <> '{}'::jsonb),
    explanation_en text NOT NULL CHECK (btrim(explanation_en) <> ''),
    explanation_bn text NOT NULL CHECK (btrim(explanation_bn) <> ''),
    created_by     uuid NOT NULL REFERENCES users (id),
    created_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
    reviewed_by    uuid REFERENCES users (id),
    reviewed_at    timestamptz,
    reason         text,                    -- why it was rejected; the audit log only says a reason was given
    UNIQUE (rule_id, version),
    CONSTRAINT rules_four_eyes CHECK (status NOT IN ('approved', 'superseded') OR reviewed_by IS DISTINCT FROM created_by)
);
CREATE UNIQUE INDEX IF NOT EXISTS rules_one_draft ON rules (rule_id) WHERE status = 'draft';
CREATE UNIQUE INDEX IF NOT EXISTS rules_one_approved ON rules (rule_id) WHERE status = 'approved';
CREATE INDEX IF NOT EXISTS rules_type ON rules (rule_type, status);

CREATE OR REPLACE FUNCTION rules_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'rule versions cannot be deleted';
    END IF;
    IF (NEW.id, NEW.rule_id, NEW.version, NEW.rule_type, NEW.severity, NEW.definition, NEW.explanation_en,
        NEW.explanation_bn, NEW.created_by, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.rule_id, OLD.version, OLD.rule_type, OLD.severity, OLD.definition, OLD.explanation_en,
                         OLD.explanation_bn, OLD.created_by, OLD.created_at) THEN
        RAISE EXCEPTION 'a rule version is immutable';
    END IF;
    IF NOT ((OLD.status = 'draft' AND NEW.status IN ('approved', 'rejected'))
            OR (OLD.status = 'approved' AND NEW.status = 'superseded')) THEN
        RAISE EXCEPTION 'illegal rule transition: % -> %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS rules_guard ON rules;
CREATE TRIGGER rules_guard BEFORE UPDATE OR DELETE ON rules FOR EACH ROW EXECUTE FUNCTION rules_guard();
DROP TRIGGER IF EXISTS rules_no_truncate ON rules;
CREATE TRIGGER rules_no_truncate BEFORE TRUNCATE ON rules FOR EACH STATEMENT EXECUTE FUNCTION append_only();

-- M6 safety alerts (B6; FRD M6, invariant 6). Nothing writes alerts yet: no M6 engine runs. An alert names the rule VERSION
-- that fired (shown with that version's explanation even after it is superseded) and keeps its evidence. Only the
-- handling fields change, and only open -> acknowledged | overridden; an override always carries a reason. Never deleted.
CREATE TABLE IF NOT EXISTS safety_alerts (
    id                 uuid PRIMARY KEY,
    patient_id         uuid NOT NULL REFERENCES patients (id),
    rule_version_id    uuid NOT NULL REFERENCES rules (id),
    severity           text NOT NULL CHECK (severity IN ('contraindicated', 'major', 'moderate', 'minor')),
    source_document_id uuid NOT NULL REFERENCES documents (id),
    evidence_event_ids uuid[] NOT NULL CHECK (cardinality(evidence_event_ids) > 0),
    created_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    status             text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'overridden')),
    handled_by         uuid REFERENCES users (id),
    handled_at         timestamptz,
    reason             text,
    CONSTRAINT safety_alerts_handled CHECK ((status = 'open') = (handled_by IS NULL AND handled_at IS NULL)),
    CONSTRAINT safety_alerts_override_reason CHECK (status <> 'overridden' OR btrim(coalesce(reason, '')) <> '')
);
CREATE INDEX IF NOT EXISTS safety_alerts_patient ON safety_alerts (patient_id, created_at DESC);

CREATE OR REPLACE FUNCTION safety_alerts_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'safety alerts cannot be deleted';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'open' OR NOT EXISTS (SELECT 1 FROM rules WHERE id = NEW.rule_version_id AND status = 'approved') THEN
            RAISE EXCEPTION 'an alert starts open and comes from an approved rule version';
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.id, NEW.patient_id, NEW.rule_version_id, NEW.severity, NEW.source_document_id, NEW.evidence_event_ids,
        NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.patient_id, OLD.rule_version_id, OLD.severity, OLD.source_document_id,
                         OLD.evidence_event_ids, OLD.created_at) THEN
        RAISE EXCEPTION 'a safety alert is immutable';
    END IF;
    IF NOT (OLD.status = 'open' AND NEW.status IN ('acknowledged', 'overridden')) THEN
        RAISE EXCEPTION 'illegal alert transition: % -> %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS safety_alerts_guard ON safety_alerts;
CREATE TRIGGER safety_alerts_guard BEFORE INSERT OR UPDATE OR DELETE ON safety_alerts
    FOR EACH ROW EXECUTE FUNCTION safety_alerts_guard();
DROP TRIGGER IF EXISTS safety_alerts_no_truncate ON safety_alerts;
CREATE TRIGGER safety_alerts_no_truncate BEFORE TRUNCATE ON safety_alerts FOR EACH STATEMENT EXECUTE FUNCTION append_only();

-- M13 per-patient threshold overrides (B6). One row per version, append-only; the newest version holds the whole set of
-- overrides (key = an approved vital_threshold rule_id, value a positive number). Version numbers start at 1; with no row
-- the patient is at version 0. Nothing evaluates readings against these yet.
CREATE TABLE IF NOT EXISTS patient_thresholds (
    patient_id uuid NOT NULL REFERENCES patients (id),
    version    int NOT NULL CHECK (version >= 1),
    overrides  jsonb NOT NULL CHECK (jsonb_typeof(overrides) = 'object'),
    updated_by uuid NOT NULL REFERENCES users (id),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (patient_id, version)
);
DROP TRIGGER IF EXISTS patient_thresholds_no_change ON patient_thresholds;
CREATE TRIGGER patient_thresholds_no_change BEFORE UPDATE OR DELETE ON patient_thresholds
    FOR EACH ROW EXECUTE FUNCTION append_only();
DROP TRIGGER IF EXISTS patient_thresholds_no_truncate ON patient_thresholds;
CREATE TRIGGER patient_thresholds_no_truncate BEFORE TRUNCATE ON patient_thresholds
    FOR EACH STATEMENT EXECUTE FUNCTION append_only();

-- Drug catalog uploads (B5; owner decision: validate and report only while FRD question 1, the licence, is open). The file
-- is read in memory by capture/drugcatalog.py and dropped; only its hash, size, the loader's counts and the admin's own
-- statement of where it came from are kept. No catalog data is stored anywhere. Append-only.
CREATE TABLE IF NOT EXISTS catalog_imports (
    id               uuid PRIMARY KEY,
    imported_by      uuid NOT NULL REFERENCES users (id),
    file_name        text NOT NULL,
    size_bytes       int NOT NULL CHECK (size_bytes > 0),
    sha256           text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    source_statement text NOT NULL CHECK (btrim(source_statement) <> ''),
    report           jsonb NOT NULL CHECK (jsonb_typeof(report) = 'object'),  -- counts only
    created_at       timestamptz NOT NULL DEFAULT clock_timestamp()
);
DROP TRIGGER IF EXISTS catalog_imports_no_change ON catalog_imports;
CREATE TRIGGER catalog_imports_no_change BEFORE UPDATE OR DELETE ON catalog_imports
    FOR EACH ROW EXECUTE FUNCTION append_only();
DROP TRIGGER IF EXISTS catalog_imports_no_truncate ON catalog_imports;
CREATE TRIGGER catalog_imports_no_truncate BEFORE TRUNCATE ON catalog_imports
    FOR EACH STATEMENT EXECUTE FUNCTION append_only();
