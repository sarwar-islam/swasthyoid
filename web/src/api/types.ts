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
  role: "doctor" | "verifier" | "clinical_reviewer" | "admin";
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

// ---- F4 caregiver mode (M1/C1 caregiver routes, BUILT in swasthyoid/api/caregivers.py)

export type CaregiverScope = "upload_documents" | "view_documents" | "view_timeline";

/** POST /caregiver-authorizations { patient_health_id, scopes, duration_days } -> 202 { status: "pending" }, whether or not the
 * Health ID exists (nothing is granted until the patient approves). BUILT. */
export interface CaregiverRequestBody {
  patient_health_id: string;
  scopes: CaregiverScope[];
  duration_days: number; // 1 to 90, default 30 (PROVISIONAL values, docs/DECISIONS.md "Caregiver access")
}

/** An item of GET /caregiver-authorizations (active, unexpired only; pending requests are never listed), and the answer of
 * POST /caregiver-authorizations/confirm { patient_health_id, code }. BUILT. */
export interface CaregiverAuthorization {
  id: string;
  patient_id: string;
  caregiver_id: string;
  scopes: CaregiverScope[];
  status: ConsentStatus;
  requested_days: number;
  activated_at: string | null;
  expires_at: string | null;
  patient_name: string;
}

// ---- F4 verifier/CHW assisted capture (M2/M3). GAP, FRD open question 3: the backend gives a verifier no access to uploads or
// extractions yet. Proposed here and mocked: the verifier enters the Health ID, a one-time code goes to the patient's own phone, the
// present patient reads it out, and a short session opens for this verifier and patient only. While it is active the verifier may
// upload (POST /patients/{id}/documents), list the documents not yet verified (GET /patients/{id}/documents, filtered by the
// server), and check one beside its image (GET /documents/{id}, /images/{n}, /extraction; PUT /documents/{id}/review;
// POST /documents/{id}/confirm, /reject, /manual-entry, /retry-extraction). Never the timeline, verified documents or consent.

/** POST /verifier/sessions { health_id } -> 201 (pending; the code is sent to the patient's phone, never returned);
 * POST /verifier/sessions/{id}/confirm { code } -> active (403 invalid_code for a wrong, expired, used or dead code);
 * POST /verifier/sessions/{id}/end. GAP: the routes, and the C1 purpose name `ASSISTED_CAPTURE`, are proposals for the owner. The
 * session length is REVIEWER-PENDING (the server sets `expires_at`). */
export interface AssistSession {
  id: string;
  purpose: "ASSISTED_CAPTURE"; // GAP: C1 purpose mapping to decide
  status: "pending" | "active" | "expired" | "revoked";
  health_id: string;
  patient_id: string | null; // only once active
  activated_at: string | null;
  expires_at: string | null;
}

// ---- F5 clinical reviewer console (staff role `clinical_reviewer`, the backend's name). Never a patient's record.

export type RuleType = "ddi" | "allergy" | "duplicate" | "drug_disease" | "class_lookback" | "vital_threshold" | "red_flag" | "emergency_message";
export type RuleStatus = "draft" | "approved" | "rejected" | "superseded";

/** One version of a rule in the one registry (FRD M6: every change is a new version; only `approved` runs). Shape GAP.
 * `definition` is the reviewer's own structured content; the UI never holds a clinical rule, it only shows what the server has. */
export interface Rule {
  id: string; // this version
  rule_id: string; // the rule across versions, e.g. SYNTH-DDI-0001
  version: number;
  rule_type: RuleType;
  severity: Severity | null;
  status: RuleStatus;
  definition: Record<string, unknown>;
  explanation: { en: string; bn: string };
  created_by_name: string;
  created_at: string;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  reason: string | null; // why it was rejected
}

/** GET /rules?type= : GAP (the FRD has no list route). POST /rules (a draft, or a new version of `rule_id`): FRD, body GAP.
 * POST /rules/{id}/approve: FRD. POST /rules/{id}/reject { reason }: GAP. Approving a version supersedes the rule's approved one. */
export interface RuleDraftBody {
  rule_id?: string; // a new version of this rule; absent: a new rule
  rule_type: RuleType;
  severity: Severity | null;
  definition: Record<string, unknown>;
  explanation: { en: string; bn: string };
}

/** A closed break-glass session waiting for post-hoc review (FRD M10; only with VITE_FEATURE_EMERGENCY_ACCESS=1).
 * GET /admin/emergency/reviews and POST /admin/emergency/reviews/{id}/review { decision, note }: FRD routes, shapes GAP. The
 * reviewer sees who opened it, why, where, when and which card FIELDS were shown, never the patient or the values. */
export interface EmergencyReview {
  id: string;
  doctor_id: string;
  doctor_name: string;
  reason: string;
  facility: string;
  opened_at: string;
  closed_at: string;
  fields_shown: EmergencyField[];
  status: "review_pending" | "justified" | "unjustified";
  note: string | null;
  reviewed_at: string | null;
  capability_suspended: boolean; // true after "unjustified": the doctor's emergency capability is off
}

// ---- F5 admin console (staff role `admin`). Never clinical content.

/** GET /credentials?status= : GAP (the FRD has no list route). POST /credentials/{id}/approve -> { user_id, status: "verified" }:
 * BUILT. POST /credentials/{id}/reject { reason }: GAP. POST /admin/users/{user_id}/suspend { reason }: GAP (FRD section 2:
 * suspension suspends every active grant at once). */
export interface CredentialReview {
  id: string;
  user_id: string;
  name: string;
  role: "doctor";
  type: "BMDC";
  number: string;
  status: StaffStatus; // a rejected credential is removed, so the doctor can submit again
  user_status: StaffStatus;
}

/** POST /catalog/import (multipart: file): FRD route, response GAP. The drug catalog source and its licence are undecided
 * (FRD question 1): no catalog data ships with the UI or the mock. */
export interface CatalogImport {
  id: string;
  status: "queued";
  file_name: string;
  size_bytes: number;
}

/** GET /audit?action=&result=&role= : FRD route (admin), shape GAP. Metadata only: no name, phone, IP, device, free text or
 * clinical content; people and records appear as short pseudonymous references. `chain` is the server's verification of the
 * whole hash chain (core/audit.py verify_chain), not something the browser recomputes. */
export interface AuditEntry {
  id: string;
  at: string;
  actor_role: string | null;
  actor_ref: string | null;
  action: string;
  purpose: string | null;
  result: "allow" | "deny";
  reason: string | null; // a reason code, or "free_text_hidden"
  patient_ref: string | null;
  consent_ref: string | null;
  prev_hash: string;
  entry_hash: string;
}
export interface AuditPage {
  chain: { status: "intact" | "broken"; checked_at: string; entries_checked: number; first_broken_id: string | null };
  entries: AuditEntry[]; // newest first
}

/** GET /internal/metrics (admin). BUILT (api/internal.py, workers/monitoring.py; owner decision D13). Counts only. */
export interface WorkerMetrics {
  at: string;
  documents: Record<DocStatus, number>;
  worker: {
    due: number; in_flight: number; lease_expired: number; failed: number; failed_permanent: number; failed_budget_exhausted: number;
    failed_retryable: number; waiting_backoff: number; attempts_open_runs: number; ocr_executions_total: number;
    failed_no_retry_last_hour: number; due_over_15_minutes: number;
  };
}
