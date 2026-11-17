import type { ApiRequest, ApiResponse, Method, Transport } from "./client";
import type {
  AccessEntry, AuditEntry, Cited, Consent, ConsentQr, CredentialReview, StaffAccount, DocType, DocumentView, DoctorConsent, EmergencyProfile,
  EmergencyReview, EmergencySession, ExtractedField, ExtractionResponse, FieldRow, Me, NotificationKind, OtpVerifyBody, PatientNotification,
  QrConsentRequest, Reminder, ReminderLogAction, ReviewBody, ReviewedText, Rule, RuleType, SafetyAlert, SafetyCheck, SearchHit, Severity, StaffMe,
  StaffVerifyBody, Summary, ThresholdField, TimelineEvent, TriageState, VitalEntry, VitalEvaluation, VitalReading, VitalThresholds, VitalType, VitalUnit,
  WorkerMetrics,
} from "./types";
import { flags } from "../flags";
import { toAsciiDigits } from "../i18n/i18n";

// In-memory stand-in for /api/v1 with SYNTHETIC data only (invariant 9): no real person, drug or clinic. It answers with the
// backend's shapes and error format (types.ts says which routes are BUILT, FRD or GAP). An unknown route answers 501
// `not_built_in_mock`, never a made-up success. Each mockTransport() call starts from the same fresh synthetic state.

export const MOCK_CODE = "123456"; // the one-time code the mock accepts (no SMS in the mock)
export const MOCK_PHONE = "+8801700000001"; // already registered; any other phone must register with a profile
export const MOCK_PATIENT_ID = "11111111-1111-4111-8111-111111111111";
export const MOCK_DOCTOR_ID = "22222222-2222-4222-8222-222222222222";
const DOCTOR_ID = MOCK_DOCTOR_ID;
export const MOCK_DOCTOR_PHONE = "+8801900000002"; // a verified, emergency-enabled synthetic doctor
export const MOCK_PENDING_DOCTOR_PHONE = "+8801900000003"; // a synthetic doctor whose BMDC credential is still pending
export const MOCK_HEALTH_ID = "SID-4827190356";
const PENDING_DOCTOR_ID = "55555555-5555-4555-8555-555555555555";
export const MOCK_CAREGIVER_ID = "33333333-3333-4333-8333-333333333333"; // another person account, asking to care for the mock patient
const CAREGIVER_ID = MOCK_CAREGIVER_ID;
const OTHER_DOCTOR_ID = "44444444-4444-4444-8444-444444444444";
export const MOCK_VERIFIER_ID = "77777777-7777-4777-8777-777777777777";
export const MOCK_VERIFIER_PHONE = "+8801900000004"; // a verified synthetic verifier (CHW)
export const MOCK_REVIEWER_ID = "88888888-8888-4888-8888-888888888888";
export const MOCK_REVIEWER_PHONE = "+8801900000005"; // a synthetic clinical reviewer
export const MOCK_ADMIN_ID = "99999999-9999-4999-8999-999999999999";
export const MOCK_ADMIN_PHONE = "+8801900000006"; // a synthetic admin
export const MOCK_SUBMITTED_DOCTOR_ID = "66666666-6666-4666-8666-666666666666"; // a doctor whose BMDC number waits for an admin
export const MOCK_PENDING_VERIFIER_ID = "7a7a7a7a-7a7a-47a7-87a7-7a7a7a7a7a7a";
export const MOCK_PENDING_VERIFIER_PHONE = "+8801900000007"; // a verifier who registered and waits for an admin

// Fictional patients the mock patient may act for as a caregiver, one per authorization state (caregiver mode, F4).
export const MOCK_OTHERS = {
  full: { id: "a1111111-1111-4111-8111-111111111111", health_id: "SID-9000000011", name: "সিনথেটিক রোগী ক" }, // active: all three scopes
  timeline: { id: "b2222222-2222-4222-8222-222222222222", health_id: "SID-9000000022", name: "সিনথেটিক রোগী খ" }, // active: view_timeline only
  revoked: { id: "c3333333-3333-4333-8333-333333333333", health_id: "SID-9000000033", name: "সিনথেটিক রোগী গ" }, // revoked
  pending: { id: "d4444444-4444-4444-8444-444444444444", health_id: "SID-9000000044", name: "সিনথেটিক রোগী ঘ" }, // a pending request
} as const;

const CODE_TTL_MS = 5 * 60_000; // the backend's OTP CODE_TTL (identity/otp.py)
const MAX_CODE_ATTEMPTS = 5; // the backend's otp.MAX_ATTEMPTS
// REVIEWER-PENDING: how long a verifier may work after the patient's code. A placeholder, not a decided value.
export const MOCK_ASSIST_MINUTES = 30;
export const ASSIST_PURPOSE = "ASSISTED_CAPTURE"; // GAP: the C1 purpose name is the owner's to decide (types.ts AssistSession)
const CARE_SCOPES = ["upload_documents", "view_documents", "view_timeline"] as const;
type CareScope = (typeof CARE_SCOPES)[number];
const CLOSED_DOCS: DocumentView["status"][] = ["verified", "rejected"];

type Handler = (request: ApiRequest, params: Record<string, string>) => ApiResponse | Promise<ApiResponse>;
const ok = (body: unknown, status = 200): ApiResponse => ({ status, body });
const error = (status: number, code: string, message: string, details: Record<string, unknown> = {}): ApiResponse =>
  ({ status, body: { code, message, details } });

