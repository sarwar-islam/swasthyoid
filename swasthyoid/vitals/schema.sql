-- M13 home vitals (P6; FRD M13, owner decisions V1-V6 and safeguards 1-7, 2026-11-17). Idempotent. Applied after
-- safety/schema.sql.
--
-- One row per saved reading, keyed by the reading id the patient's app made (safeguard 4), per patient so one patient's
-- ids can never collide with, or reveal, another's. The reading itself is the `vital_reading` event (C4,
-- patient_reported); this row holds what the event does not: the request fingerprint for idempotent retries, the
-- evaluation made when it was saved, the correction it is (if any) and the notice it queued. Append-only: a correction
-- is a new row with supersedes_reading_id, never a change to the original.
CREATE TABLE IF NOT EXISTS vital_readings (
    patient_id            uuid NOT NULL REFERENCES patients (id),
    id                    uuid NOT NULL,
    event_id              uuid NOT NULL UNIQUE REFERENCES events (id),
    request_hash          text NOT NULL,
    supersedes_reading_id uuid,
    correction_reason     text,
    actor_id              uuid NOT NULL,
    confirmed             boolean NOT NULL DEFAULT false,
    -- {level, rule_id, rule_version_id, reason}: never text; a message is read from the rule version that fired
    evaluation            jsonb NOT NULL CHECK (evaluation ->> 'level' IN ('within_range', 'flagged', 'critical', 'not_evaluated')),
    notification_id       uuid REFERENCES notifications (id),
    created_at            timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (patient_id, id),
    FOREIGN KEY (patient_id, supersedes_reading_id) REFERENCES vital_readings (patient_id, id),
    CONSTRAINT vital_correction_has_reason CHECK ((supersedes_reading_id IS NULL) = (correction_reason IS NULL)),
    -- safeguard 2: a reading the system could not evaluate (or found within range) never queues an urgent notice
    CONSTRAINT vital_notice_only_when_fired CHECK (
        notification_id IS NULL OR evaluation ->> 'level' IN ('flagged', 'critical'))
);
CREATE UNIQUE INDEX IF NOT EXISTS vital_readings_one_correction ON vital_readings (patient_id, supersedes_reading_id)
    WHERE supersedes_reading_id IS NOT NULL;

DROP TRIGGER IF EXISTS vital_readings_no_change ON vital_readings;
CREATE TRIGGER vital_readings_no_change BEFORE UPDATE OR DELETE ON vital_readings
    FOR EACH ROW EXECUTE FUNCTION append_only();
DROP TRIGGER IF EXISTS vital_readings_no_truncate ON vital_readings;
CREATE TRIGGER vital_readings_no_truncate BEFORE TRUNCATE ON vital_readings
    FOR EACH STATEMENT EXECUTE FUNCTION append_only();
