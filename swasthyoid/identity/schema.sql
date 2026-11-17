-- M1 identity schema (FRD ERD A). Idempotent. Applied after core/schema.sql.
-- PENDING: foreign keys from the core tables (audit_logs, events, consents, notifications)
-- to patients and users are not added yet; they come with the end-to-end fixtures in slice 7.

CREATE TABLE IF NOT EXISTS patients (
    id              uuid PRIMARY KEY,
    health_id       text NOT NULL UNIQUE,
    phone_hash      text NOT NULL UNIQUE,       -- lookup only; the number itself is in phone_enc
    phone_enc       text NOT NULL,
    name_enc        text NOT NULL,
    dob             date NOT NULL,
    sex             text NOT NULL CHECK (sex <> ''),  -- DECISION-PENDING: allowed values not in the FRD
    language        text NOT NULL DEFAULT 'bn',
    cloud_ai_opt_in boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS users (
    id                uuid PRIMARY KEY,
    role              text NOT NULL CHECK (role IN ('doctor', 'verifier', 'clinical_reviewer', 'admin')),
    name              text NOT NULL CHECK (name <> ''),
    status            text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'suspended')),
    clinic_id         uuid,                     -- clinics table arrives with the module that needs it
    emergency_enabled boolean NOT NULL DEFAULT false,
    -- DECISION-PENDING: the ERD gives users no phone, but every role logs in by phone OTP (FRD 7).
    phone_hash        text NOT NULL UNIQUE,
    phone_enc         text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at        timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- FRD v4: the pharmacist role went with M11 (also for a database created before v4).
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('doctor', 'verifier', 'clinical_reviewer', 'admin'));

CREATE TABLE IF NOT EXISTS credentials (
    id          uuid PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users (id),
    type        text NOT NULL CHECK (type <> ''),      -- e.g. BMDC number
    number      text NOT NULL CHECK (number <> ''),    -- unique among credentials not rejected (index below)
    doc_key     text,                                  -- object-storage key of the credential document
    status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'suspended', 'rejected')),
    reviewed_by uuid REFERENCES users (id),
    created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at  timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- B2 (owner decision 2026-11-16): a rejected credential is kept with the admin's reason, and its number may be submitted
-- again. Also upgrades a database created before B2.
ALTER TABLE credentials ADD COLUMN IF NOT EXISTS review_reason text;
ALTER TABLE credentials DROP CONSTRAINT IF EXISTS credentials_number_key;
CREATE UNIQUE INDEX IF NOT EXISTS credentials_number_live ON credentials (number) WHERE status <> 'rejected';
ALTER TABLE credentials DROP CONSTRAINT IF EXISTS credentials_status_check;
ALTER TABLE credentials ADD CONSTRAINT credentials_status_check CHECK (status IN ('pending', 'verified', 'suspended', 'rejected'));
-- The admin's reason for the last status change of a staff account (suspension). Never written to the audit log.
ALTER TABLE users ADD COLUMN IF NOT EXISTS status_reason text;

-- One-time codes. Only a keyed hash of the code is stored.
CREATE TABLE IF NOT EXISTS otp_codes (
    id         uuid PRIMARY KEY,
    phone_hash text NOT NULL,
    kind       text NOT NULL,                   -- 'login' or 'consent'
    ref        text NOT NULL DEFAULT '',        -- what the code confirms, e.g. a consent id
    code_hash  text NOT NULL,
    expires_at timestamptz NOT NULL,
    attempts   int NOT NULL DEFAULT 0,
    used_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS otp_codes_phone ON otp_codes (phone_hash, created_at);

-- Refresh tokens, bound to a device. Only a keyed hash of the token is stored.
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id         uuid PRIMARY KEY,
    subject_id uuid NOT NULL,                   -- a patient id or a user id
    role       text NOT NULL,
    device_id  text NOT NULL CHECK (device_id <> ''),
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS refresh_tokens_subject ON refresh_tokens (subject_id);
-- W2: every request checks that its device's session is live (identity/sessions.py touch)
CREATE INDEX IF NOT EXISTS refresh_tokens_live ON refresh_tokens (subject_id, device_id) WHERE revoked_at IS NULL;
-- W2 idle timeout: the last request of the session this token belongs to (carried over when the token rotates)
ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp();