function base64url(value: object): string {
  return btoa(JSON.stringify(value)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}

/** An UNSIGNED token shaped like the backend's JWT (sub, role), so the client reads it the same way. Mock only. */
function mockJwt(sub: string, role: string): string {
  return `${base64url({ alg: "none", typ: "JWT" })}.${base64url({ sub, role, device_id: "mock" })}.mock`;
}

const field = (value: string | null, confidence: number, raw = value, extra: Partial<ExtractedField> = {}): ExtractedField =>
  ({ value: confidence >= 0.85 ? value : null, raw, confidence, source: raw === null ? null : "ocr",
     manual_entry: confidence < 0.85 || value === null, ...extra });
const empty = (): ExtractedField => field(null, 0, null);

function prescriptionFields(): ExtractionResponse["extraction"] {
  const rows: FieldRow[] = [
    { name_as_written: field("SYNTH-DRUG-001 500 mg", 0.93), strength: empty(), form: empty(), dose_instruction: empty(), duration: empty() },
    { name_as_written: field("SYNTH-DRUG-002", 0.62), strength: empty(), form: empty(), dose_instruction: empty(), duration: empty() },
  ];
  return {
    version: 1, engine: "fake-ocr", raw_text: "SYNTHETIC PRESCRIPTION", raw_text_available: true,
    created_at: "2026-11-14T09:30:00Z", printed_name_check: "not_checked",
    fields: {
      prescription_date: field("2026-11-12", 0.97, "12/11/2026"),
      prescriber_name: field("Dr. Synthetic Prescriber", 0.71),
      prescriber_registration: field("SYNTH-REG-0001", 0.9),
      facility_name: field("Synthetic Clinic", 0.88),
      diagnosis_text: empty(),
      medications: rows,
      advice_text: field("rest and fluids", 0.66),
      follow_up_date: field(null, 0.99, "next week", { error: "invalid_date" }),
      allergy_text: empty(),
      printed_patient_name: empty(),
    },
  };
}

function createState() {
  const now = Date.now();
  const iso = (offsetHours: number) => new Date(now + offsetHours * 3600_000).toISOString();
  const me: Me = { id: MOCK_PATIENT_ID, health_id: "SID-4827190356", name: "সিনথেটিক রোগী", language: "bn", cloud_ai_opt_in: false };
  const consents: Consent[] = [
    { id: "c-active", grantee_id: DOCTOR_ID, grantee_role: "doctor", purpose: "TIMELINE", allowed_categories: ["timeline", "documents", "safety"],
      status: "active", activated_at: iso(-2), expires_at: iso(22), created_at: iso(-2), grantee_name: "ডা. সিনথেটিক চিকিৎসক",
      grantee_phone_tail: null, requested_days: null },
    { id: "c-pending", grantee_id: OTHER_DOCTOR_ID, grantee_role: "doctor", purpose: "TIMELINE", allowed_categories: ["timeline"],
      status: "pending", activated_at: null, expires_at: null, created_at: iso(-0.2), grantee_name: "ডা. দ্বিতীয় সিনথেটিক",
      grantee_phone_tail: null, requested_days: null },
    { id: "c-caregiver", grantee_id: CAREGIVER_ID, grantee_role: "caregiver", purpose: "CAREGIVER",
      allowed_categories: ["upload_documents", "view_timeline"], status: "pending", activated_at: null, expires_at: null,
      created_at: iso(-1), grantee_name: "সিনথেটিক পরিচর্যাকারী", grantee_phone_tail: "0042", requested_days: 30 },
    { id: "c-expired", grantee_id: OTHER_DOCTOR_ID, grantee_role: "doctor", purpose: "TIMELINE", allowed_categories: ["timeline"],
      status: "expired", activated_at: iso(-80), expires_at: iso(-56), created_at: iso(-80), grantee_name: "ডা. দ্বিতীয় সিনথেটিক",
      grantee_phone_tail: null, requested_days: null },
  ];
  const history: AccessEntry[] = [
    { at: iso(-1.5), actor_id: DOCTOR_ID, actor_role: "doctor", action: "timeline.read", purpose: "TIMELINE", result: "allow",
      reason: null, consent_id: "c-active", actor_name: "ডা. সিনথেটিক চিকিৎসক" },
    { at: iso(-3), actor_id: OTHER_DOCTOR_ID, actor_role: "doctor", action: "timeline.read", purpose: "TIMELINE", result: "deny",
      reason: "consent_required", consent_id: null, actor_name: "ডা. দ্বিতীয় সিনথেটিক" },
  ];
  const doc = (id: string, status: DocumentView["status"], hoursAgo: number, docType: DocType = "prescription", patient = MOCK_PATIENT_ID): DocumentView =>
    ({ id, patient_id: patient, doc_type: docType, status, uploaded_by: patient, created_at: iso(-hoursAgo),
       images: [{ n: 1, content_type: "image/png", size_bytes: 48213, sha256: "0".repeat(64), quality_warnings: [] }] });
  const documents: DocumentView[] = [
    doc("d-review", "needs_review", 2), doc("d-verified", "verified", 72), doc("d-failed", "extraction_failed", 30, "lab_report"),
    doc("d-reading", "extracting", 0.1),
  ];
  const extractions: Record<string, ExtractionResponse["extraction"]> = { "d-review": prescriptionFields(), "d-verified": prescriptionFields() };
  const ev = (event_id: string, event_type: TimelineEvent["event_type"], date: string, status: TimelineEvent["verification_status"],
              payload: Record<string, string>, extra: Partial<TimelineEvent> = {}): TimelineEvent =>
    ({ event_id, event_type, date, date_precision: "day", verification_status: status, source_document_id: null,
       recorded_at: iso(-48), version: 1, supersedes: null, payload, ...extra });
  const timeline: TimelineEvent[] = [
    ev("e-rx", "prescription", "2026-11-08", "document_verified", { prescriber_name: "Dr. Synthetic Prescriber" }, { source_document_id: "d-verified" }),
    ev("e-med", "medication", "2026-11-08", "document_verified", { name_as_written: "SYNTH-DRUG-003" }, { source_document_id: "d-verified" }),
    // not in any catalog: the M6 check lists it as unrecognised (P3), never passes it silently
    ev("e-med-2", "medication", "2026-11-08", "document_verified", { name_as_written: "SYNTH-DRUG-UNLISTED 250 mg" }, { source_document_id: "d-verified" }),
    ev("e-allergy", "allergy", "2026-10-02", "document_verified", { allergy_text: "SYNTH-ALLERGEN-01" }, { source_document_id: "d-verified" }),
    ev("e-lab-1", "lab_result", "2026-09-15", "document_verified", { test_name: "SYNTH-TEST-A", result: "5.4", unit: "mg/dL" }),
    ev("e-lab-2", "lab_result", "2026-11-01", "document_verified", { test_name: "SYNTH-TEST-A", result: "5.9", unit: "mg/dL" }),
    ev("e-bp-1", "vital_reading", "2026-11-10", "patient_reported", { reading: "150/95 mmHg" }),
    ev("e-bp-2", "vital_reading", "2026-11-10", "patient_reported", { reading: "130/85 mmHg" }, { version: 2, supersedes: "e-bp-1" }),
  ];
  const vitals: VitalReading[] = [
    { event_id: "v-1", vital_type: "bp", value: "150/95", unit: "mmHg", context: "home", measured_at: iso(-120), verification_status: "patient_reported",
      version: 1, supersedes: null, recorded_at: iso(-120) },
    { event_id: "v-2", vital_type: "bp", value: "130/85", unit: "mmHg", context: "home", measured_at: iso(-120), verification_status: "patient_reported",
      version: 2, supersedes: "v-1", recorded_at: iso(-119) },
    { event_id: "v-3", vital_type: "glucose", value: "6.1", unit: "mmol/L", context: "fasting", measured_at: iso(-30), verification_status: "patient_reported",
      version: 1, supersedes: null, recorded_at: iso(-30) },
  ];
  const reminders: Reminder[] = [
    { id: "r-proposed", kind: "medicine", status: "proposed", as_written: "SYNTH-DRUG-003 · 1+0+1 (as written)", times: ["08:00", "20:00"],
      source_event_id: "e-med", log: [] },
    { id: "r-active", kind: "medicine", status: "active", as_written: "SYNTH-DRUG-001 · 0+0+1 (as written)", times: ["21:00"],
      source_event_id: "e-med", log: [{ action: "taken", at: iso(-20) }] },
    { id: "r-follow", kind: "follow_up", status: "paused", as_written: "Follow-up visit (as written)", times: ["10:00"],
      source_event_id: "e-rx", log: [] },
  ];
  const emergency: EmergencyProfile = { enabled: false, fields: [], contacts: [],
    // like the server (B7 decision 2): verified allergies as written; blood group, medications and conditions REVIEWER-PENDING
    available: { blood_group: null, allergies: ["SYNTH-ALLERGEN-01"], active_medications: [], conditions: [] } };

  // every patient's records, by patient id; the mock patient's are the arrays above
  const records: Record<string, { health_id: string; name: string; documents: DocumentView[]; timeline: TimelineEvent[] }> = {
    [MOCK_PATIENT_ID]: { health_id: me.health_id, name: me.name, documents, timeline },
  };
  const histories: Record<string, AccessEntry[]> = { [MOCK_PATIENT_ID]: history };
  const patientOf: Record<string, string> = Object.fromEntries(consents.map((c) => [c.id, MOCK_PATIENT_ID])); // consent id -> patient id
  const codes = new Map<string, { sentAt: number; tries: number; used: boolean }>(); // one-time code state by request id (never the code)
  Object.entries(MOCK_OTHERS).forEach(([key, o], i) => {
    const verified = doc(`d-${key}-verified`, "verified", 96, "prescription", o.id);
    records[o.id] = { health_id: o.health_id, name: o.name, documents: [doc(`d-${key}-review`, "needs_review", 5, "prescription", o.id), verified],
      timeline: [ev(`e-${key}-med`, "medication", "2026-10-20", "document_verified", { name_as_written: `SYNTH-DRUG-10${i}` }, { source_document_id: verified.id })] };
    extractions[`d-${key}-review`] = prescriptionFields();
    histories[o.id] = [];
    const scopes = key === "timeline" ? ["view_timeline"] : [...CARE_SCOPES];
    const status = key === "pending" ? "pending" : key === "revoked" ? "revoked" : "active";
    const c: Consent = { id: `c-care-${key}`, grantee_id: MOCK_PATIENT_ID, grantee_role: "caregiver", purpose: "CAREGIVER", allowed_categories: scopes,
      status, activated_at: status === "pending" ? null : iso(-24), expires_at: status === "pending" ? null : iso(24 * 29),
      created_at: iso(-24), grantee_name: me.name, grantee_phone_tail: "0001", requested_days: 30 };
    consents.push(c);
    patientOf[c.id] = o.id;
    if (status === "pending") codes.set(c.id, { sentAt: now, tries: 0, used: false });
  });

  const review = (id: string, hoursAgo: number, reason: string, fields: EmergencyReview["fields_shown"]): EmergencyReview => ({
    id, doctor_id: DOCTOR_ID, doctor_name: "ডা. সিনথেটিক চিকিৎসক", reason, facility: "Synthetic General Hospital",
    opened_at: iso(hoursAgo - 2), closed_at: iso(hoursAgo), fields_shown: fields, status: "review_pending", note: null, reviewed_at: null,
    capability_suspended: false });

  return { me, consents, history, documents, extractions, timeline, phones: new Set([MOCK_PHONE]), reviews: {} as Record<string, ReviewBody["fields"]>,
           vitals, reminders, emergency, triage: {} as Record<string, number>, records, histories, patientOf, codes,
           sessions: [] as Array<{ id: string; verifier_id: string; patient_id: string; status: "pending" | "active" | "expired" | "revoked";
                                   activated_at: string | null; expires_at: string | null }>,
           staff: {
             [DOCTOR_ID]: { id: DOCTOR_ID, role: "doctor", name: "ডা. সিনথেটিক চিকিৎসক", status: "verified", emergency_enabled: true,
                            credential: { type: "BMDC", number: "SYNTH-BMDC-0001", status: "verified" } },
             [PENDING_DOCTOR_ID]: { id: PENDING_DOCTOR_ID, role: "doctor", name: "ডা. নতুন সিনথেটিক", status: "pending", emergency_enabled: false,
                                    credential: null },
             [MOCK_VERIFIER_ID]: { id: MOCK_VERIFIER_ID, role: "verifier", name: "সিনথেটিক স্বাস্থ্যকর্মী", status: "verified", emergency_enabled: false,
                                   credential: null },
             [MOCK_SUBMITTED_DOCTOR_ID]: { id: MOCK_SUBMITTED_DOCTOR_ID, role: "doctor", name: "ডা. তৃতীয় সিনথেটিক", status: "pending",
                                           emergency_enabled: false, credential: { type: "BMDC", number: "SYNTH-BMDC-0042", status: "pending" } },
             [MOCK_REVIEWER_ID]: { id: MOCK_REVIEWER_ID, role: "clinical_reviewer", name: "সিনথেটিক রিভিউয়ার", status: "verified",
                                   emergency_enabled: false, credential: null },
             [MOCK_ADMIN_ID]: { id: MOCK_ADMIN_ID, role: "admin", name: "সিনথেটিক অ্যাডমিন", status: "verified", emergency_enabled: false, credential: null },
             [MOCK_PENDING_VERIFIER_ID]: { id: MOCK_PENDING_VERIFIER_ID, role: "verifier", name: "সিনথেটিক নতুন স্বাস্থ্যকর্মী", status: "pending",
                                           emergency_enabled: false, credential: null },
           } as Record<string, StaffMe>,
           staffPhones: new Map([[MOCK_DOCTOR_PHONE, DOCTOR_ID], [MOCK_PENDING_DOCTOR_PHONE, PENDING_DOCTOR_ID], [MOCK_VERIFIER_PHONE, MOCK_VERIFIER_ID],
                                 [MOCK_REVIEWER_PHONE, MOCK_REVIEWER_ID], [MOCK_ADMIN_PHONE, MOCK_ADMIN_ID],
                                 [MOCK_PENDING_VERIFIER_PHONE, MOCK_PENDING_VERIFIER_ID]]),
           rules: seedRules(iso),
           rejectedCredentials: [] as CredentialReview[], // the server keeps a rejected credential with its status (B2)
           emergencyReviews: [
             review("er-1", -30, "SYNTH-REASON: unconscious on arrival (synthetic)", ["blood_group", "allergies"]),
             review("er-2", -6, "SYNTH-REASON: unresponsive after a fall (synthetic)", ["allergies", "active_medications"]),
           ],
           auditLog: [] as Array<Omit<AuditEntry, "actor_ref" | "patient_ref" | "consent_ref"> & { actor_id: string | null; patient_id: string | null;
                                   consent_id: string | null; resource: string | null }>,
           alerts: [
             { id: "a-1", rule_id: "SYNTH-DDI-0001", severity: "major", source_document_id: "d-verified", evidence_event_ids: ["e-med", "e-rx"],
               explanation: pendingText("Approved interaction explanation for SYNTH-DRUG-003 goes here.", "SYNTH-DRUG-003-এর অনুমোদিত ব্যাখ্যা এখানে বসবে।"),
               created_at: iso(-47), status: "open", reason: null },
             { id: "a-2", rule_id: "SYNTH-ALG-0001", severity: "moderate", source_document_id: "d-verified", evidence_event_ids: ["e-allergy", "e-med"],
               explanation: pendingText("Approved allergy explanation goes here.", "অ্যালার্জির অনুমোদিত ব্যাখ্যা এখানে বসবে।"),
               created_at: iso(-47), status: "open", reason: null },
           ] as SafetyAlert[],
           qr: {} as Record<string, ConsentQr>, // consent id -> its QR (F6, GAP)
           thresholds: {} as Record<string, Omit<VitalThresholds, "patient_id" | "fields"> & { overrides: Record<string, number | null> }>,
           notifications: [
             note("n-2", "caregiver_request", iso(-1), "সিনথেটিক পরিচর্যাকারী", ["upload_documents", "view_timeline"]),
             note("n-1", "consent_request", iso(-0.2), "ডা. দ্বিতীয় সিনথেটিক", ["timeline"]),
             // M10 is conditional: the seeded break-glass notice exists only where the flag is on (the server writes one per session)
             ...(flags.emergencyAccess ? [note("n-3", "emergency_access", iso(-8), "ডা. সিনথেটিক চিকিৎসক", [], "Synthetic General Hospital")] : []),
           ].sort((a, b) => b.created_at.localeCompare(a.created_at)) };
}

const note = (id: string, kind: NotificationKind, created_at: string, actor_name: string | null, categories: string[],
              facility: string | null = null): PatientNotification => ({ id, kind, created_at, read_at: null, actor_name, categories, facility });

const QR_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"; // no 0/O, 1/I/L: read and typed by hand

/** SYNTHETIC rule versions so the registry screens can be tried. MOCK ONLY and REVIEWER-PENDING: no real drug, interaction,
 * threshold, red flag or message. The clinical reviewer writes the real ones (FRD question 7). */
function seedRules(iso: (offsetHours: number) => string): Rule[] {
  const rule = (ruleId: string, version: number, ruleType: RuleType, severity: Severity | null, status: Rule["status"], hoursAgo: number,
                extra: Record<string, unknown> = {}): Rule => ({
    id: `${ruleId}-v${version}`, rule_id: ruleId, version, rule_type: ruleType, severity, status,
    // the engine types use the strict P3 shape (D5); their names are made up
    definition: ["ddi", "allergy", "duplicate"].includes(ruleType) ? extra : { placeholder: "REVIEWER-PENDING", synthetic: true, ...extra },
    explanation: { en: `[REVIEWER-PENDING] Approved explanation for ${ruleId} goes here.`,
                   bn: `[রিভিউয়ার-অনুমোদন বাকি] ${ruleId}-এর অনুমোদিত ব্যাখ্যা এখানে বসবে।` },
    // B5 four-eyes: the seeds are written by a second synthetic reviewer, so the signed-in reviewer may approve them
    created_by_name: "সিনথেটিক রিভিউয়ার (দ্বিতীয়)", created_at: iso(-hoursAgo),
    reviewed_by_name: status === "draft" ? null : "সিনথেটিক রিভিউয়ার", reviewed_at: status === "draft" ? null : iso(-hoursAgo + 1),
    reason: null });
  return [
    rule("SYNTH-DDI-0001", 1, "ddi", "major", "approved", 200, { schema: 1, ingredients: ["synthgen-alpha", "synthgen-beta"] }),
    rule("SYNTH-DDI-0001", 2, "ddi", "major", "draft", 20, { schema: 1, ingredients: ["synthgen-alpha", "synthgen-beta"] }),
    rule("SYNTH-ALG-0001", 1, "allergy", "moderate", "approved", 190,
         { schema: 1, allergen_terms: ["SYNTH-ALLERGEN-01"], ingredients: ["synthgen-beta"] }),
    rule("SYNTH-VT-0001", 1, "vital_threshold", null, "draft", 10, { vital_type: "bp" }),
    // approved SYNTHETIC threshold rules, so the doctor's thresholds screen has fields; no value and no limit (REVIEWER-PENDING)
    rule("SYNTH-VT-0101", 1, "vital_threshold", null, "approved", 180, { vital_type: "bp", unit: "mmHg" }),
    rule("SYNTH-VT-0102", 1, "vital_threshold", null, "approved", 180, { vital_type: "bp", unit: "mmHg" }),
    rule("SYNTH-VT-0103", 1, "vital_threshold", null, "approved", 180, { vital_type: "glucose", unit: "mmol/L" }),
    rule("SYNTH-RF-0001", 1, "red_flag", null, "draft", 9, { phrase: "SYNTH-RED-FLAG" }),
    rule("SYNTH-EM-0001", 1, "emergency_message", null, "draft", 8),
  ];
}

/** A deterministic stand-in for SHA-256 (64 hex characters). MOCK ONLY: the real chain is core/audit.py entry_hash. */
function mockHash(text: string): string {
  let out = "";
  for (let seed = 0; seed < 8; seed++) {
    let h = 0x811c9dc5 ^ seed;
    for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193);
    out += (h >>> 0).toString(16).padStart(8, "0");
  }
  return out;
}

