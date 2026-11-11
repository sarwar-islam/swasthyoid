-- Core schema. Idempotent: safe to apply on every start.
-- shortcut: no migration tool, upgrade to Alembic at the first change to a deployed table.

-- C2 audit log (FRD 4.2, ERD D). Append-only and hash-chained.
CREATE TABLE IF NOT EXISTS audit_logs (
    seq           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id            uuid NOT NULL UNIQUE,
    at            timestamptz NOT NULL,        -- server time, set by core.audit.append
    actor_id      uuid,                        -- null for failed logins with no known actor
    actor_role    text,
    device_id     text,
    ip            text,
    user_agent    text,
    action        text NOT NULL,
    patient_id    uuid,
    resource_type text,
    resource_id   uuid,
    consent_id    uuid,
    purpose       text,
    result        text NOT NULL,
    reason        text,
    prev_hash     text NOT NULL UNIQUE,        -- UNIQUE: the chain can never fork
    entry_hash    text NOT NULL UNIQUE
);
-- Foreign keys to users, patients and consents are added with those tables (slices 4 and 6).

-- Shared by every append-only table.
CREATE OR REPLACE FUNCTION append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_logs_no_change ON audit_logs;
CREATE TRIGGER audit_logs_no_change BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION append_only();

DROP TRIGGER IF EXISTS audit_logs_no_truncate ON audit_logs;
CREATE TRIGGER audit_logs_no_truncate BEFORE TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION append_only();

-- DEPLOYMENT-PENDING (DECISIONS.md Q4): the application's database role must also be
-- granted INSERT and SELECT only on audit_logs and events. The triggers above do not stop the
-- table owner from disabling them.

-- C4 events with provenance (FRD 4.4, ERD B). Append-only: a correction is a new
-- row whose `supersedes` points at the old one.
CREATE TABLE IF NOT EXISTS events (
    id                  uuid PRIMARY KEY,
    patient_id          uuid NOT NULL,
    event_type          text NOT NULL CHECK (event_type IN (
                            'visit', 'diagnosis', 'medication', 'lab_result', 'allergy', 'follow_up',
                            'prescription', 'dispense', 'vital_reading', 'referral', 'referral_feedback')),
    event_date          date NOT NULL,
    -- DECISION-PENDING: the FRD names date_precision but not its values; day/month/year assumed.
    date_precision      text NOT NULL CHECK (date_precision IN ('day', 'month', 'year')),
    actor_id            uuid NOT NULL,
    actor_role          text NOT NULL CHECK (actor_role <> ''),
    -- DECISION-PENDING: the FRD does not list source_type values, so any non-empty text is accepted.
    source_type         text NOT NULL CHECK (source_type <> ''),
    source_document_id  uuid,
    recorded_at         timestamptz NOT NULL DEFAULT clock_timestamp(),  -- server time
    verified_by         uuid,
    verified_at         timestamptz,
    verification_status text NOT NULL CHECK (verification_status IN (
                            'document_verified', 'clinician_authored', 'pharmacist_recorded',
                            'doctor_submitted', 'patient_reported', 'pending')),
    related_record_id   uuid,
    version             int NOT NULL CHECK (version >= 1),
    supersedes          uuid UNIQUE REFERENCES events (id),  -- UNIQUE: one successor per event
    payload             jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    -- Invariant 1: paper data counts as verified only with a human verifier and its source document.
    CONSTRAINT document_verified_has_provenance CHECK (
        verification_status <> 'document_verified'
        OR (verified_by IS NOT NULL AND verified_at IS NOT NULL AND source_document_id IS NOT NULL)),
    CONSTRAINT version_matches_supersedes CHECK ((supersedes IS NULL) = (version = 1))
);
-- Foreign keys to patients, users and documents are added with those tables.

CREATE INDEX IF NOT EXISTS events_patient_date ON events (patient_id, event_date);
CREATE INDEX IF NOT EXISTS events_patient_type ON events (patient_id, event_type);

DROP TRIGGER IF EXISTS events_no_change ON events;
CREATE TRIGGER events_no_change BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION append_only();

DROP TRIGGER IF EXISTS events_no_truncate ON events;
CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON events
    FOR EACH STATEMENT EXECUTE FUNCTION append_only();
