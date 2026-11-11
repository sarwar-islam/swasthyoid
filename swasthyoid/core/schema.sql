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

CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only';
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_logs_no_change ON audit_logs;
CREATE TRIGGER audit_logs_no_change BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only();

DROP TRIGGER IF EXISTS audit_logs_no_truncate ON audit_logs;
CREATE TRIGGER audit_logs_no_truncate BEFORE TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_append_only();

-- DEPLOYMENT-PENDING (DECISIONS.md Q4): the application's database role must also be
-- granted INSERT and SELECT only on audit_logs. The triggers above do not stop the
-- table owner from disabling them.
