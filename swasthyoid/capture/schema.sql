-- M2 capture schema (FRD ERD B). Idempotent. Applied after identity/schema.sql.

CREATE TABLE IF NOT EXISTS documents (
    id          uuid PRIMARY KEY,
    patient_id  uuid NOT NULL REFERENCES patients (id),   -- whose record this is
    doc_type    text NOT NULL CHECK (doc_type IN ('prescription', 'lab_report', 'discharge_summary', 'other')),
    status      text NOT NULL DEFAULT 'uploaded' CHECK (status IN (
                    'uploaded', 'extracting', 'needs_review', 'extraction_failed', 'verified', 'rejected')),
    uploaded_by uuid NOT NULL,                             -- the patient, or a caregiver acting for them
    verified_by uuid,
    created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at  timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS documents_patient ON documents (patient_id, status);

-- A document's origin never changes and it is never deleted; only its status moves on.
CREATE OR REPLACE FUNCTION documents_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'documents cannot be deleted';
    END IF;
    IF (NEW.id, NEW.patient_id, NEW.doc_type, NEW.uploaded_by, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.patient_id, OLD.doc_type, OLD.uploaded_by, OLD.created_at) THEN
        RAISE EXCEPTION 'the origin of a document is immutable';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS documents_guard ON documents;
CREATE TRIGGER documents_guard BEFORE UPDATE OR DELETE ON documents
    FOR EACH ROW EXECUTE FUNCTION documents_guard();
DROP TRIGGER IF EXISTS documents_no_truncate ON documents;
CREATE TRIGGER documents_no_truncate BEFORE TRUNCATE ON documents
    FOR EACH STATEMENT EXECUTE FUNCTION append_only();

-- The original images: append-only records with a SHA-256 of the uploaded bytes, checked
-- on every read. The ERD keeps keys in documents.image_keys; a separate append-only table
-- is used so the originals can never be edited or dropped while the status changes.
CREATE TABLE IF NOT EXISTS document_images (
    document_id  uuid NOT NULL REFERENCES documents (id),
    n            int NOT NULL CHECK (n >= 1),
    storage_key  text NOT NULL UNIQUE,
    content_type text NOT NULL CHECK (content_type IN ('image/jpeg', 'image/png')),
    size_bytes   int NOT NULL CHECK (size_bytes > 0),
    sha256       text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (document_id, n)
);

DROP TRIGGER IF EXISTS document_images_no_change ON document_images;
CREATE TRIGGER document_images_no_change BEFORE UPDATE OR DELETE ON document_images
    FOR EACH ROW EXECUTE FUNCTION append_only();
DROP TRIGGER IF EXISTS document_images_no_truncate ON document_images;
CREATE TRIGGER document_images_no_truncate BEFORE TRUNCATE ON document_images
    FOR EACH STATEMENT EXECUTE FUNCTION append_only();

-- Extraction job state. The documents table is the queue: `uploaded` rows and `extracting`
-- rows whose retry time has come are due.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS extraction_attempts int NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS next_extraction_at timestamptz;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS extraction_error text;  -- error type only, never document text
-- Fencing token of the attempt that holds the document; a new one on every claim. While set,
-- next_extraction_at is the end of that attempt's lease.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS extraction_claim uuid;
-- An `extracting` document always has a time at which it is due (lease end or retry time),
-- so none can be stranded. Rows from before this rule are made due now.
UPDATE documents SET next_extraction_at = clock_timestamp()
    WHERE status = 'extracting' AND next_extraction_at IS NULL;
ALTER TABLE documents DROP CONSTRAINT IF EXISTS extracting_has_time;
ALTER TABLE documents ADD CONSTRAINT extracting_has_time
    CHECK (status <> 'extracting' OR next_extraction_at IS NOT NULL);

-- What was read from a document, for human review. Never the timeline: only M3's confirm
-- step writes events. One row per (document, version); a repeat of the same job is a no-op.
CREATE TABLE IF NOT EXISTS extractions (
    id          uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents (id),
    version     int NOT NULL CHECK (version >= 1),
    engine      text NOT NULL CHECK (engine <> ''),
    fields      jsonb NOT NULL CHECK (jsonb_typeof(fields) = 'object'),
    -- PRIVACY RISK (docs/DECISIONS.md): raw_text and fields hold unverified document text in
    -- plain form. Do not deploy with real patient data before the mitigation there is done.
    raw_text    text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (document_id, version)
);

DROP TRIGGER IF EXISTS extractions_no_change ON extractions;
CREATE TRIGGER extractions_no_change BEFORE UPDATE OR DELETE ON extractions
    FOR EACH ROW EXECUTE FUNCTION append_only();
DROP TRIGGER IF EXISTS extractions_no_truncate ON extractions;
CREATE TRIGGER extractions_no_truncate BEFORE TRUNCATE ON extractions
    FOR EACH STATEMENT EXECUTE FUNCTION append_only();