// ---- F2 mock rules. SYNTHETIC and MOCK-ONLY: they exist so every screen state can be tried. They are NOT clinical rules and the
// UI never contains them; the real ones come from the reviewer-approved M6 registry (FRD M13, M7). All wording is a placeholder.
const pending = (en: string, bn: string): ReviewedText =>
  ({ status: "REVIEWER-PENDING", en: `[REVIEWER-PENDING] ${en}`, bn: `[রিভিউয়ার-অনুমোদন বাকি] ${bn}` });
export const MOCK_RED_FLAG = "SYNTH-RED-FLAG"; // the mock routes a message containing this to the emergency card

function mockEvaluate(entry: VitalEntry): { confirm: boolean; evaluation: VitalEvaluation } {
  if (entry.vital_type === "bp") {
    const [sys, dia] = entry.value.split("/").map(Number);
    const confirm = sys > 300 || dia > 200 || sys <= dia; // mock-only plausibility check
    // 180/120 is the FRD's own example of a critical reading (M13); every other reading has no approved rule yet
    const critical = sys >= 180 || dia >= 120;
    return { confirm, evaluation: critical
      ? { level: "critical", rule_id: "SYNTH-RULE-BP-CRITICAL", message: pending("Approved escalation message goes here.", "অনুমোদিত জরুরি বার্তা এখানে বসবে।") }
      : { level: "not_evaluated", rule_id: null, message: null } };
  }
  const value = Number(entry.value);
  const confirm = entry.unit === "mmol/L" ? value > 40 : value > 700; // mock-only: a value that looks like the wrong unit
  return { confirm, evaluation: { level: "not_evaluated", rule_id: null, message: null } };
}

/** One step of the mock triage: the red-flag check runs on the first message and on every answer, before anything else. */
function triageStep(id: string, text: string, answered: number): TriageState {
  if (text.toUpperCase().includes(MOCK_RED_FLAG)) return { session_id: id, state: "emergency", question: null, suggestion: null };
  if (answered >= 2) {
    return { session_id: id, state: "suggestion", question: null, suggestion: {
      department: pending("Department from the approved guide table", "অনুমোদিত নির্দেশিকা থেকে বিভাগ"),
      reason: pending("Short reason from the approved guide table", "অনুমোদিত নির্দেশিকা থেকে সংক্ষিপ্ত কারণ") } };
  }
  return { session_id: id, state: "question", suggestion: null, question: { id: `q${answered + 1}`,
    text: pending(`Follow-up question ${answered + 1} from the approved guide table`, `অনুমোদিত নির্দেশিকা থেকে প্রশ্ন ${answered + 1}`),
    options: [{ id: "yes", text: { status: "approved", en: "Yes", bn: "হ্যাঁ" } }, { id: "no", text: { status: "approved", en: "No", bn: "না" } }] } };
}

function pendingText(en: string, bn: string): ReviewedText {
  return { status: "REVIEWER-PENDING", en: `[REVIEWER-PENDING] ${en}`, bn: `[রিভিউয়ার-অনুমোদন বাকি] ${bn}` };
}

// The payload fields each summary section states, in the server's order (summary/build.py FIELDS).
const SUMMARY_FIELDS: Partial<Record<TimelineEvent["event_type"], string[]>> = {
  medication: ["name_as_written", "strength", "form", "dose_instruction", "duration"], allergy: ["allergy_text"],
  lab_result: ["test_name", "result", "unit", "reference_range"], visit: ["facility_name", "admission_date", "discharge_date"],
  follow_up: ["follow_up_date"],
};
const currentOf = (events: TimelineEvent[]) => events.filter((e) => !events.some((x) => x.supersedes === e.event_id));

/** One cited line, as the server: the event's values as written, then its date, each value a fact (P3 correction 2). */
function citedLine(e: TimelineEvent, fields = SUMMARY_FIELDS[e.event_type] ?? Object.keys(e.payload).sort()): Cited {
  const facts = fields.filter((f) => typeof e.payload[f] === "string" && e.payload[f].trim())
    .map((f) => ({ event_id: e.event_id, field: f, value: e.payload[f].trim() }));
  facts.push({ event_id: e.event_id, field: "date", value: e.date });
  return { text: facts.map((f) => f.value).join(" · "), citations: [e.event_id], facts };
}

/** The template summary, as the server's (P3): current verified events only, newest first; "medications recorded", never
 * "active" (D3); diagnoses not recorded (D2); one lab line per result grouped by test name in date order; follow-ups from today. */
function templateSummary(events: TimelineEvent[]): Summary {
  const current = currentOf(events);
  const newest = (list: TimelineEvent[]) => [...list].sort((a, b) => b.date.localeCompare(a.date));
  const verified = newest(current.filter((e) => e.verification_status === "document_verified"));
  const of = (type: TimelineEvent["event_type"]) => verified.filter((e) => e.event_type === type);
  const today = new Date().toISOString().slice(0, 10);
  const labs = [...of("lab_result")].sort((a, b) => (a.payload.test_name ?? "").toLowerCase().localeCompare((b.payload.test_name ?? "").toLowerCase())
    || a.date.localeCompare(b.date));
  const section = (id: Summary["sections"][number]["id"], list: TimelineEvent[]) =>
    ({ id, note: null, sentences: list.map((e) => citedLine(e)), truncated: 0 });
  return {
    mode: "template", generated_at: new Date().toISOString(), model_id: null, fallback_reason: null,
    sections: [
      section("medications_recorded", of("medication")),
      section("allergies", of("allergy")),
      { id: "diagnoses", note: "not_recorded", sentences: [], truncated: 0 },
      section("labs", labs),
      section("visits", of("visit")),
      section("follow_ups", of("follow_up").filter((e) => e.date >= today)),
    ],
    patient_reported: newest(current.filter((e) => e.verification_status === "patient_reported")).map((e) => citedLine(e)),
  };
}

/** Strict schema-1 shapes of the rule types the M6 engine runs (P3, D5), as the server's safety/definitions.py. */
function engineShapeOk(type: RuleType, severity: Severity | null | undefined, def: Record<string, unknown>): boolean {
  const keys: Partial<Record<RuleType, string[]>> = { ddi: ["ingredients"], allergy: ["allergen_terms", "ingredients"], duplicate: ["ingredients"] };
  const want = keys[type];
  if (!want) return true;
  const norm = (v: unknown) => (typeof v === "string" ? v.normalize("NFC").toLowerCase().split(/\s+/).filter(Boolean).join(" ") : "");
  const names = (v: unknown) => Array.isArray(v) && v.length > 0 && v.every((x) => norm(x)) && new Set(v.map(norm)).size === v.length;
  return severity != null && def.schema === 1 && Object.keys(def).sort().join() === ["schema", ...want].sort().join()
    && want.every((k) => names(def[k])) && (type !== "ddi" || (def.ingredients as unknown[]).length === 2);
}

