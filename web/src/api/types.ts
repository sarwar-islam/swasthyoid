// Shapes of /api/v1 (docs/FRD.md v4 section 7). "BUILT" = the FastAPI route exists today (swasthyoid/api/); "APPROVED" = an owner-approved contract not built yet; "FRD" = specified,
// not built (mocked from the FRD); "GAP" = needed by the UI but not in the FRD (mocked, owner to decide). Field names follow the
// backend exactly. Only in-scope modules: M1-M8, M10, M13.

/** Every error: `{ "code", "message", "details" }`. BUILT. */
export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

// ---- M1 identity

/** POST /auth/otp/request. BUILT (204). */
export interface OtpRequestBody {
  phone: string;
}

export interface PatientProfile {
  name: string;
  dob: string; // YYYY-MM-DD
  sex: string;
  language?: "bn" | "en";
}

/** POST /auth/otp/verify. BUILT. 409 `registration_required` when a new patient sends no profile (request a new code). */
export interface OtpVerifyBody {
  phone: string;
  code: string;
  device_id: string;
  account?: "patient" | "staff";
  profile?: PatientProfile;
}

/** POST /auth/otp/verify, /auth/refresh. BUILT. The access token is a JWT with `sub` (the user id) and `role`. */
export interface TokenPair {
  access_token: string;
  refresh_token: string;
}

/** GET /me. APPROVED contract (owner decision 2026-11-15), not built yet: the authenticated patient's own Health ID, profile
 * metadata and cloud-AI opt-in flag, for the Home card. Mocked until the backend implements it. */
export interface Me {
  id: string;
  health_id: string; // SID- + 10 digits
  name: string;
  language: "bn" | "en";
  cloud_ai_opt_in: boolean;
}

// ---- C1 consent (M1 Consent Center)

export type ConsentPurpose = "TIMELINE" | "EMERGENCY" | "CLOUD_AI" | "CAREGIVER";
export type ConsentStatus = "pending" | "active" | "expired" | "revoked" | "declined" | "suspended";

/** An item of GET /consents. BUILT. */
export interface Consent {
  id: string;
  grantee_id: string;
  grantee_role: string;
  purpose: ConsentPurpose;
  allowed_categories: string[]; // TIMELINE: timeline, documents, safety; CAREGIVER: upload_documents, view_documents, view_timeline
  status: ConsentStatus;
  activated_at: string | null;
  expires_at: string | null;
  created_at: string;
  grantee_name: string | null;
  grantee_phone_tail: string | null; // caregivers only
  requested_days: number | null; // caregiver requests
}

/** An item of GET /me/access-history (newest first). BUILT. */
export interface AccessEntry {
  at: string;
  actor_id: string | null;
  actor_role: string | null;
  action: string;
  purpose: string | null;
  result: "allow" | "deny";
  reason: string | null;
  consent_id: string | null;
  actor_name: string | null;
}

// ---- M2 capture

export type DocType = "prescription" | "lab_report" | "discharge_summary" | "other";
export type DocStatus = "uploaded" | "extracting" | "needs_review" | "extraction_failed" | "verified" | "rejected";
export type QualityCode = "image_blurry" | "image_glare" | "image_low_contrast" | "image_skewed" | "image_too_small";

export interface DocImage {
  n: number;
  content_type: string;
  size_bytes: number;
  sha256: string;
  quality_warnings: QualityCode[] | null;
}

/** POST /documents (multipart: doc_type, images[1-10], upload_anyway), GET /documents/{id}, GET /patients/{id}/documents. BUILT. */
export interface DocumentView {
  id: string;
  patient_id: string;
  doc_type: DocType;
  status: DocStatus;
  uploaded_by: string;
  created_at: string;
  images: DocImage[];
}

/** `details` of 422 image_quality_warning. BUILT. `bn` guidance is the approved text from capture/guidance.py. */
export interface QualityWarningDetails {
  pages: Array<{ page: number; reasons: QualityCode[]; guidance: Array<{ code: QualityCode; bn: string }> }>;
}

// ---- M2/M3 extraction and verification

/** One schema field (capture/extraction.py `_field`). BUILT. */
export interface ExtractedField {
  value: string | null;
  raw: string | null;
  confidence: number;
  source: "ocr" | "cloud_ai" | null;
  manual_entry: boolean;
  error?: string;
}

export type FieldRow = Record<string, ExtractedField>;
export type ExtractedFields = Record<string, ExtractedField | FieldRow[]>;

/** GET /documents/{id}/extraction (patient only). BUILT. `extraction` is null before any extraction exists. */
export interface ExtractionResponse {
  document_id: string;
  status: DocStatus;
  threshold: number; // the review threshold (0.85, FRD M3)
  extraction: null | {
    version: number;
    engine: string;
    fields: ExtractedFields;
    raw_text: string;
    raw_text_available: boolean;
    created_at: string;
    printed_name_check: "same_after_normalisation" | "not_the_same" | "not_checked";
  };
}

/** PUT /documents/{id}/review then POST /documents/{id}/confirm or /reject. FRD (M3), not built. */
export interface ReviewBody {
  fields: Record<string, string | null | Array<Record<string, string | null>>>;
}

// ---- M4 timeline

export type Provenance = "document_verified" | "patient_reported";
export type EventType = "visit" | "diagnosis" | "medication" | "lab_result" | "allergy" | "follow_up" | "prescription" | "vital_reading";

/** An item of GET /patients/{id}/timeline. FRD (C4 mandatory fields, trimmed to what the UI shows), not built. */
export interface TimelineEvent {
  event_id: string;
  event_type: EventType;
  date: string;
  date_precision: "day" | "month" | "year";
  verification_status: Provenance;
  source_document_id: string | null;
  recorded_at: string;
  version: number;
  supersedes: string | null; // the event this one corrects
  payload: Record<string, string>;
}
