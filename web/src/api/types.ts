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

// ---- M13 home vitals (FRD section 7: POST /vitals, GET /vitals, POST /vitals/{id}/correct; response shapes PROPOSED here)

export type VitalType = "bp" | "glucose";
export type VitalUnit = "mmHg" | "mmol/L" | "mg/dL";
export type VitalContext = "home" | "resting" | "fasting" | "post_meal" | "random";

export interface VitalEntry {
  vital_type: VitalType;
  value: string; // "120/80" for BP, "6.2" for glucose; ASCII digits
  unit: VitalUnit;
  context: VitalContext;
  measured_at: string; // ISO
  confirmed?: boolean; // true after the patient confirmed a value the server called implausible (422 confirmation_required)
}

/** A `vital_reading` event: always patient_reported, never device-verified. A correction is a new reading that supersedes. */
export interface VitalReading extends Omit<VitalEntry, "confirmed"> {
  event_id: string;
  verification_status: "patient_reported";
  version: number;
  supersedes: string | null;
  recorded_at: string;
}

/** Text a clinical reviewer approved, in both languages, or a REVIEWER-PENDING placeholder until one exists. */
export interface ReviewedText {
  bn: string;
  en: string;
  status: "approved" | "REVIEWER-PENDING";
}

/** The server's evaluation against the reviewer-approved threshold rules (M6 registry). The client never decides this. */
export interface VitalEvaluation {
  level: "within_range" | "flagged" | "critical" | "not_evaluated";
  rule_id: string | null;
  message: ReviewedText | null; // the escalation or alert text; critical always carries one
}

export interface VitalSaved {
  reading: VitalReading;
  evaluation: VitalEvaluation;
}

// ---- M7 triage (FRD section 7: POST /triage/sessions, POST /triage/sessions/{id}/answer; shapes PROPOSED)

export interface TriageState {
  session_id: string;
  state: "question" | "emergency" | "suggestion";
  question: { id: string; text: ReviewedText; options: Array<{ id: string; text: ReviewedText }> } | null;
  suggestion: { department: ReviewedText; reason: ReviewedText } | null;
}

// ---- M8 reminders (FRD section 7: GET /reminders, PATCH /reminders/{id}, POST /reminders/{id}/log; shapes PROPOSED)

export type ReminderStatus = "proposed" | "active" | "paused" | "ended";
export type ReminderLogAction = "taken" | "skipped" | "snoozed";

export interface Reminder {
  id: string;
  kind: "medicine" | "follow_up" | "test";
  status: ReminderStatus;
  as_written: string; // repeats the verified prescription; never a suggested dose
  times: string[]; // "08:00", from the written frequency
  source_event_id: string; // a document_verified event
  log: Array<{ action: ReminderLogAction; at: string }>;
}

// ---- M10 emergency profile (FRD: PUT /me/emergency-profile. GAP: GET /me/emergency-profile, needed to show the current profile)

export type EmergencyField = "blood_group" | "allergies" | "active_medications" | "conditions" | "emergency_contacts";

export interface EmergencyProfile {
  enabled: boolean;
  fields: EmergencyField[];
  contacts: Array<{ name: string; phone: string }>;
  /** What the card could show, built from verified events only (null: nothing verified for it yet). */
  available: { blood_group: string | null; allergies: string[]; active_medications: string[]; conditions: string[] };
}

// ---- F3 doctor portal

/** POST /auth/otp/verify for staff: `account: "staff"`, and on first login `staff: { role, name }`. BUILT. */
export interface StaffVerifyBody {
  phone: string;
  code: string;
  device_id: string;
  account: "staff";
  staff?: { role: "doctor" | "verifier" | "clinical_reviewer"; name: string };
}

export type StaffStatus = "pending" | "verified" | "suspended";

/** GET /me for a staff member. GAP: the approved GET /me covers patients; a doctor needs their own credential status (BMDC)
 * to know whether they may request consent. Mocked; owner to decide. */
export interface StaffMe {
  id: string;
  role: "doctor";
  name: string;
  status: StaffStatus;
  emergency_enabled: boolean;
  credential: { type: "BMDC"; number: string; status: StaffStatus } | null;
}

/** POST /credentials { type, number, doc_key? } -> { id, status }. BUILT. */
export interface CredentialBody {
  type: "BMDC";
  number: string;
}

/** POST /consents/requests { health_id, categories } and POST /consents/requests/{id}/confirm { code }. BUILT, but the response
 * has no patient: GAP `patient_id` (and the Health ID echoed back) so the doctor can open the record. Mocked with both. */
export interface DoctorConsent {
  id: string;
  purpose: "TIMELINE";
  allowed_categories: Array<"timeline" | "documents" | "safety">;
  status: "pending" | "active" | "expired" | "revoked" | "declined" | "suspended";
  activated_at: string | null;
  expires_at: string | null;
  created_at: string;
  patient_id: string; // GAP
  health_id: string; // GAP
}

/** One sentence of a summary, with the events it cites (invariant 3). */
export interface Cited {
  text: string;
  citations: string[];
}

/** GET /patients/{id}/summary. FRD (M5), not built. `mode: template` when no LLM adapter is configured or validation failed. */
export interface Summary {
  mode: "llm" | "template";
  generated_at: string;
  sections: Array<{ id: "active_medications" | "allergies" | "diagnoses" | "labs" | "visits" | "follow_ups"; sentences: Cited[] }>;
  patient_reported: Cited[]; // home vitals: a separate section, "reported by patient, not verified"
}

/** GET /patients/{id}/search?q= : event ids with source links, never generated answers. FRD (M5), not built. */
export interface SearchHit {
  event_id: string;
  event_type: EventType;
  date: string;
  source_document_id: string | null;
  snippet: string;
}

export type Severity = "contraindicated" | "major" | "moderate" | "minor";

/** An M6 alert on a newly verified prescription. Ack: POST /safety/alerts/{id}/ack { action, reason } (FRD). Listing alerts:
 * GAP `GET /patients/{id}/safety-alerts` (the FRD has no list endpoint). Mocked. */
export interface SafetyAlert {
  id: string;
  rule_id: string;
  severity: Severity;
  explanation: ReviewedText;
  evidence_event_ids: string[];
  source_document_id: string;
  created_at: string;
  status: "open" | "acknowledged" | "overridden";
  reason: string | null;
}

/** POST /emergency/access { health_id, reason, facility }. FRD (M10), not built; only with VITE_FEATURE_EMERGENCY_ACCESS=1. */
export interface EmergencySession {
  session_id: string;
  expires_at: string;
  card: { blood_group?: string; allergies?: string[]; active_medications?: string[]; conditions?: string[];
          emergency_contacts?: Array<{ name: string; phone: string }> } | null; // null: the patient has no emergency profile on
}
