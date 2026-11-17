-- M10 emergency access (B7; FRD M10, owner decisions 2026-11-17). Idempotent. Applied after safety/schema.sql.
-- Every route is refused unless the server flag EMERGENCY_ACCESS_ENABLED=1 is set (owner decision 9, 2026-11-16).

-- The patient's emergency profile: off until the patient turns it on; the patient picks the card fields. Contacts (names
-- and phone numbers) are stored sealed like other personal details. The card's values are read from verified events when
-- a session opens, never stored here.
CREATE TABLE IF NOT EXISTS emergency_profiles (
    patient_id   uuid PRIMARY KEY REFERENCES patients (id),
    enabled      boolean NOT NULL DEFAULT false,
    fields       text[] NOT NULL DEFAULT '{}'
                 CHECK (fields <@ ARRAY['blood_group', 'allergies', 'active_medications', 'conditions', 'emergency_contacts']),
    contacts_enc text,
    updated_at   timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- One row per break-glass session. Time-boxed: closed once ends_at has passed, then waiting for post-hoc review. Only the
-- review fields change, only review_pending -> justified | unjustified, and only after the session has closed; an
-- unjustified decision always carries a note. Never deleted. fields_shown names the card fields, never their values.
CREATE TABLE IF NOT EXISTS emergency_sessions (
    id            uuid PRIMARY KEY,
    doctor_id     uuid NOT NULL REFERENCES users (id),
    patient_id    uuid NOT NULL REFERENCES patients (id),
    reason        text NOT NULL CHECK (btrim(reason) <> ''),
    facility      text NOT NULL CHECK (btrim(facility) <> ''),
    fields_shown  text[] NOT NULL,
    started_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
    ends_at       timestamptz NOT NULL,
    review_status text NOT NULL DEFAULT 'review_pending'
                  CHECK (review_status IN ('review_pending', 'justified', 'unjustified')),
    reviewed_by   uuid REFERENCES users (id),
    reviewed_at   timestamptz,
    note          text,
    CONSTRAINT emergency_sessions_time_box CHECK (ends_at > started_at),
    CONSTRAINT emergency_sessions_reviewed CHECK ((review_status = 'review_pending') = (reviewed_by IS NULL AND reviewed_at IS NULL)),
    CONSTRAINT emergency_sessions_unjustified_note CHECK (review_status <> 'unjustified' OR btrim(coalesce(note, '')) <> '')
);
CREATE INDEX IF NOT EXISTS emergency_sessions_ends ON emergency_sessions (ends_at DESC);

CREATE OR REPLACE FUNCTION emergency_sessions_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'emergency sessions cannot be deleted';
    END IF;
    IF (NEW.id, NEW.doctor_id, NEW.patient_id, NEW.reason, NEW.facility, NEW.fields_shown, NEW.started_at, NEW.ends_at)
       IS DISTINCT FROM (OLD.id, OLD.doctor_id, OLD.patient_id, OLD.reason, OLD.facility, OLD.fields_shown, OLD.started_at,
                         OLD.ends_at) THEN
        RAISE EXCEPTION 'an emergency session is immutable';
    END IF;
    IF NOT (OLD.review_status = 'review_pending' AND NEW.review_status IN ('justified', 'unjustified')) THEN
        RAISE EXCEPTION 'illegal review transition: % -> %', OLD.review_status, NEW.review_status;
    END IF;
    IF clock_timestamp() < OLD.ends_at THEN
        RAISE EXCEPTION 'an emergency session is reviewed only after it has closed';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS emergency_sessions_guard ON emergency_sessions;
CREATE TRIGGER emergency_sessions_guard BEFORE UPDATE OR DELETE ON emergency_sessions
    FOR EACH ROW EXECUTE FUNCTION emergency_sessions_guard();
DROP TRIGGER IF EXISTS emergency_sessions_no_truncate ON emergency_sessions;
CREATE TRIGGER emergency_sessions_no_truncate BEFORE TRUNCATE ON emergency_sessions
    FOR EACH STATEMENT EXECUTE FUNCTION append_only();
