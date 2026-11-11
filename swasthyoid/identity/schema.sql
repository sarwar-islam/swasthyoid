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
    role              text NOT NULL CHECK (role IN ('doctor', 'pharmacist', 'verifier', 'clinical_reviewer', 'admin')),
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

CREATE TABLE IF NOT EXISTS credentials (
    id          uuid PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users (id),
    type        text NOT NULL CHECK (type <> ''),      -- e.g. BMDC number, pharmacy licence
    number      text NOT NULL UNIQUE CHECK (number <> ''),
    doc_key     text,                                  -- object-storage key of the credential document
    status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'suspended')),
    reviewed_by uuid REFERENCES users (id),
    created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at  timestamptz NOT NULL DEFAULT clock_timestamp()
);

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