function syntheticPage(): Blob {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="840" viewBox="0 0 600 840"><rect width="600" height="840" fill="#f4f1e8"/>
<text x="40" y="70" font-family="sans-serif" font-size="26" fill="#1f2937">SYNTHETIC PRESCRIPTION</text>
<text x="40" y="130" font-family="sans-serif" font-size="20" fill="#374151">Date: 12/11/2026</text>
<text x="40" y="170" font-family="sans-serif" font-size="20" fill="#374151">Dr: Synthetic Prescriber</text>
<text x="40" y="240" font-family="sans-serif" font-size="22" fill="#111827">Rx:</text>
<text x="70" y="280" font-family="sans-serif" font-size="20" fill="#111827">SYNTH-DRUG-001 500 mg</text>
<text x="70" y="320" font-family="sans-serif" font-size="20" fill="#6b7280">SYNTH-DRUG-002</text>
<text x="40" y="400" font-family="sans-serif" font-size="20" fill="#9ca3af">Advice: rest and fluids</text></svg>`;
  return new Blob([svg], { type: "image/svg+xml" });
}

export function mockTransport(): Transport {
  const s = createState();
  const who = (r: ApiRequest): { sub: string; role: string } | null => {
    try {
      return JSON.parse(atob((r.headers.Authorization ?? "").replace(/^Bearer /, "").split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    } catch {
      return null;
    }
  };
  // shortcut: only the mock patient has app data of their own (vitals, consents, reminders...); any other patient account is a
  // caregiver only here, and the own-data routes refuse it. Upgrade if a test needs a second full patient.
  const authed = (r: ApiRequest) => who(r)?.role === "patient" && who(r)!.sub === MOCK_PATIENT_ID;
  const staffOf = (r: ApiRequest, role: StaffMe["role"]) => (who(r)?.role === role ? s.staff[who(r)!.sub] ?? null : null);
  const doctorOf = (r: ApiRequest) => staffOf(r, "doctor");
  const live = (iso: string | null) => iso !== null && Date.parse(iso) > Date.now();
  /** C2 for the mock: append to that patient's access history. Never a code or any clinical content. */
  /** C2's one append-only, hash-chained log (every entry links to the one before it). */
  const appendAudit = (e: { at?: string; actor_id: string | null; actor_role: string | null; action: string; patient_id?: string | null;
                            consent_id?: string | null; purpose?: string | null; result: "allow" | "deny"; reason?: string | null; resource?: string | null }) => {
    const prev = s.auditLog.at(-1)?.entry_hash ?? "0".repeat(64);
    const fields = { id: `al-${s.auditLog.length + 1}`, at: e.at ?? new Date().toISOString(), actor_id: e.actor_id, actor_role: e.actor_role,
      action: e.action, patient_id: e.patient_id ?? null, consent_id: e.consent_id ?? null, purpose: e.purpose ?? null, result: e.result,
      reason: e.reason ?? null, resource: e.resource ?? null };
    s.auditLog.push({ ...fields, prev_hash: prev, entry_hash: mockHash(prev + JSON.stringify(fields)) });
  };
  [...s.history].reverse().forEach((h) => appendAudit({ ...h, patient_id: MOCK_PATIENT_ID })); // the seeded history, oldest first
  const audit = (patientId: string, entry: Omit<AccessEntry, "at">) => {
    const at = new Date().toISOString();
    (s.histories[patientId] ??= []).unshift({ at, ...entry });
    appendAudit({ ...entry, at, patient_id: patientId });
  };
  const record = (doctor: StaffMe, action: string, result: "allow" | "deny", reason: string | null, consentId: string | null, patientId = MOCK_PATIENT_ID) =>
    audit(patientId, { actor_id: doctor.id, actor_role: "doctor", action, purpose: "TIMELINE", result, reason, consent_id: consentId, actor_name: doctor.name });
  const roleDenied = () => error(403, "role_not_allowed", "You are not allowed to do this.");
  const invalidCode = () => error(403, "invalid_code", "The code is wrong or has expired.");
  const patientByHealthId = (hid: unknown) =>
    Object.keys(s.records).find((id) => s.records[id].health_id === String(hid ?? "").trim().toUpperCase()) ?? null;
  /** A one-time code "sent to the patient's own phone" (the mock has no SMS; the code is always MOCK_CODE). Single use, expires
   * after CODE_TTL_MS, dead after MAX_CODE_ATTEMPTS wrong tries. */
  const issueCode = (ref: string) => s.codes.set(ref, { sentAt: Date.now(), tries: 0, used: false });
  const useCode = (ref: string, code: unknown): boolean => {
    const c = s.codes.get(ref);
    if (!c || c.used || Date.now() - c.sentAt > CODE_TTL_MS || c.tries >= MAX_CODE_ATTEMPTS) return false;
    if (code !== MOCK_CODE) {
      c.tries += 1;
      return false;
    }
    c.used = true;
    return true;
  };
  /** C1 for a caregiver: an active, unexpired CAREGIVER authorization of this person for this patient holding the scope. Audited. */
  const careFor = (sub: string, patientId: string, scope: CareScope, action: string): ApiResponse | null => {
    const c = s.consents.find((x) => x.purpose === "CAREGIVER" && x.grantee_id === sub && s.patientOf[x.id] === patientId
      && x.status === "active" && live(x.expires_at));
    const reason = !c ? "consent_required" : !c.allowed_categories.includes(scope) ? "category_not_allowed" : null;
    audit(patientId, { actor_id: sub, actor_role: "caregiver", action, purpose: "CAREGIVER", result: reason ? "deny" : "allow", reason,
                       consent_id: c?.id ?? null, actor_name: c?.grantee_name ?? null });
    return reason ? error(403, reason, "The patient has not allowed this access.") : null;
  };
  /** C1 for a verifier: an active assisted session (opened with the patient's own code) for this patient. A verifier never reaches
   * a verified or rejected document's content: that is the record, not work to check. Audited. */
  const sessionFor = (r: ApiRequest, patientId: string, action: string, doc?: DocumentView): ApiResponse | null => {
    const v = staffOf(r, "verifier");
    if (!v || v.status !== "verified") return error(403, "user_not_verified", "You are not allowed to do this.");
    const x = s.sessions.find((y) => y.verifier_id === v.id && y.patient_id === patientId && y.status === "active" && live(y.expires_at));
    const reason = !x ? "consent_required" : doc && CLOSED_DOCS.includes(doc.status) ? "document_closed" : null;
    audit(patientId, { actor_id: v.id, actor_role: "verifier", action, purpose: ASSIST_PURPOSE, result: reason ? "deny" : "allow", reason,
                       consent_id: x?.id ?? null, actor_name: v.name });
    if (reason === "document_closed") return error(404, "not_found", "No document with this id.");
    return reason ? error(403, reason, "The patient has not allowed this access.") : null;
  };
  /** RBAC -> C1 -> C2 for one patient's data: the patient themself passes; otherwise only the roles this route names, each through
   * its own consent check, which writes the audit entry. Everyone else is refused. */
  type Gate = { doctor?: "timeline" | "documents"; care?: CareScope; verifier?: boolean };
  const gate = (r: ApiRequest, patientId: string, g: Gate, action: string, doc?: DocumentView): ApiResponse | null => {
    const w = who(r);
    if (!w) return unauthenticated;
    if (w.role === "patient" && w.sub === patientId) return null;
    if (w.role === "doctor" && g.doctor) return consentFor(r, patientId, g.doctor, action);
    if (w.role === "verifier" && g.verifier) return sessionFor(r, patientId, action, doc);
    if (w.role === "patient" && g.care) return careFor(w.sub, patientId, g.care, action);
    return roleDenied();
  };
  const VIEW: Gate = { doctor: "documents", care: "view_documents", verifier: true };
  const WORK: Gate = { verifier: true }; // checking a document: the patient or a verifier in session, never a caregiver or doctor
  const allDocs = () => Object.values(s.records).flatMap((x) => x.documents);
  /** The document, then the gate for its patient. `closedToo` lets a verifier read the status line of a document they just closed. */
  const withDoc = (r: ApiRequest, id: string, g: Gate, action: string, then: (d: DocumentView) => ApiResponse, closedToo = false): ApiResponse => {
    if (!who(r)) return unauthenticated;
    const d = allDocs().find((x) => x.id === id);
    if (!d) return notFound;
    return gate(r, d.patient_id, g, action, closedToo ? undefined : d) ?? then(d);
  };
  const careView = (c: Consent) => ({ id: c.id, patient_id: s.patientOf[c.id], caregiver_id: c.grantee_id, scopes: c.allowed_categories,
    status: c.status, requested_days: c.requested_days ?? 30, activated_at: c.activated_at, expires_at: c.expires_at,
    patient_name: s.records[s.patientOf[c.id]]?.name ?? null });
  const sessionView = (x: (typeof s.sessions)[number]) => ({ id: x.id, purpose: ASSIST_PURPOSE, status: x.status,
    health_id: s.records[x.patient_id].health_id, patient_id: x.status === "active" ? x.patient_id : null,
    activated_at: x.activated_at, expires_at: x.expires_at });
  /** Approve a pending caregiver request; it replaces the pair's active authorization (DECISIONS.md, "Caregiver access"). */
  const approveCare = (c: Consent) => {
    const pid = s.patientOf[c.id];
    s.consents.filter((x) => x !== c && x.purpose === "CAREGIVER" && x.grantee_id === c.grantee_id && s.patientOf[x.id] === pid && x.status === "active")
      .forEach((x) => { x.status = "revoked"; });
    c.status = "active";
    c.activated_at = new Date().toISOString();
    c.expires_at = new Date(Date.now() + (c.requested_days ?? 30) * 86400_000).toISOString();
    audit(pid, { actor_id: c.grantee_id, actor_role: "caregiver", action: "caregiver.granted", purpose: "CAREGIVER", result: "allow", reason: null,
                 consent_id: c.id, actor_name: c.grantee_name });
    notify("caregiver_granted", c.grantee_name, c.allowed_categories, null, pid);
  };
  const ownConsent = (id: string) => s.consents.find((x) => x.id === id && s.patientOf[x.id] === MOCK_PATIENT_ID);
  /** Upload for `patientId` (M2); the mock-only "blur" file name rule lets the retake flow be tried. */
  const upload = (r: ApiRequest, patientId: string): ApiResponse => {
    const form = r.body instanceof FormData ? r.body : new FormData();
    const images = form.getAll("images").filter((f): f is File => f instanceof File);
    if (images.length < 1 || images.length > 10) return error(422, "invalid_document", "Send 1 to 10 images.");
    const poor = images.map((f, i) => ({ page: i + 1, f })).filter(({ f }) => /blur/i.test(f.name));
    if (poor.length && form.get("upload_anyway") !== "true") {
      return error(422, "image_quality_warning", "Some pages look poor. Retake them, or upload anyway.", {
        pages: poor.map(({ page }) => ({ page, reasons: ["image_blurry"],
          // the owner-approved text from capture/guidance.py, copied as-is
          guidance: [{ code: "image_blurry", bn: "ছবিটি ঝাপসা হয়েছে। ক্যামেরা স্থির রেখে আবার পরিষ্কার ছবি তুলুন।" }] })) });
    }
    const created: DocumentView = { id: `d-${crypto.randomUUID().slice(0, 8)}`, patient_id: patientId,
      doc_type: (form.get("doc_type") as DocType) ?? "prescription", status: "uploaded", uploaded_by: who(r)!.sub,
      created_at: new Date().toISOString(),
      images: images.map((f, i) => ({ n: i + 1, content_type: f.type || "image/png", size_bytes: f.size, sha256: "0".repeat(64),
        quality_warnings: poor.some((x) => x.page === i + 1) ? ["image_blurry"] : [] })) };
    s.records[patientId].documents.unshift(created);
    return ok(created, 201);
  };
  /** C1 for the mock: an active, unexpired TIMELINE consent of this doctor for this patient covering the category; every
   * allow and deny is written to the patient's access history (C2). */
  const consentFor = (r: ApiRequest, patientId: string, category: "timeline" | "documents" | "safety", action: string): ApiResponse | null => {
    const doctor = doctorOf(r);
    if (!doctor) return error(403, "role_not_allowed", "You are not allowed to do this.");
    const c = s.consents.find((x) => x.grantee_id === doctor.id && s.patientOf[x.id] === patientId && x.status === "active"
      && x.expires_at !== null && Date.parse(x.expires_at) > Date.now());
    const reason = !c ? "consent_required" : !c.allowed_categories.includes(category) ? "category_not_allowed" : null;
    record(doctor, action, reason ? "deny" : "allow", reason, c?.id ?? null, patientId);
    return reason ? error(403, reason, reason === "consent_required" ? "No active consent." : "This consent does not cover that.") : null;
  };
  /** Whether the consent consentFor judged ALSO covers `category`; no audit entry (the read itself was audited). */
  const covers = (r: ApiRequest, patientId: string, category: "timeline" | "documents" | "safety") => {
    const doctor = doctorOf(r);
    const c = doctor && s.consents.find((x) => x.grantee_id === doctor.id && s.patientOf[x.id] === patientId && x.status === "active"
      && x.expires_at !== null && Date.parse(x.expires_at) > Date.now());
    return !!c && c.allowed_categories.includes(category);
  };
  const doctorView = (c: Consent): DoctorConsent => ({ id: c.id, purpose: "TIMELINE", allowed_categories: c.allowed_categories as DoctorConsent["allowed_categories"],
    status: c.status, activated_at: c.activated_at, expires_at: c.expires_at, created_at: c.created_at, patient_id: s.patientOf[c.id],
    health_id: s.me.health_id });
  const unauthenticated = error(401, "unauthenticated", "Sign in first.");
  const notFound = error(404, "not_found", "No document with this id.");
  /** C3 in-app inbox: only the mock patient has an app here (see `authed`). */
  const notify = (kind: NotificationKind, actor: string | null, categories: string[], facility: string | null = null, patientId = MOCK_PATIENT_ID) => {
    if (patientId === MOCK_PATIENT_ID) s.notifications.unshift(note(`n-${crypto.randomUUID().slice(0, 8)}`, kind, new Date().toISOString(), actor, categories, facility));
  };
  const activate = (c: Consent) => {
    c.status = "active";
    c.activated_at = new Date().toISOString();
    c.expires_at = new Date(Date.now() + 24 * 3600_000).toISOString(); // the backend reads TIMELINE_CONSENT_HOURS
    notify("consent_granted", c.grantee_name, c.allowed_categories);
  };
  /** The signed-in patient's pending-or-answered QR request by token or short code; never another patient's. */
  const qrConsent = (ref: string) => {
    const want = toAsciiDigits(ref).trim();
    const id = Object.keys(s.qr).find((k) => s.qr[k].token === want || s.qr[k].short_code === want.toUpperCase());
    return id && s.patientOf[id] === MOCK_PATIENT_ID ? s.consents.find((c) => c.id === id) : undefined;
  };
  const qrView = (c: Consent): QrConsentRequest => ({ consent_id: c.id, doctor_name: c.grantee_name ?? "", status:
    c.status === "pending" && !live(s.qr[c.id].expires_at) ? "expired" : c.status as QrConsentRequest["status"],
    categories: c.allowed_categories as QrConsentRequest["categories"], expires_at: s.qr[c.id].expires_at, access_hours: 24 });
  const qrNotFound = () => error(404, "not_found", "This request is not open.");
  /** Like the server (safety/thresholds.py): one field per approved vital_threshold rule, keyed by rule_id; default always null. */
  const thresholdFields = (): Array<Omit<ThresholdField, "override_value">> => s.rules
    .filter((x) => x.rule_type === "vital_threshold" && x.status === "approved")
    .sort((a, b) => a.rule_id.localeCompare(b.rule_id))
    .map((x) => ({ key: x.rule_id, vital_type: x.definition.vital_type as VitalType, unit: x.definition.unit as VitalUnit,
                   label: { ...x.explanation, status: "approved" }, default_value: null }));
  const thresholdsOf = (pid: string): VitalThresholds => {
    const t = (s.thresholds[pid] ??= { version: 0, updated_at: null, updated_by_name: null, overrides: {} }); // no change yet: version 0
    return { patient_id: pid, version: t.version, updated_at: t.updated_at, updated_by_name: t.updated_by_name,
             fields: thresholdFields().map((f) => ({ ...f, override_value: t.overrides[f.key] ?? null })) };
  };

  // ---- F5 console: a verified clinical reviewer or admin, each only on their own routes (RBAC); neither reaches patient data,
  // because every patient route above names only patient, doctor, verifier or caregiver.
  const consoleUser = (r: ApiRequest, role: "clinical_reviewer" | "admin"): StaffMe | ApiResponse => {
    const w = who(r);
    if (!w) return unauthenticated;
    const u = w.role === role ? s.staff[w.sub] : undefined;
    if (!u) return roleDenied();
    return u.status === "verified" ? u : error(403, "user_not_verified", "You are not allowed to do this.");
  };
  const isUser = (x: StaffMe | ApiResponse): x is StaffMe => "role" in x;
  const staffAudit = (u: StaffMe, action: string, resource: string, reason: string | null = null) =>
    appendAudit({ actor_id: u.id, actor_role: u.role, action, result: "allow", reason, resource });
  const reasonOf = (r: ApiRequest) => String((r.body as { reason?: unknown } | undefined)?.reason ?? "").trim();
  const RULE_TYPES: RuleType[] = ["ddi", "allergy", "duplicate", "drug_disease", "class_lookback", "vital_threshold", "red_flag", "emergency_message"];
  const SEVERITIES: Severity[] = ["contraindicated", "major", "moderate", "minor"];
  const credentialView = (u: StaffMe): CredentialReview => ({ id: `cred-${u.id.slice(0, 8)}`, user_id: u.id, name: u.name, role: "doctor", type: "BMDC",
    number: u.credential!.number, status: u.credential!.status, user_status: u.status });
  const staffView = (x: StaffMe): StaffAccount => ({ id: x.id, role: x.role as StaffAccount["role"], name: x.name, status: x.status,
    phone_tail: [...s.staffPhones].find(([, id]) => id === x.id)?.[0].slice(-4) ?? null });
  const credentialOwner = (id: string) => Object.values(s.staff).find((u) => u.role === "doctor" && u.credential && `cred-${u.id.slice(0, 8)}` === id);
  /** The server's rule (swasthyoid/pii.py normalize_phone): a Bangladesh mobile, returned as +8801XXXXXXXXX, else null. */
  const bdMobile = (raw: unknown) => {
    let p = String(raw ?? "").replace(/[\s-]/g, "");
    if (p.startsWith("01")) p = "+88" + p;
    else if (p.startsWith("8801")) p = "+" + p;
    return /^\+8801[3-9]\d{8}$/.test(p) ? p : null;
  };
  const short = (id: string | null) => (id ? id.replace(/^[a-z]+-/, "").slice(0, 8) : null); // a pseudonymous reference, never a name

  const routes: Array<[Method, string, Handler]> = [
    ["GET", "/health", () => ok({ status: "ok" })],
    ["POST", "/auth/otp/request", (r) => {
      return bdMobile((r.body as { phone?: unknown } | undefined)?.phone) ? ok(null, 204) : error(422, "invalid_phone", "Enter a phone number.");
    }],
    ["POST", "/auth/otp/verify", (r) => {
      const body = r.body as Partial<OtpVerifyBody & StaffVerifyBody> | undefined;
      if (body?.code !== MOCK_CODE) return error(401, "invalid_code", "The code is wrong or has expired.");
      const phone = bdMobile(body.phone) ?? "";
      if (body.account === "staff") {
        let id = s.staffPhones.get(phone);
        if (!id) {
          if (!body.staff?.name) return error(409, "registration_required", "Request a new code and send your profile with it.");
          if (body.staff.role !== "doctor" && body.staff.role !== "verifier") return error(422, "invalid_role", "This role cannot register here.");
          id = crypto.randomUUID();
          s.staffPhones.set(phone, id);
          s.staff[id] = { id, role: body.staff.role, name: body.staff.name, status: "pending", emergency_enabled: false, credential: null };
        }
        if (s.staff[id].status === "suspended") return error(403, "user_suspended", "This account is suspended.");
        return ok({ access_token: mockJwt(id, s.staff[id].role), refresh_token: "synthetic-refresh-token" });
      }
      if (!s.phones.has(phone)) {
        if (!body.profile) return error(409, "registration_required", "Request a new code and send your profile with it.");
        s.phones.add(phone); // shortcut: every mock registration signs in to the one synthetic patient
      }
      return ok({ access_token: mockJwt(MOCK_PATIENT_ID, "patient"), refresh_token: "synthetic-refresh-token" });
    }],
    ["GET", "/me", (r) => {
      const w = who(r);
      const staff = w && w.role !== "patient" && s.staff[w.sub]?.role === w.role ? s.staff[w.sub] : null;
      return authed(r) ? ok(s.me) : staff ? ok(staff) : unauthenticated;
    }],
    ["POST", "/credentials", (r) => {
      const doctor = doctorOf(r);
      if (!doctor) return error(403, "role_not_allowed", "You are not allowed to do this.");
      const number = String((r.body as { number?: unknown }).number ?? "").trim();
      if (!number) return error(422, "invalid_credential", "Enter the registration number.");
      if (Object.values(s.staff).some((d) => d.credential?.number === number)) return error(409, "credential_exists", "This credential number is already registered.");
      doctor.credential = { type: "BMDC", number, status: "pending" };
      return ok({ id: `cred-${doctor.id.slice(0, 8)}`, status: "pending" }, 201);
    }],
    ["POST", "/consents/requests", (r) => {
      const doctor = doctorOf(r);
      if (!doctor) return error(403, "role_not_allowed", "You are not allowed to do this.");
      if (doctor.status !== "verified") return error(403, "user_not_verified", "You are not allowed to do this.");
      const body = r.body as { health_id?: string; categories?: string[]; method?: string };
      if (body.health_id !== s.me.health_id) return error(404, "patient_not_found", "No patient has this Health ID.");
      const categories = (body.categories ?? []).filter((c) => ["timeline", "documents", "safety"].includes(c));
      if (!categories.length) return error(422, "invalid_categories", "Choose at least one category.");
      if (body.method !== undefined && body.method !== "otp" && body.method !== "qr") return error(422, "invalid_method", "Use otp or qr.");
      const c: Consent = { id: `c-${crypto.randomUUID().slice(0, 8)}`, grantee_id: doctor.id, grantee_role: "doctor", purpose: "TIMELINE",
        allowed_categories: categories, status: "pending", activated_at: null, expires_at: null, created_at: new Date().toISOString(),
        grantee_name: doctor.name, grantee_phone_tail: null, requested_days: null, method: body.method === "qr" ? "qr" : "otp" };
      s.consents.unshift(c);
      s.patientOf[c.id] = s.me.id;
      notify("consent_request", doctor.name, categories);
      if (body.method !== "qr") return ok(doctorView(c), 201);
      // GAP: the server signs the token; the mock's is random. No SMS code is sent for a QR request.
      const pick = () => QR_ALPHABET[crypto.getRandomValues(new Uint32Array(1))[0] % QR_ALPHABET.length];
      s.qr[c.id] = { token: `qr.${crypto.randomUUID()}`, short_code: Array.from({ length: 8 }, pick).join(""),
                     expires_at: new Date(Date.now() + CODE_TTL_MS).toISOString() };
      return ok({ ...doctorView(c), qr: s.qr[c.id] }, 201);
    }],
    ["GET", "/consents/requests/{id}", (r, p) => { // GAP: the doctor's screen checks a QR request until the patient answers
      const doctor = doctorOf(r);
      if (!doctor) return who(r) ? roleDenied() : unauthenticated;
      const c = s.consents.find((x) => x.id === p.id && x.grantee_id === doctor.id && x.purpose === "TIMELINE");
      return c ? ok(doctorView(c)) : error(404, "not_found", "No consent request with this id.");
    }],
    ["POST", "/consents/requests/{id}/confirm", (r, p) => {
      const doctor = doctorOf(r);
      if (!doctor) return error(403, "role_not_allowed", "You are not allowed to do this.");
      const c = s.consents.find((x) => x.id === p.id && x.grantee_id === doctor.id && x.status === "pending");
      if (!c) return error(404, "not_found", "No pending consent request with this id.");
      // a QR request has no SMS code to read out: only the patient's own app can approve it
      if (s.qr[c.id] || (r.body as { code?: string }).code !== MOCK_CODE) return error(403, "invalid_code", "The code is wrong or has expired.");
      activate(c);
      return ok(doctorView(c));
    }],
    // GAP (F6): the patient's side of a QR request, only for the patient the doctor named; every other case is the same 404
    ["GET", "/consents/qr/{ref}", (r, p) => {
      if (!authed(r)) return who(r) ? roleDenied() : unauthenticated;
      const c = qrConsent(p.ref);
      return c ? ok(qrView(c)) : qrNotFound();
    }],
    ...(["approve", "decline"] as const).map((verb): [Method, string, Handler] => ["POST", `/consents/qr/{ref}/${verb}`, (r, p) => {
      if (!authed(r)) return who(r) ? roleDenied() : unauthenticated;
      const c = qrConsent(p.ref);
      if (!c || c.status !== "pending" || !live(s.qr[c.id].expires_at)) return qrNotFound();
      if (verb === "approve") activate(c);
      else c.status = "declined";
      audit(MOCK_PATIENT_ID, { actor_id: MOCK_PATIENT_ID, actor_role: "patient", action: `consent.qr.${verb}`, purpose: "TIMELINE",
                               result: "allow", reason: null, consent_id: c.id, actor_name: s.me.name });
      return ok(qrView(c));
    }]),
    ["GET", "/notifications", (r) => (authed(r) ? ok(s.notifications) : who(r) ? roleDenied() : unauthenticated)],
    ["POST", "/notifications/{id}/read", (r, p) => {
      if (!authed(r)) return who(r) ? roleDenied() : unauthenticated;
      const n = s.notifications.find((x) => x.id === p.id);
      if (!n) return error(404, "not_found", "No notification with this id.");
      n.read_at ??= new Date().toISOString();
      return ok(n);
    }],
    // GAP (F6, M13): a treating doctor's per-patient threshold overrides, under a consent covering `safety`
    ["GET", "/patients/{id}/vital-thresholds", (r, p) => consentFor(r, p.id, "safety", "vital_thresholds.read") ?? ok(thresholdsOf(p.id))],
    ["PUT", "/patients/{id}/vital-thresholds", (r, p) => {
      const denied = consentFor(r, p.id, "safety", "vital_thresholds.update");
      if (denied) return denied;
      const body = (r.body ?? {}) as { version?: unknown; overrides?: unknown };
      const current = thresholdsOf(p.id);
      if (body.version !== current.version) return error(409, "version_conflict", "Someone changed these thresholds. Reload them.");
      const overrides = body.overrides && typeof body.overrides === "object" && !Array.isArray(body.overrides) ? body.overrides as Record<string, unknown> : null;
      // shortcut: the mock checks only the type; the allowed range is the approved rule's (REVIEWER-PENDING), checked by the server
      if (!overrides || Object.entries(overrides).some(([k, v]) => !current.fields.some((f) => f.key === k)
          || (v !== null && (typeof v !== "number" || !Number.isFinite(v) || v <= 0)))) {
        return error(422, "invalid_threshold", "Check the fields and values.");
      }
      const t = s.thresholds[p.id];
      Object.assign(t.overrides, overrides);
      Object.assign(t, { version: t.version + 1, updated_at: new Date().toISOString(), updated_by_name: doctorOf(r)!.name });
      return ok(thresholdsOf(p.id));
    }],
    ["GET", "/patients/{id}/summary", (r, p) => consentFor(r, p.id, "timeline", "summary.read") ?? ok(templateSummary(s.timeline))],
    // P3, as the server: every word must appear in the event's values (keys never), current events only; a document link only
    // under a consent that also covers `documents`
    ["GET", "/patients/{id}/search", (r, p) => {
      const denied = consentFor(r, p.id, "timeline", "search");
      if (denied) return denied;
      const raw = decodeURIComponent((r.path.split("?q=")[1] ?? "").split("&")[0].replace(/\+/g, " "));
      if (!raw.trim()) return error(422, "query_required", "Type a word to search for.");
      if (raw.length > 200) return error(422, "query_too_long", "At most 200 characters.");
      const words = toAsciiDigits(raw).toLowerCase().split(/\s+/).filter(Boolean);
      const docs = covers(r, p.id, "documents");
      const hits: SearchHit[] = currentOf(s.timeline)
        .filter((e) => { const text = toAsciiDigits(Object.values(e.payload).join(" ")).toLowerCase(); return words.every((w) => text.includes(w)); })
        .sort((a, b) => b.date.localeCompare(a.date))
        .map((e) => ({ event_id: e.event_id, event_type: e.event_type, date: e.date, source_document_id: docs ? e.source_document_id : null,
                       snippet: citedLine(e).facts.filter((f) => f.field !== "date").map((f) => f.value).join(" · "), match: "keyword" }));
      return ok(hits);
    }],
    ["GET", "/patients/{id}/safety-alerts", (r, p) => consentFor(r, p.id, "safety", "safety.read") ?? ok(s.alerts)],
    // P3 (D6): each verified prescription's M6 check. SYNTHETIC: one completed check with the seeded alerts and one unrecognised
    // medication, so the screen can be tried; names only under a consent that also covers `timeline`
    ["GET", "/patients/{id}/safety-checks", (r, p) => {
      const denied = consentFor(r, p.id, "safety", "safety_checks.read");
      if (denied) return denied;
      const named = covers(r, p.id, "timeline");
      const checks: SafetyCheck[] = [{ document_id: "d-verified", status: "completed", reason: null, attempts: 1, queued_at: s.alerts[0]?.created_at ?? new Date().toISOString(),
        checked_at: s.alerts[0]?.created_at ?? null, alert_count: s.alerts.length,
        unrecognised: [{ event_id: "e-med-2", reason: "not_in_catalog", scope: "prescription", name_as_written: named ? "SYNTH-DRUG-UNLISTED 250 mg" : null }],
        not_run: [{ check: "drug_disease", reason: "diagnoses_not_recorded" }, { check: "allergy_class", reason: "class_data_unavailable" },
                  { check: "duplicate_class", reason: "class_data_unavailable" }, { check: "class_lookback", reason: "class_data_unavailable" }] }];
      return ok(checks);
    }],
    ["POST", "/safety/alerts/{id}/ack", (r, p) => {
      const denied = consentFor(r, s.me.id, "safety", "safety.ack");
      if (denied) return denied;
      const alert = s.alerts.find((a) => a.id === p.id);
      if (!alert) return error(404, "not_found", "No alert with this id.");
      if (alert.status !== "open") return error(409, "not_open", "This alert was already handled.");
      const body = r.body as { action?: string; reason?: string };
      const reason = (body.reason ?? "").trim();
      if (body.action === "override" && !reason) return error(422, "reason_required", "An override needs a reason.");
      if (body.action !== "acknowledge" && body.action !== "override") return error(422, "invalid_action", "Acknowledge or override.");
      alert.status = body.action === "override" ? "overridden" : "acknowledged";
      alert.reason = reason || null;
      return ok(alert);
    }],
    ["POST", "/emergency/access", (r) => {
      const doctor = doctorOf(r);
      if (!doctor || doctor.status !== "verified" || !doctor.emergency_enabled) return error(403, "emergency_not_enabled", "You are not allowed to do this.");
      const body = r.body as { health_id?: string; reason?: string; facility?: string };
      if (!body.reason?.trim() || !body.facility?.trim()) return error(422, "reason_required", "A reason and a facility are required.");
      if (body.health_id !== s.me.health_id) return error(404, "patient_not_found", "No patient has this Health ID.");
      record(doctor, "emergency.access", "allow", body.reason.trim(), null); // audit first, then the card (FRD M10)
      notify("emergency_access", doctor.name, [], body.facility.trim()); // the patient is always notified (FRD M10)
      const e = s.emergency;
      const pick = <K extends keyof NonNullable<EmergencySession["card"]>>(k: K, v: NonNullable<EmergencySession["card"]>[K]) =>
        (e.fields.includes(k as never) ? { [k]: v } : {});
      const card = !e.enabled ? null : { ...pick("blood_group", e.available.blood_group ?? undefined), ...pick("allergies", e.available.allergies),
        ...pick("active_medications", e.available.active_medications), ...pick("conditions", e.available.conditions),
        ...pick("emergency_contacts", e.contacts) };
      const session: EmergencySession = { session_id: `es-${crypto.randomUUID().slice(0, 8)}`, expires_at: new Date(Date.now() + 2 * 3600_000).toISOString(), card };
      // the review list shows it only once the session has closed, like the server (FRD M10)
      s.emergencyReviews.unshift({ id: `er-${session.session_id.slice(3)}`, doctor_id: doctor.id, doctor_name: doctor.name, reason: body.reason.trim(),
        facility: body.facility.trim(), opened_at: new Date().toISOString(), closed_at: session.expires_at,
        fields_shown: card ? (Object.keys(card) as EmergencyReview["fields_shown"]) : [], status: "review_pending", note: null, reviewed_at: null,
        capability_suspended: false });
      return ok(session, 201);
    }],
    ["GET", "/consents", (r) => (authed(r) ? ok(s.consents.filter((c) => s.patientOf[c.id] === MOCK_PATIENT_ID)) : unauthenticated)],
    ["POST", "/consents/{id}/revoke", (r, p) => {
      if (!authed(r)) return unauthenticated;
      const c = ownConsent(p.id);
      if (!c) return error(404, "not_found", "No consent with this id.");
      if (c.status !== "active") return error(409, "not_revocable", "This consent is not active.");
      c.status = "revoked";
      return ok(c);
    }],
    ["GET", "/me/access-history", (r) => (authed(r) ? ok(s.history) : unauthenticated)],
    ...(["approve", "decline"] as const).map((verb): [Method, string, Handler] => ["POST", `/caregiver-authorizations/{id}/${verb}`, (r, p) => {
      if (!authed(r)) return unauthenticated;
      const c = ownConsent(p.id);
      if (c?.purpose !== "CAREGIVER") return error(404, "not_found", "No caregiver request with this id.");
      if (c.status !== "pending") return error(409, "not_pending", "This request is no longer open.");
      if (verb === "approve") approveCare(c);
      else c.status = "declined";
      return ok(c);
    }]),
    // M1/C1 caregiver side (BUILT): ask, confirm with the code the patient reads out, list who I may act for right now.
    ["GET", "/caregiver-authorizations", (r) => {
      const w = who(r);
      if (!w) return unauthenticated;
      if (w.role !== "patient") return roleDenied();
      // pending requests are never listed (the backend's rule: listing them would confirm a guessed Health ID)
      return ok(s.consents.filter((c) => c.purpose === "CAREGIVER" && c.grantee_id === w.sub && c.status === "active" && live(c.expires_at)).map(careView));
    }],
    ["POST", "/caregiver-authorizations", (r) => {
      const w = who(r);
      if (!w) return unauthenticated;
      if (w.role !== "patient") return roleDenied();
      const body = (r.body ?? {}) as { patient_health_id?: unknown; scopes?: unknown; duration_days?: unknown };
      const scopes = Array.isArray(body.scopes) ? body.scopes : [];
      const days = body.duration_days ?? 30;
      if (!scopes.length || scopes.some((x) => !CARE_SCOPES.includes(x)) || !Number.isInteger(days) || (days as number) < 1 || (days as number) > 90) {
        return error(422, "invalid_request", "Check the scopes and the number of days.");
      }
      const pid = patientByHealthId(body.patient_health_id);
      if (pid && pid !== w.sub) { // an unknown Health ID gets the same answer and grants nothing
        s.consents.filter((c) => c.purpose === "CAREGIVER" && c.grantee_id === w.sub && s.patientOf[c.id] === pid && c.status === "pending")
          .forEach((c) => { c.status = "expired"; }); // one pending request per pair: the newest replaces it
        const c: Consent = { id: `c-care-${crypto.randomUUID().slice(0, 8)}`, grantee_id: w.sub, grantee_role: "caregiver", purpose: "CAREGIVER",
          allowed_categories: [...new Set(scopes as string[])], status: "pending", activated_at: null, expires_at: null, created_at: new Date().toISOString(),
          grantee_name: s.records[w.sub]?.name ?? null, grantee_phone_tail: null, requested_days: days as number };
        s.consents.push(c);
        s.patientOf[c.id] = pid;
        issueCode(c.id);
        audit(pid, { actor_id: w.sub, actor_role: "caregiver", action: "caregiver.request", purpose: "CAREGIVER", result: "allow", reason: null,
                     consent_id: c.id, actor_name: c.grantee_name });
        notify("caregiver_request", c.grantee_name, c.allowed_categories, null, pid);
      }
      return ok({ status: "pending" }, 202);
    }],
    ["POST", "/caregiver-authorizations/confirm", (r) => {
      const w = who(r);
      if (!w) return unauthenticated;
      if (w.role !== "patient") return roleDenied();
      const body = (r.body ?? {}) as { patient_health_id?: unknown; code?: unknown };
      const pid = patientByHealthId(body.patient_health_id);
      const c = pid && pid !== w.sub ? s.consents.find((x) => x.purpose === "CAREGIVER" && x.grantee_id === w.sub && s.patientOf[x.id] === pid
        && x.status === "pending") : undefined;
      if (!c || !useCode(c.id, body.code)) return invalidCode(); // every failure looks the same
      approveCare(c);
      return ok(careView(c));
    }],
    // M3 assisted verification (GAP, FRD question 3): the patient's own code, read out, opens a short session for one verifier.
    ["POST", "/verifier/sessions", (r) => {
      const v = staffOf(r, "verifier");
      if (!v) return who(r) ? roleDenied() : unauthenticated;
      if (v.status !== "verified") return error(403, "user_not_verified", "You are not allowed to do this.");
      const pid = patientByHealthId((r.body as { health_id?: unknown } | undefined)?.health_id);
      if (!pid) return error(404, "patient_not_found", "No patient has this Health ID.");
      s.sessions.filter((x) => x.verifier_id === v.id && x.patient_id === pid && x.status === "pending").forEach((x) => { x.status = "expired"; });
      const x = { id: `vs-${crypto.randomUUID().slice(0, 8)}`, verifier_id: v.id, patient_id: pid, status: "pending" as const, activated_at: null, expires_at: null };
      s.sessions.push(x);
      issueCode(x.id);
      audit(pid, { actor_id: v.id, actor_role: "verifier", action: "assist.request", purpose: ASSIST_PURPOSE, result: "allow", reason: null,
                   consent_id: x.id, actor_name: v.name });
      return ok(sessionView(x), 201);
    }],
    ["POST", "/verifier/sessions/{id}/confirm", (r, p) => {
      const v = staffOf(r, "verifier");
      if (!v) return who(r) ? roleDenied() : unauthenticated;
      const x = s.sessions.find((y) => y.id === p.id && y.verifier_id === v.id && y.status === "pending");
      if (!x || !useCode(x.id, (r.body as { code?: unknown } | undefined)?.code)) {
        if (x) audit(x.patient_id, { actor_id: v.id, actor_role: "verifier", action: "assist.confirm", purpose: ASSIST_PURPOSE, result: "deny",
                                      reason: "invalid_code", consent_id: x.id, actor_name: v.name });
        return invalidCode();
      }
      x.status = "active";
      x.activated_at = new Date().toISOString();
      x.expires_at = new Date(Date.now() + MOCK_ASSIST_MINUTES * 60_000).toISOString();
      audit(x.patient_id, { actor_id: v.id, actor_role: "verifier", action: "assist.granted", purpose: ASSIST_PURPOSE, result: "allow", reason: null,
                            consent_id: x.id, actor_name: v.name });
      return ok(sessionView(x));
    }],
    ["POST", "/verifier/sessions/{id}/end", (r, p) => {
      const v = staffOf(r, "verifier");
      if (!v) return who(r) ? roleDenied() : unauthenticated;
      const x = s.sessions.find((y) => y.id === p.id && y.verifier_id === v.id);
      if (!x) return error(404, "not_found", "No session with this id.");
      if (x.status === "active") {
        x.status = "revoked";
        audit(x.patient_id, { actor_id: v.id, actor_role: "verifier", action: "assist.ended", purpose: ASSIST_PURPOSE, result: "allow", reason: null,
                              consent_id: x.id, actor_name: v.name });
      }
      return ok(sessionView(x));
    }],
    ["GET", "/patients/{id}/documents", (r, p) => {
      const denied = gate(r, p.id, VIEW, "documents.list");
      if (denied) return denied;
      const docs = s.records[p.id]?.documents ?? [];
      return ok(who(r)!.role === "verifier" ? docs.filter((d) => !CLOSED_DOCS.includes(d.status)) : docs); // a verifier sees only work to check
    }],
    ["POST", "/documents", (r) => (authed(r) ? upload(r, MOCK_PATIENT_ID) : unauthenticated)],
    ["POST", "/patients/{id}/documents", (r, p) =>
      gate(r, p.id, { care: "upload_documents", verifier: true }, "document.upload") ?? (s.records[p.id] ? upload(r, p.id) : notFound)],
    ["GET", "/documents/{id}", (r, p) => withDoc(r, p.id, VIEW, "document.read", ok, true)],
    ["GET", "/documents/{id}/extraction", (r, p) => withDoc(r, p.id, WORK, "extraction.read",
      (d) => ok({ document_id: d.id, status: d.status, threshold: 0.85, extraction: s.extractions[d.id] ?? null }))],
    ["GET", "/documents/{id}/images/{n}", (r, p) => withDoc(r, p.id, VIEW, "document.image.read", () => ok(syntheticPage()))],
    ["POST", "/documents/{id}/manual-entry", (r, p) => withDoc(r, p.id, WORK, "document.manual_entry", (d) => {
      if (!["uploaded", "extracting", "extraction_failed"].includes(d.status)) return error(409, "not_allowed_state", "The document is not in a state that allows this.");
      d.status = "needs_review";
      const blank = prescriptionFields()!;
      for (const [k, v] of Object.entries(blank.fields)) blank.fields[k] = Array.isArray(v) ? [] : empty();
      s.extractions[d.id] = { ...blank, engine: "manual", raw_text: "", raw_text_available: false };
      return ok({ document_id: d.id, status: d.status, extraction: s.extractions[d.id] });
    })],
    ["POST", "/documents/{id}/retry-extraction", (r, p) => withDoc(r, p.id, WORK, "document.retry", (d) => {
      if (d.status !== "extraction_failed") return error(409, "not_allowed_state", "The document is not in a state that allows this.");
      d.status = "extracting";
      return ok({ document_id: d.id, status: d.status, retries_used: 1, attempts_used: 3, attempts_allowed: 5 });
    })],
    ["PUT", "/documents/{id}/review", (r, p) => withDoc(r, p.id, WORK, "document.review", (d) => {
      if (d.status !== "needs_review") return error(409, "not_allowed_state", "Only a document in review can be changed.");
      s.reviews[d.id] = (r.body as ReviewBody).fields;
      return ok({ document_id: d.id, status: d.status, fields: s.reviews[d.id] });
    })],
    ["POST", "/documents/{id}/confirm", (r, p) => withDoc(r, p.id, WORK, "document.confirm", (d) => {
      if (d.status !== "needs_review") return error(409, "not_allowed_state", "Only a document in review can be confirmed.");
      // as the backend (B4a): a saved check is needed, and the document's own date (never one invented from the upload)
      if (!s.reviews[d.id]) return error(422, "review_required", "Save the check first.", { field: null });
      const dateField = ({ prescription: "prescription_date", lab_report: "report_date", discharge_summary: "discharge_date" } as Record<string, string>)[d.doc_type];
      const dateValue = dateField ? s.reviews[d.id][dateField] : "set";
      if (typeof dateValue !== "string" || !dateValue.trim()) return error(422, "date_required", "The document's date is needed.", { field: dateField });
      d.status = "verified";
      // what the patient checked becomes document_verified events (a sketch of M3 -> C4; the real mapping is the backend's)
      const reviewed = s.reviews[d.id] ?? {};
      const text = (v: unknown) => (typeof v === "string" ? v : "");
      const dmy = text(reviewed.prescription_date).match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/); // the backend parses dates itself
      const date = dmy ? `${dmy[3]}-${dmy[2].padStart(2, "0")}-${dmy[1].padStart(2, "0")}` : new Date().toISOString().slice(0, 10);
      const event = (n: number, type: TimelineEvent["event_type"], payload: Record<string, string>): TimelineEvent => ({
        event_id: `e-${d.id}-${n}`, event_type: type, date, date_precision: "day", verification_status: "document_verified",
        source_document_id: d.id, recorded_at: new Date().toISOString(), version: 1, supersedes: null, payload });
      const prescriber = text(reviewed.prescriber_name);
      const rows = Array.isArray(reviewed.medications) ? reviewed.medications : [];
      s.records[d.patient_id].timeline.unshift(event(0, "prescription", prescriber ? { prescriber_name: prescriber } : {}),
        ...rows.filter((row) => text(row.name_as_written)).map((row, i) => event(i + 1, "medication", { name_as_written: text(row.name_as_written) })));
      return ok(d);
    })],
    ["POST", "/documents/{id}/reject", (r, p) => withDoc(r, p.id, WORK, "document.reject", (d) => {
      if (d.status !== "needs_review") return error(409, "not_allowed_state", "Only a document in review can be rejected.");
      d.status = "rejected";
      return ok(d);
    })],
    // verifiers never read timelines (FRD section 2)
    ["GET", "/patients/{id}/timeline", (r, p) =>
      gate(r, p.id, { doctor: "timeline", care: "view_timeline" }, "timeline.read") ?? ok(s.records[p.id]?.timeline ?? [])],
    ["GET", "/vitals", (r) => (authed(r) ? ok(s.vitals) : unauthenticated)],
    ...(["/vitals", "/vitals/{id}/correct"] as const).map((path): [Method, string, Handler] => ["POST", path, (r, p) => {
      if (!authed(r)) return unauthenticated;
      const entry = r.body as VitalEntry;
      const original = p.id ? s.vitals.find((v) => v.event_id === p.id) : undefined;
      if (p.id && !original) return error(404, "not_found", "No reading with this id.");
      const shape = entry.vital_type === "bp" ? /^\d{2,3}\/\d{2,3}$/ : /^\d+(\.\d+)?$/;
      if (!shape.test(entry.value ?? "") || !["mmHg", "mmol/L", "mg/dL"].includes(entry.unit)) return error(422, "invalid_reading", "Check the value and unit.");
      const { confirm, evaluation } = mockEvaluate(entry);
      if (confirm && !entry.confirmed) return error(422, "confirmation_required", "This value looks unusual. Confirm it.");
      const reading: VitalReading = { event_id: `v-${crypto.randomUUID().slice(0, 8)}`, vital_type: entry.vital_type, value: entry.value,
        unit: entry.unit, context: entry.context, measured_at: entry.measured_at, verification_status: "patient_reported",
        version: original ? original.version + 1 : 1, supersedes: original?.event_id ?? null, recorded_at: new Date().toISOString() };
      s.vitals.push(reading);
      return ok({ reading, evaluation }, 201);
    }]),
    ["POST", "/triage/sessions", (r) => {
      if (!authed(r)) return unauthenticated;
      const message = String((r.body as { message?: unknown } | undefined)?.message ?? "");
      const id = `t-${crypto.randomUUID().slice(0, 8)}`;
      s.triage[id] = 0;
      return ok(triageStep(id, message, 0), 201);
    }],
    ["POST", "/triage/sessions/{id}/answer", (r, p) => {
      if (!authed(r)) return unauthenticated;
      if (!(p.id in s.triage)) return error(404, "not_found", "No triage session with this id.");
      s.triage[p.id] += 1;
      return ok(triageStep(p.id, String((r.body as { answer?: unknown } | undefined)?.answer ?? ""), s.triage[p.id]));
    }],
    ["GET", "/reminders", (r) => (authed(r) ? ok(s.reminders) : unauthenticated)],
    ["PATCH", "/reminders/{id}", (r, p) => {
      if (!authed(r)) return unauthenticated;
      const rem = s.reminders.find((x) => x.id === p.id);
      if (!rem) return error(404, "not_found", "No reminder with this id.");
      const next = (r.body as { status?: string }).status;
      const allowed: Record<string, string[]> = { proposed: ["active", "ended"], active: ["paused", "ended"], paused: ["active", "ended"], ended: [] };
      if (!next || !allowed[rem.status].includes(next)) return error(409, "not_allowed_state", "The reminder is not in a state that allows this.");
      rem.status = next as Reminder["status"];
      return ok(rem);
    }],
    ["POST", "/reminders/{id}/log", (r, p) => {
      if (!authed(r)) return unauthenticated;
      const rem = s.reminders.find((x) => x.id === p.id);
      if (!rem) return error(404, "not_found", "No reminder with this id.");
      if (rem.status !== "active") return error(409, "not_allowed_state", "Only an active reminder can be logged.");
      const action = (r.body as { action?: ReminderLogAction }).action;
      if (!action || !["taken", "skipped", "snoozed"].includes(action)) return error(422, "invalid_action", "Use taken, skipped or snoozed.");
      rem.log.unshift({ action, at: new Date().toISOString() });
      return ok(rem);
    }],
    // ---- F5 clinical reviewer: the rule registry (FRD M6: one registry, versions, only approved rules run)
    ["GET", "/rules", (r) => {
      const u = consoleUser(r, "clinical_reviewer");
      if (!isUser(u)) return u;
      const type = new URLSearchParams(r.path.split("?")[1] ?? "").get("type");
      return ok(s.rules.filter((x) => !type || x.rule_type === type));
    }],
    ["POST", "/rules", (r) => {
      const u = consoleUser(r, "clinical_reviewer");
      if (!isUser(u)) return u;
      const b = (r.body ?? {}) as Partial<{ rule_id: string; rule_type: RuleType; severity: Severity | null; definition: unknown;
                                            explanation: { en?: unknown; bn?: unknown } }>;
      const def = b.definition;
      if (!RULE_TYPES.includes(b.rule_type!) || (b.severity != null && !SEVERITIES.includes(b.severity))
        || !def || typeof def !== "object" || Array.isArray(def) || !Object.keys(def).length
        || typeof b.explanation?.en !== "string" || !b.explanation.en.trim() || typeof b.explanation?.bn !== "string" || !b.explanation.bn.trim()) {
        return error(422, "invalid_rule", "Check the type, severity, definition and both explanations.");
      }
      // B5, as the server (REVIEWER-PENDING vocabulary): a vital_threshold names what it applies to, with a unit that fits it
      const units: Record<string, string[]> = { bp: ["mmHg"], glucose: ["mmol/L", "mg/dL"] };
      const vt = def as { vital_type?: unknown; unit?: unknown };
      if (b.rule_type === "vital_threshold" && !(units[String(vt.vital_type)] ?? []).includes(String(vt.unit))) {
        return error(422, "invalid_vital_threshold", "A vital threshold needs vital_type bp or glucose and a matching unit.");
      }
      if (!engineShapeOk(b.rule_type!, b.severity, def as Record<string, unknown>)) {
        return error(422, "invalid_rule_definition", "This rule type needs its schema-1 definition and a severity.");
      }
      const versions = b.rule_id ? s.rules.filter((x) => x.rule_id === b.rule_id) : [];
      if (b.rule_id && !versions.length) return error(404, "not_found", "No rule with this id.");
      if (versions.length && versions[0].rule_type !== b.rule_type) return error(422, "invalid_rule", "A new version keeps the rule's type.");
      if (versions.some((x) => x.status === "draft")) return error(409, "draft_exists", "This rule already has a draft waiting for review.");
      const ruleId = b.rule_id ?? `RULE-${crypto.randomUUID().slice(0, 6).toUpperCase()}`;
      const rule: Rule = { id: `${ruleId}-v${versions.length + 1}`, rule_id: ruleId, version: versions.length + 1, rule_type: b.rule_type!,
        severity: b.severity ?? null, status: "draft", definition: def as Record<string, unknown>,
        explanation: { en: (b.explanation!.en as string).trim(), bn: (b.explanation!.bn as string).trim() }, created_by_name: u.name,
        created_at: new Date().toISOString(), reviewed_by_name: null, reviewed_at: null, reason: null };
      s.rules.push(rule);
      staffAudit(u, "rule.draft", rule.id);
      return ok(rule, 201);
    }],
    ...(["approve", "reject"] as const).map((verb): [Method, string, Handler] => ["POST", `/rules/{id}/${verb}`, (r, p) => {
      const u = consoleUser(r, "clinical_reviewer");
      if (!isUser(u)) return u;
      const rule = s.rules.find((x) => x.id === p.id);
      if (!rule) return error(404, "not_found", "No rule with this id.");
      if (rule.status !== "draft") return error(409, "not_draft", "Only a draft can be reviewed.");
      const reason = reasonOf(r);
      if (verb === "reject" && !reason) return error(422, "reason_required", "A rejection needs a reason.");
      // B5 four-eyes, as the server: never approved by its author (the author may still withdraw it by rejecting)
      if (verb === "approve" && rule.created_by_name === u.name) return error(409, "four_eyes", "Another reviewer must approve this draft.");
      if (verb === "approve") {
        s.rules.filter((x) => x.rule_id === rule.rule_id && x.status === "approved").forEach((x) => { x.status = "superseded"; });
      }
      Object.assign(rule, { status: verb === "approve" ? "approved" : "rejected", reviewed_by_name: u.name, reviewed_at: new Date().toISOString(),
                            reason: reason || null });
      staffAudit(u, `rule.${verb}`, rule.id);
      return ok(rule);
    }]),
    // ---- F5 clinical reviewer: break-glass post-hoc review (FRD M10)
    ["GET", "/admin/emergency/reviews", (r) => {
      const u = consoleUser(r, "clinical_reviewer");
      return isUser(u) ? ok(s.emergencyReviews.filter((x) => !live(x.closed_at))) : u; // closed sessions only
    }],
    ["POST", "/admin/emergency/reviews/{id}/review", (r, p) => {
      const u = consoleUser(r, "clinical_reviewer");
      if (!isUser(u)) return u;
      const item = s.emergencyReviews.find((x) => x.id === p.id && !live(x.closed_at)); // an open session is not reviewable yet
      if (!item) return error(404, "not_found", "No review with this id.");
      if (item.status !== "review_pending") return error(409, "not_pending", "This session was already reviewed.");
      const body = (r.body ?? {}) as { decision?: unknown; note?: unknown };
      const note = String(body.note ?? "").trim();
      if (body.decision !== "justified" && body.decision !== "unjustified") return error(422, "invalid_decision", "Justified or unjustified.");
      if (body.decision === "unjustified" && !note) return error(422, "reason_required", "Say why the access was not justified.");
      Object.assign(item, { status: body.decision, note: note || null, reviewed_at: new Date().toISOString() });
      if (body.decision === "unjustified") { // FRD M10: an unjustified access suspends the doctor's emergency capability
        if (s.staff[item.doctor_id]) s.staff[item.doctor_id].emergency_enabled = false;
        item.capability_suspended = true;
      }
      staffAudit(u, `emergency.review.${body.decision}`, item.id);
      return ok(item);
    }],
    // ---- F5 admin: credentials (M1), catalog import (M6), audit (C2), worker metrics (D13)
    ["GET", "/credentials", (r) => {
      const u = consoleUser(r, "admin");
      if (!isUser(u)) return u;
      const status = new URLSearchParams(r.path.split("?")[1] ?? "").get("status");
      return ok([...Object.values(s.staff).filter((x) => x.role === "doctor" && x.credential).map(credentialView), ...s.rejectedCredentials]
        .filter((c) => !status || c.status === status));
    }],
    ["POST", "/credentials/{id}/approve", (r, p) => {
      const u = consoleUser(r, "admin");
      if (!isUser(u)) return u;
      const doctor = credentialOwner(p.id);
      if (!doctor || doctor.credential!.status !== "pending") return error(404, "not_found", "No pending credential with this id.");
      doctor.credential!.status = "verified";
      doctor.status = "verified";
      staffAudit(u, "credential.approve", p.id);
      return ok({ user_id: doctor.id, status: "verified" });
    }],
    ["POST", "/credentials/{id}/reject", (r, p) => {
      const u = consoleUser(r, "admin");
      if (!isUser(u)) return u;
      const doctor = credentialOwner(p.id);
      if (!doctor || doctor.credential!.status !== "pending") return error(404, "not_found", "No pending credential with this id.");
      const reason = reasonOf(r);
      if (!reason) return error(422, "reason_required", "A rejection needs a reason.");
      // kept as rejected, like the server; the doctor may submit again; the reason stays in the audit log only as "reason_given"
      s.rejectedCredentials.push({ ...credentialView(doctor), id: `${p.id}-r${s.rejectedCredentials.length + 1}`, status: "rejected" });
      doctor.credential = null;
      staffAudit(u, "credential.reject", p.id, "reason_given");
      return ok({ user_id: doctor.id, status: "rejected" });
    }],
    ["POST", "/admin/users/{id}/suspend", (r, p) => {
      const u = consoleUser(r, "admin");
      if (!isUser(u)) return u;
      const target = s.staff[p.id];
      if (!target || target.role === "admin") return error(404, "not_found", "No staff member with this id.");
      if (!reasonOf(r)) return error(422, "reason_required", "A suspension needs a reason.");
      target.status = "suspended";
      if (target.credential) target.credential.status = "suspended";
      // emergency_enabled is left as it is, like the server: a suspended doctor cannot sign in or pass RBAC anyway
      // FRD section 2: suspension suspends every active grant immediately (the consent state machine's `suspended`)
      s.consents.filter((c) => c.grantee_id === target.id && c.status === "active").forEach((c) => { c.status = "suspended"; });
      s.sessions.filter((x) => x.verifier_id === target.id && x.status === "active").forEach((x) => { x.status = "revoked"; }); // assisted sessions end
      staffAudit(u, "user.suspend", target.id, "reason_given");
      return ok({ user_id: target.id, status: "suspended" });
    }],
    // B7 decision 1: an admin switches a verified doctor's M10 capability (also restores it after an unjustified review)
    ["POST", "/admin/users/{id}/emergency", (r, p) => {
      const u = consoleUser(r, "admin");
      if (!isUser(u)) return u;
      const enabled = (r.body as { enabled?: unknown } | undefined)?.enabled;
      if (typeof enabled !== "boolean") return error(422, "invalid_request", "Send enabled: true or false.");
      const target = s.staff[p.id];
      if (!target || target.role !== "doctor" || target.status !== "verified") return error(404, "not_found", "No verified doctor with this id.");
      target.emergency_enabled = enabled;
      staffAudit(u, enabled ? "user.emergency.enable" : "user.emergency.disable", target.id);
      return ok({ user_id: target.id, emergency_enabled: enabled });
    }],
    // GAP (owner decision 2026-11-16): an admin creates verifier and clinical reviewer accounts and approves a verifier's own
    // registration, so no staff role is left pending with nobody able to approve it. Console roles never self-register.
    ["GET", "/admin/staff", (r) => {
      const u = consoleUser(r, "admin");
      if (!isUser(u)) return u;
      const status = new URLSearchParams(r.path.split("?")[1] ?? "").get("status");
      return ok(Object.values(s.staff).filter((x) => (x.role === "verifier" || x.role === "clinical_reviewer") && (!status || x.status === status))
        .map(staffView));
    }],
    ["POST", "/admin/staff", (r) => {
      const u = consoleUser(r, "admin");
      if (!isUser(u)) return u;
      const b = (r.body ?? {}) as { role?: unknown; name?: unknown; phone?: unknown };
      if (b.role !== "verifier" && b.role !== "clinical_reviewer") return error(422, "invalid_role", "Choose verifier or clinical reviewer.");
      const name = String(b.name ?? "").trim();
      const phone = bdMobile(b.phone);
      if (!name) return error(422, "invalid_name", "Enter the person's name.");
      if (!phone) return error(422, "invalid_phone", "Enter a phone number.");
      if (s.staffPhones.has(phone)) return error(409, "phone_exists", "This phone number already has an account.");
      const id = crypto.randomUUID();
      s.staff[id] = { id, role: b.role, name, status: "verified", emergency_enabled: false, credential: null };
      s.staffPhones.set(phone, id);
      staffAudit(u, "staff.create", id);
      return ok(staffView(s.staff[id]), 201);
    }],
    ["POST", "/admin/staff/{id}/approve", (r, p) => {
      const u = consoleUser(r, "admin");
      if (!isUser(u)) return u;
      const target = s.staff[p.id];
      if (!target || target.role !== "verifier" || target.status !== "pending") return error(404, "not_found", "No pending registration with this id.");
      target.status = "verified";
      staffAudit(u, "staff.approve", target.id);
      return ok(staffView(target));
    }],
    ["POST", "/catalog/import", (r) => {
      const u = consoleUser(r, "admin");
      if (!isUser(u)) return u;
      const file = r.body instanceof FormData ? r.body.get("file") : null;
      if (!(file instanceof File) || !/\.csv$/i.test(file.name) || !file.size) return error(422, "invalid_file", "Choose a non-empty CSV file.");
      const source = String((r.body as FormData).get("source") ?? "").trim();
      if (!source) return error(422, "source_required", "Say where the file came from and on what terms.");
      staffAudit(u, "catalog.validate", file.name);
      // B5, validate and report only. MOCK ONLY: the mock reads nothing from the file (no catalog data exists here, FRD
      // question 1), so every count is 0 and the hash is a placeholder; the server runs the real loader.
      return ok({ id: `imp-${crypto.randomUUID().slice(0, 8)}`, status: "validated", file_name: file.name, size_bytes: file.size,
        sha256: "0".repeat(64), report: { rows: 0, matchable: 0, unmatchable: 0, duplicate_groups: 0, near_duplicate_groups: 0,
          brands_with_several_generics: 0, products_with_several_manufacturers: 0 } }, 201);
    }],
    ["GET", "/audit", (r) => {
      const u = consoleUser(r, "admin");
      if (!isUser(u)) return u;
      const q = new URLSearchParams(r.path.split("?")[1] ?? "");
      let prev = "0".repeat(64);
      let broken: string | null = null;
      for (const e of s.auditLog) { // the server's chain check, over the whole log
        const { prev_hash, entry_hash, ...fields } = e;
        if (!broken && (prev_hash !== prev || entry_hash !== mockHash(prev + JSON.stringify(fields)))) broken = e.id;
        prev = entry_hash;
      }
      const entries: AuditEntry[] = [...s.auditLog].reverse()
        .filter((e) => (!q.get("action") || e.action.startsWith(q.get("action")!)) && (!q.get("result") || e.result === q.get("result"))
          && (!q.get("role") || e.actor_role === q.get("role")))
        .slice(0, 100)
        .map((e) => ({ id: e.id, at: e.at, actor_role: e.actor_role, actor_ref: short(e.actor_id), action: e.action, purpose: e.purpose,
          result: e.result, reason: e.reason && !/^[a-z_]+$/.test(e.reason) ? "free_text_hidden" : e.reason, // no free text (it may hold PHI)
          patient_ref: short(e.patient_id), consent_ref: short(e.consent_id), prev_hash: e.prev_hash, entry_hash: e.entry_hash }));
      return ok({ chain: { status: broken ? "broken" : "intact", checked_at: new Date().toISOString(), entries_checked: s.auditLog.length,
                           first_broken_id: broken }, entries });
    }],
    ["GET", "/internal/metrics", (r) => {
      const u = consoleUser(r, "admin");
      if (!isUser(u)) return u;
      const count = (st: DocumentView["status"]) => allDocs().filter((d) => d.status === st).length;
      const documents = Object.fromEntries((["uploaded", "extracting", "needs_review", "extraction_failed", "verified", "rejected"] as const)
        .map((st) => [st, count(st)])) as WorkerMetrics["documents"];
      // synthetic worker counts: one expired lease, MOCK ONLY, so the D13 warning can be seen
      const worker: WorkerMetrics["worker"] = { due: documents.uploaded + 1, in_flight: documents.extracting,
        lease_expired: 1, failed: documents.extraction_failed, failed_permanent: 0, failed_budget_exhausted: 0,
        failed_retryable: documents.extraction_failed, waiting_backoff: 0, attempts_open_runs: documents.extracting, ocr_executions_total: 12,
        failed_no_retry_last_hour: 0, due_over_15_minutes: 0 };
      return ok({ at: new Date().toISOString(), documents, worker } satisfies WorkerMetrics);
    }],
    ["GET", "/me/emergency-profile", (r) => (authed(r) ? ok(s.emergency) : unauthenticated)],
    ["PUT", "/me/emergency-profile", (r) => {
      if (!authed(r)) return unauthenticated;
      const body = r.body as Pick<EmergencyProfile, "enabled" | "fields" | "contacts">;
      if (body.contacts?.some((c) => !c.name?.trim() || !bdMobile(c.phone))) {
        return error(422, "invalid_contact", "Each contact needs a name and a phone number.");
      }
      const contacts = (body.contacts ?? []).map((c) => ({ ...c, name: c.name.trim(), phone: bdMobile(c.phone)! })); // stored as +880...
      Object.assign(s.emergency, { enabled: !!body.enabled, fields: body.fields ?? [], contacts });
      return ok(s.emergency);
    }],
  ];

  return async (request) => {
    for (const [method, pattern, handler] of routes) {
      const params = method === request.method ? match(pattern, request.path) : null;
      if (params) return handler(request, params);
    }
    return error(501, "not_built_in_mock", `${request.method} ${request.path} has no mock yet.`);
  };
}

function match(pattern: string, path: string): Record<string, string> | null {
  const want = pattern.split("/"), got = path.split("?")[0].split("/");
  if (want.length !== got.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < want.length; i++) {
    if (want[i].startsWith("{")) params[want[i].slice(1, -1)] = decodeURIComponent(got[i]);
    else if (want[i] !== got[i]) return null;
  }
  return params;
}
