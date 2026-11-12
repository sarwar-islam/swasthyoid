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

-- C1 consents (FRD 4.1, ERD A). The row holds the current state; every change is
-- also written to consent_events (append-only) and to audit_logs.
CREATE TABLE IF NOT EXISTS consents (
    id                 uuid PRIMARY KEY,
    patient_id         uuid NOT NULL,
    grantee_id         uuid NOT NULL,
    grantee_role       text NOT NULL CHECK (grantee_role <> ''),
    purpose            text NOT NULL CHECK (purpose IN (
                           'TIMELINE', 'APPOINTMENT', 'REFERRAL', 'DISPENSING', 'EMERGENCY', 'CLOUD_AI')),
    resource_type      text,
    resource_id        uuid,
    allowed_categories text[] NOT NULL CHECK (cardinality(allowed_categories) > 0),
    method             text,                    -- OTP / QR / in-app, set on activation
    status             text NOT NULL CHECK (status IN ('pending', 'active', 'suspended', 'expired', 'revoked')),
    activated_at       timestamptz,
    expires_at         timestamptz,
    max_window_ends_at timestamptz,
    revoked_at         timestamptz,
    revoked_by         uuid,
    -- LEGAL-PENDING (FRD open question 8): versions of the consent wording and policy shown to the patient.
    consent_version    int NOT NULL,
    policy_version     text NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT binding_is_whole CHECK ((resource_type IS NULL) = (resource_id IS NULL)),
    CONSTRAINT active_has_expiry CHECK (status <> 'active' OR expires_at IS NOT NULL)
);
-- Foreign keys to patients and users are added with those tables (slice 6).

CREATE INDEX IF NOT EXISTS consents_lookup ON consents (grantee_id, patient_id, purpose, status);

CREATE TABLE IF NOT EXISTS consent_events (
    id         uuid PRIMARY KEY,
    consent_id uuid NOT NULL REFERENCES consents (id),
    action     text NOT NULL,
    actor_id   uuid,                            -- null when the system acts (expiry)
    at         timestamptz NOT NULL DEFAULT clock_timestamp()
);

DROP TRIGGER IF EXISTS consent_events_no_change ON consent_events;
CREATE TRIGGER consent_events_no_change BEFORE UPDATE OR DELETE ON consent_events
    FOR EACH ROW EXECUTE FUNCTION append_only();

DROP TRIGGER IF EXISTS consent_events_no_truncate ON consent_events;
CREATE TRIGGER consent_events_no_truncate BEFORE TRUNCATE ON consent_events
    FOR EACH STATEMENT EXECUTE FUNCTION append_only();

-- C3 notifications (FRD 4.3, ERD D). The table is the queue: a row is written in the
-- source module's transaction, then a worker delivers it.
CREATE TABLE IF NOT EXISTS notifications (
    id              uuid PRIMARY KEY,
    recipient_id    uuid NOT NULL,
    template_id     text NOT NULL CHECK (template_id <> ''),
    payload         jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    status          text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'delivered', 'fallback_in_app')),
    attempts        int NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS notifications_due ON notifications (next_attempt_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS notifications_recipient ON notifications (recipient_id, created_at);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id              uuid PRIMARY KEY,
    notification_id uuid NOT NULL REFERENCES notifications (id),
    channel         text NOT NULL,
    attempt         int NOT NULL,
    status          text NOT NULL CHECK (status IN ('sent', 'failed')),
    error           text,
    at              timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Platform: Idempotency-Key replay for authenticated writes (FRD 7, ERD D).
-- The ERD keys this table by `key` alone; it is scoped per caller and endpoint here so
-- two callers can never collide on, or read back, each other's keys.
CREATE TABLE IF NOT EXISTS idempotency_keys (
    actor_id     uuid NOT NULL,
    endpoint     text NOT NULL,                 -- method and path
    key          text NOT NULL,
    request_hash text NOT NULL,
    response     jsonb,                         -- null while the first request is still running
    expires_at   timestamptz NOT NULL,
    PRIMARY KEY (actor_id, endpoint, key)
);

-- Caregiver-assisted access (DECISIONS.md, "Caregiver access"). Idempotent upgrades of
-- the consents table: a new purpose, a new `declined` state, and the caregiver rules.
ALTER TABLE consents ADD COLUMN IF NOT EXISTS requested_ttl interval;  -- duration asked for, applied on approval

ALTER TABLE consents DROP CONSTRAINT IF EXISTS consents_purpose_check;
ALTER TABLE consents ADD CONSTRAINT consents_purpose_check CHECK (purpose IN (
    'TIMELINE', 'APPOINTMENT', 'REFERRAL', 'DISPENSING', 'EMERGENCY', 'CLOUD_AI', 'CAREGIVER'));

ALTER TABLE consents DROP CONSTRAINT IF EXISTS consents_status_check;
ALTER TABLE consents ADD CONSTRAINT consents_status_check CHECK (status IN (
    'pending', 'active', 'suspended', 'expired', 'revoked', 'declined'));

-- A caregiver authorization: fixed role, no resource binding, never yourself, only the three
-- approved scopes (verify_documents is deliberately absent: caregivers cannot verify), and
-- never longer than 90 days. PROVISIONAL: 90 days also lives in core/consent_authz.py.
ALTER TABLE consents DROP CONSTRAINT IF EXISTS caregiver_shape;
ALTER TABLE consents ADD CONSTRAINT caregiver_shape CHECK (purpose <> 'CAREGIVER' OR (
    grantee_role = 'caregiver'
    AND resource_type IS NULL
    AND grantee_id <> patient_id
    AND allowed_categories <@ ARRAY['upload_documents', 'view_documents', 'view_timeline']
    AND requested_ttl IS NOT NULL
    AND requested_ttl > interval '0'
    AND requested_ttl <= interval '90 days'
    AND (expires_at IS NULL OR activated_at IS NULL OR expires_at <= activated_at + interval '90 days')));

-- At most one active and one pending authorization per patient-caregiver pair. The pending
-- one is the request for renewal or different scopes; approving it replaces the active one.
CREATE UNIQUE INDEX IF NOT EXISTS caregiver_one_active ON consents (patient_id, grantee_id)
    WHERE purpose = 'CAREGIVER' AND status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS caregiver_one_pending ON consents (patient_id, grantee_id)
    WHERE purpose = 'CAREGIVER' AND status = 'pending';
