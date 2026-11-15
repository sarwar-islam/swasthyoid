import type { ApiRequest, ApiResponse, Method, Transport } from "./client";
import type {
  AccessEntry, Consent, DocType, DocumentView, ExtractedField, ExtractionResponse, FieldRow, Me, OtpVerifyBody, ReviewBody,
  TimelineEvent,
} from "./types";

// In-memory stand-in for /api/v1 with SYNTHETIC data only (invariant 9): no real person, drug or clinic. It answers with the
// backend's shapes and error format (types.ts says which routes are BUILT, FRD or GAP). An unknown route answers 501
// `not_built_in_mock`, never a made-up success. Each mockTransport() call starts from the same fresh synthetic state.

export const MOCK_CODE = "123456"; // the one-time code the mock accepts (no SMS in the mock)
export const MOCK_PHONE = "+8801700000001"; // already registered; any other phone must register with a profile
export const MOCK_PATIENT_ID = "11111111-1111-4111-8111-111111111111";
const DOCTOR_ID = "22222222-2222-4222-8222-222222222222";
const CAREGIVER_ID = "33333333-3333-4333-8333-333333333333";
const OTHER_DOCTOR_ID = "44444444-4444-4444-8444-444444444444";

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
  const doc = (id: string, status: DocumentView["status"], hoursAgo: number, docType: DocType = "prescription"): DocumentView =>
    ({ id, patient_id: MOCK_PATIENT_ID, doc_type: docType, status, uploaded_by: MOCK_PATIENT_ID, created_at: iso(-hoursAgo),
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
    ev("e-bp-1", "vital_reading", "2026-11-10", "patient_reported", { reading: "150/95 mmHg" }),
    ev("e-bp-2", "vital_reading", "2026-11-10", "patient_reported", { reading: "130/85 mmHg" }, { version: 2, supersedes: "e-bp-1" }),
  ];
  return { me, consents, history, documents, extractions, timeline, phones: new Set([MOCK_PHONE]), reviews: {} as Record<string, ReviewBody["fields"]> };
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
  const authed = (r: ApiRequest) => (r.headers.Authorization ?? "").startsWith("Bearer ");
  const unauthenticated = error(401, "unauthenticated", "Sign in first.");
  const findDoc = (id: string) => s.documents.find((d) => d.id === id);
  const notFound = error(404, "not_found", "No document with this id.");

  const routes: Array<[Method, string, Handler]> = [
    ["GET", "/health", () => ok({ status: "ok" })],
    ["POST", "/auth/otp/request", (r) => {
      const phone = (r.body as { phone?: unknown } | undefined)?.phone;
      return typeof phone === "string" && phone.trim() ? ok(null, 204) : error(422, "invalid_phone", "Enter a phone number.");
    }],
    ["POST", "/auth/otp/verify", (r) => {
      const body = r.body as Partial<OtpVerifyBody> | undefined;
      if (body?.code !== MOCK_CODE) return error(401, "invalid_code", "The code is wrong or has expired.");
      if (!s.phones.has(body.phone ?? "")) {
        if (!body.profile) return error(409, "registration_required", "Request a new code and send your profile with it.");
        s.phones.add(body.phone ?? ""); // shortcut: every mock registration signs in to the one synthetic patient
      }
      return ok({ access_token: mockJwt(MOCK_PATIENT_ID, "patient"), refresh_token: "synthetic-refresh-token" });
    }],
    ["GET", "/me", (r) => (authed(r) ? ok(s.me) : unauthenticated)],
    ["GET", "/consents", (r) => (authed(r) ? ok(s.consents) : unauthenticated)],
    ["POST", "/consents/{id}/revoke", (r, p) => {
      if (!authed(r)) return unauthenticated;
      const c = s.consents.find((x) => x.id === p.id);
      if (!c) return error(404, "not_found", "No consent with this id.");
      if (c.status !== "active") return error(409, "not_revocable", "This consent is not active.");
      c.status = "revoked";
      return ok(c);
    }],
    ["GET", "/me/access-history", (r) => (authed(r) ? ok(s.history) : unauthenticated)],
    ...(["approve", "decline"] as const).map((verb): [Method, string, Handler] => ["POST", `/caregiver-authorizations/{id}/${verb}`, (r, p) => {
      if (!authed(r)) return unauthenticated;
      const c = s.consents.find((x) => x.id === p.id && x.purpose === "CAREGIVER");
      if (!c) return error(404, "not_found", "No caregiver request with this id.");
      if (c.status !== "pending") return error(409, "not_pending", "This request is no longer open.");
      c.status = verb === "approve" ? "active" : "declined";
      if (verb === "approve") {
        c.activated_at = new Date().toISOString();
        c.expires_at = new Date(Date.now() + (c.requested_days ?? 30) * 86400_000).toISOString();
      }
      return ok(c);
    }]),
    ["GET", "/patients/{id}/documents", (r) => (authed(r) ? ok(s.documents) : unauthenticated)],
    ["POST", "/documents", (r) => {
      if (!authed(r)) return unauthenticated;
      const form = r.body instanceof FormData ? r.body : new FormData();
      const images = form.getAll("images").filter((f): f is File => f instanceof File);
      if (images.length < 1 || images.length > 10) return error(422, "invalid_document", "Send 1 to 10 images.");
      // mock-only rule so the retake flow can be tried: a file whose name contains "blur" is a poor page
      const poor = images.map((f, i) => ({ page: i + 1, f })).filter(({ f }) => /blur/i.test(f.name));
      if (poor.length && form.get("upload_anyway") !== "true") {
        return error(422, "image_quality_warning", "Some pages look poor. Retake them, or upload anyway.", {
          pages: poor.map(({ page }) => ({ page, reasons: ["image_blurry"],
            // the owner-approved text from capture/guidance.py, copied as-is
            guidance: [{ code: "image_blurry", bn: "ছবিটি ঝাপসা হয়েছে। ক্যামেরা স্থির রেখে আবার পরিষ্কার ছবি তুলুন।" }] })) });
      }
      const created: DocumentView = { id: `d-${crypto.randomUUID().slice(0, 8)}`, patient_id: MOCK_PATIENT_ID,
        doc_type: (form.get("doc_type") as DocType) ?? "prescription", status: "uploaded", uploaded_by: MOCK_PATIENT_ID,
        created_at: new Date().toISOString(),
        images: images.map((f, i) => ({ n: i + 1, content_type: f.type || "image/png", size_bytes: f.size, sha256: "0".repeat(64),
          quality_warnings: poor.some((x) => x.page === i + 1) ? ["image_blurry"] : [] })) };
      s.documents.unshift(created);
      return ok(created, 201);
    }],
    ["GET", "/documents/{id}", (r, p) => (!authed(r) ? unauthenticated : findDoc(p.id) ? ok(findDoc(p.id)) : notFound)],
    ["GET", "/documents/{id}/extraction", (r, p) => {
      if (!authed(r)) return unauthenticated;
      const d = findDoc(p.id);
      return d ? ok({ document_id: d.id, status: d.status, threshold: 0.85, extraction: s.extractions[d.id] ?? null }) : notFound;
    }],
    ["GET", "/documents/{id}/images/{n}", (r, p) => (!authed(r) ? unauthenticated : findDoc(p.id) ? ok(syntheticPage()) : notFound)],
    ["POST", "/documents/{id}/manual-entry", (r, p) => {
      if (!authed(r)) return unauthenticated;
      const d = findDoc(p.id);
      if (!d) return notFound;
      if (!["uploaded", "extracting", "extraction_failed"].includes(d.status)) return error(409, "not_allowed_state", "The document is not in a state that allows this.");
      d.status = "needs_review";
      const blank = prescriptionFields()!;
      for (const [k, v] of Object.entries(blank.fields)) blank.fields[k] = Array.isArray(v) ? [] : empty();
      s.extractions[d.id] = { ...blank, engine: "manual", raw_text: "", raw_text_available: false };
      return ok({ document_id: d.id, status: d.status, extraction: s.extractions[d.id] });
    }],
    ["POST", "/documents/{id}/retry-extraction", (r, p) => {
      if (!authed(r)) return unauthenticated;
      const d = findDoc(p.id);
      if (!d) return notFound;
      if (d.status !== "extraction_failed") return error(409, "not_allowed_state", "The document is not in a state that allows this.");
      d.status = "extracting";
      return ok({ document_id: d.id, status: d.status, retries_used: 1, attempts_used: 3, attempts_allowed: 5 });
    }],
    ["PUT", "/documents/{id}/review", (r, p) => {
      if (!authed(r)) return unauthenticated;
      const d = findDoc(p.id);
      if (!d) return notFound;
      if (d.status !== "needs_review") return error(409, "not_allowed_state", "Only a document in review can be changed.");
      s.reviews[d.id] = (r.body as ReviewBody).fields;
      return ok({ document_id: d.id, status: d.status, fields: s.reviews[d.id] });
    }],
    ["POST", "/documents/{id}/confirm", (r, p) => {
      if (!authed(r)) return unauthenticated;
      const d = findDoc(p.id);
      if (!d) return notFound;
      if (d.status !== "needs_review") return error(409, "not_allowed_state", "Only a document in review can be confirmed.");
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
      s.timeline.unshift(event(0, "prescription", prescriber ? { prescriber_name: prescriber } : {}),
        ...rows.filter((row) => text(row.name_as_written)).map((row, i) => event(i + 1, "medication", { name_as_written: text(row.name_as_written) })));
      return ok(d);
    }],
    ["POST", "/documents/{id}/reject", (r, p) => {
      if (!authed(r)) return unauthenticated;
      const d = findDoc(p.id);
      if (!d) return notFound;
      if (d.status !== "needs_review") return error(409, "not_allowed_state", "Only a document in review can be rejected.");
      d.status = "rejected";
      return ok(d);
    }],
    ["GET", "/patients/{id}/timeline", (r) => (authed(r) ? ok(s.timeline) : unauthenticated)],
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
