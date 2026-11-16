import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CAREGIVER_TOKEN, DOCTOR_TOKEN, PATIENT_TOKEN, VERIFIER_TOKEN } from "../test-utils";
import { ApiError, createClient, type Transport } from "./client";
import { ASSIST_PURPOSE, MOCK_ASSIST_MINUTES, MOCK_CODE, MOCK_HEALTH_ID, MOCK_OTHERS, MOCK_PATIENT_ID, mockTransport } from "./mock";
import type { AccessEntry, AssistSession, CaregiverAuthorization, DocumentView, TimelineEvent } from "./types";

// F4 access rules at the API layer: every call here goes straight to the mock API, around the UI, so nothing passes only
// because a screen hid a button. RBAC -> C1 -> C2 for every non-patient read; one-time codes single use and short-lived.

let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => { fetchSpy = vi.spyOn(globalThis, "fetch"); });
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled(); // no network: the mock answers everything
  fetchSpy.mockRestore();
  vi.useRealTimers();
});

let transport: Transport;
beforeEach(() => { transport = mockTransport(); });
const as = (token: string) => createClient(transport, () => token);
const patient = () => as(PATIENT_TOKEN);
const verifier = () => as(VERIFIER_TOKEN);

async function failure(call: Promise<unknown>): Promise<[number, string]> {
  try {
    await call;
  } catch (e) {
    if (e instanceof ApiError) return [e.status, e.code];
    throw e;
  }
  throw new Error("expected the API to refuse");
}

const { full, timeline: timelineOnly, revoked, pending } = MOCK_OTHERS;
const upload = () => {
  const form = new FormData();
  form.append("doc_type", "prescription");
  form.append("upload_anyway", "false");
  form.append("images", new File(["synthetic"], "page.png", { type: "image/png" }));
  return form;
};
const history = () => patient().request<AccessEntry[]>("GET", "/me/access-history");

/** Open an assisted session for the mock patient with their code; returns the active session. */
async function openSession(healthId = MOCK_HEALTH_ID) {
  const s = await verifier().request<AssistSession>("POST", "/verifier/sessions", { body: { health_id: healthId } });
  return verifier().request<AssistSession>("POST", `/verifier/sessions/${s.id}/confirm`, { body: { code: MOCK_CODE } });
}

describe("verifier: the patient's code read out, then a short session", () => {
  it("a correct code opens a session for this patient only, and never returns the code", async () => {
    const requested = await verifier().request<AssistSession>("POST", "/verifier/sessions", { body: { health_id: MOCK_HEALTH_ID.toLowerCase() } });
    expect(requested).toMatchObject({ status: "pending", purpose: ASSIST_PURPOSE, patient_id: null, health_id: MOCK_HEALTH_ID });
    expect(JSON.stringify(requested)).not.toContain(MOCK_CODE);
    const active = await verifier().request<AssistSession>("POST", `/verifier/sessions/${requested.id}/confirm`, { body: { code: MOCK_CODE } });
    expect(active).toMatchObject({ status: "active", patient_id: MOCK_PATIENT_ID });
    expect(Date.parse(active.expires_at!) - Date.now()).toBeLessThanOrEqual(MOCK_ASSIST_MINUTES * 60_000);
    // the verifier sees only documents still to check, never the verified record
    const docs = await verifier().request<DocumentView[]>("GET", `/patients/${MOCK_PATIENT_ID}/documents`);
    expect(docs.map((d) => d.status).sort()).toEqual(["extracting", "extraction_failed", "needs_review"]);
  });

  it("writes the request, the grant and every read to the patient's access history (C2), with no code in it", async () => {
    const s = await openSession();
    await verifier().request("GET", "/documents/d-review/extraction");
    const mine = (await history()).filter((h) => h.actor_role === "verifier");
    expect(mine.map((h) => h.action).reverse()).toEqual(["assist.request", "assist.granted", "extraction.read"]);
    expect(mine.every((h) => h.purpose === ASSIST_PURPOSE && h.consent_id === s.id && h.result === "allow")).toBe(true);
    expect(JSON.stringify(await history())).not.toContain(MOCK_CODE);
  });

  it("rejects a wrong code, and a code is dead after five wrong tries", async () => {
    const s = await verifier().request<AssistSession>("POST", "/verifier/sessions", { body: { health_id: MOCK_HEALTH_ID } });
    const confirm = (code: string) => verifier().request("POST", `/verifier/sessions/${s.id}/confirm`, { body: { code } });
    expect(await failure(confirm("000000"))).toEqual([403, "invalid_code"]);
    for (let i = 0; i < 4; i++) await failure(confirm("000000"));
    expect(await failure(confirm(MOCK_CODE))).toEqual([403, "invalid_code"]); // the right code, too late
    expect(await failure(verifier().request("GET", `/patients/${MOCK_PATIENT_ID}/documents`))).toEqual([403, "consent_required"]);
    expect((await history()).some((h) => h.action === "assist.confirm" && h.result === "deny")).toBe(true);
  });

  it("rejects an expired code", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const s = await verifier().request<AssistSession>("POST", "/verifier/sessions", { body: { health_id: MOCK_HEALTH_ID } });
    vi.setSystemTime(Date.now() + 5 * 60_000 + 1000);
    expect(await failure(verifier().request("POST", `/verifier/sessions/${s.id}/confirm`, { body: { code: MOCK_CODE } }))).toEqual([403, "invalid_code"]);
  });

  it("a used code cannot be replayed", async () => {
    const s = await openSession();
    expect(await failure(verifier().request("POST", `/verifier/sessions/${s.id}/confirm`, { body: { code: MOCK_CODE } }))).toEqual([403, "invalid_code"]);
  });

  it("refuses a verifier with no session, another patient, the timeline, verified content, and an ended or expired session", async () => {
    expect(await failure(verifier().request("GET", `/patients/${MOCK_PATIENT_ID}/documents`))).toEqual([403, "consent_required"]);
    expect(await failure(verifier().request("GET", "/documents/d-review/extraction"))).toEqual([403, "consent_required"]);
    expect(await failure(verifier().request("POST", `/patients/${MOCK_PATIENT_ID}/documents`, { body: upload() }))).toEqual([403, "consent_required"]);
    const s = await openSession();
    expect(await failure(verifier().request("GET", `/patients/${full.id}/documents`))).toEqual([403, "consent_required"]); // another patient
    expect(await failure(verifier().request("GET", `/documents/d-full-review/extraction`))).toEqual([403, "consent_required"]);
    expect(await failure(verifier().request("GET", `/patients/${MOCK_PATIENT_ID}/timeline`))).toEqual([403, "role_not_allowed"]);
    expect(await failure(verifier().request("GET", "/documents/d-verified/images/1"))).toEqual([404, "not_found"]);
    expect(await failure(verifier().request("GET", "/documents/d-verified/extraction"))).toEqual([404, "not_found"]);
    expect(await failure(verifier().request("GET", "/consents"))).toEqual([401, "unauthenticated"]);
    expect(await failure(verifier().request("GET", "/me/access-history"))).toEqual([401, "unauthenticated"]);
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.now() + MOCK_ASSIST_MINUTES * 60_000 + 1000);
    expect(await failure(verifier().request("GET", `/patients/${MOCK_PATIENT_ID}/documents`))).toEqual([403, "consent_required"]);
    const again = await openSession(); // still at the later time, so the first session stays expired
    await verifier().request("POST", `/verifier/sessions/${again.id}/end`);
    expect(await failure(verifier().request("GET", `/patients/${MOCK_PATIENT_ID}/documents`))).toEqual([403, "consent_required"]);
    expect(s.id).not.toBe(again.id);
  });

  it("only a verified verifier may start, and no other role may", async () => {
    const tokens = await createClient(transport).request<{ access_token: string }>("POST", "/auth/otp/verify",
      { body: { phone: "+8801900000077", code: MOCK_CODE, device_id: "t", account: "staff", staff: { role: "verifier", name: "New CHW" } } });
    expect(await failure(as(tokens.access_token).request("POST", "/verifier/sessions", { body: { health_id: MOCK_HEALTH_ID } })))
      .toEqual([403, "user_not_verified"]);
    for (const token of [PATIENT_TOKEN, DOCTOR_TOKEN, CAREGIVER_TOKEN]) {
      expect(await failure(as(token).request("POST", "/verifier/sessions", { body: { health_id: MOCK_HEALTH_ID } }))).toEqual([403, "role_not_allowed"]);
    }
  });

  it("with the patient present, uploads and confirms a check; the events reach the patient's timeline", async () => {
    await openSession();
    const created = await verifier().request<DocumentView>("POST", `/patients/${MOCK_PATIENT_ID}/documents`, { body: upload() });
    expect(created).toMatchObject({ patient_id: MOCK_PATIENT_ID, status: "uploaded" });
    await verifier().request("PUT", "/documents/d-review/review", { body: { fields: { prescription_date: "12/11/2026", prescriber_name: "Dr. Synthetic Prescriber", medications: [] } } });
    await verifier().request("POST", "/documents/d-review/confirm");
    const events = await patient().request<TimelineEvent[]>("GET", `/patients/${MOCK_PATIENT_ID}/timeline`);
    expect(events.some((e) => e.source_document_id === "d-review")).toBe(true);
    expect((await verifier().request<DocumentView>("GET", "/documents/d-review")).status).toBe("verified"); // its status line only
    expect(await failure(verifier().request("GET", "/documents/d-review/images/1"))).toEqual([404, "not_found"]);
  });
});

describe("caregiver: only active authorizations, only their scopes", () => {
  it("lists only active authorizations, never pending or revoked ones", async () => {
    const list = await patient().request<CaregiverAuthorization[]>("GET", "/caregiver-authorizations");
    expect(list.map((a) => a.patient_id).sort()).toEqual([full.id, timelineOnly.id].sort());
    expect(list.find((a) => a.patient_id === timelineOnly.id)!.scopes).toEqual(["view_timeline"]);
  });

  it("a request answers the same for an unknown Health ID, grants nothing until the patient's code, then the scopes asked", async () => {
    const ask = (hid: string) => patient().request("POST", "/caregiver-authorizations",
      { body: { patient_health_id: hid, scopes: ["view_documents"], duration_days: 10 } });
    expect(await ask("SID-0000000000")).toEqual({ status: "pending" });
    expect(await ask(revoked.health_id)).toEqual({ status: "pending" });
    expect((await patient().request<CaregiverAuthorization[]>("GET", "/caregiver-authorizations")).some((a) => a.patient_id === revoked.id)).toBe(false);
    expect(await failure(patient().request("GET", `/patients/${revoked.id}/documents`))).toEqual([403, "consent_required"]);
    expect(await failure(patient().request("POST", "/caregiver-authorizations/confirm", { body: { patient_health_id: revoked.health_id, code: "999999" } })))
      .toEqual([403, "invalid_code"]);
    const granted = await patient().request<CaregiverAuthorization>("POST", "/caregiver-authorizations/confirm",
      { body: { patient_health_id: revoked.health_id, code: MOCK_CODE } });
    expect(granted).toMatchObject({ status: "active", scopes: ["view_documents"], requested_days: 10 });
    expect(await patient().request<DocumentView[]>("GET", `/patients/${revoked.id}/documents`)).toHaveLength(2);
    expect(await failure(patient().request("GET", `/patients/${revoked.id}/timeline`))).toEqual([403, "category_not_allowed"]);
    // the used code cannot be replayed, and an unknown Health ID never confirms
    expect(await failure(patient().request("POST", "/caregiver-authorizations/confirm", { body: { patient_health_id: revoked.health_id, code: MOCK_CODE } })))
      .toEqual([403, "invalid_code"]);
    expect(await failure(patient().request("POST", "/caregiver-authorizations/confirm", { body: { patient_health_id: "SID-0000000000", code: MOCK_CODE } })))
      .toEqual([403, "invalid_code"]);
  });

  it("refuses a request with no scope, an unknown scope or too many days", async () => {
    for (const body of [{ scopes: [] }, { scopes: ["verify_documents"] }, { scopes: ["view_timeline"], duration_days: 91 }]) {
      expect(await failure(patient().request("POST", "/caregiver-authorizations", { body: { patient_health_id: full.health_id, ...body } })))
        .toEqual([422, "invalid_request"]);
    }
  });

  it("an approved caregiver reads and uploads within the scopes, and every read is audited for the patient", async () => {
    expect((await patient().request<TimelineEvent[]>("GET", `/patients/${full.id}/timeline`))[0].payload.name_as_written).toBe("SYNTH-DRUG-100");
    expect(await patient().request<DocumentView[]>("GET", `/patients/${full.id}/documents`)).toHaveLength(2);
    expect((await patient().request<DocumentView>("GET", "/documents/d-full-verified")).patient_id).toBe(full.id);
    const created = await patient().request<DocumentView>("POST", `/patients/${full.id}/documents`, { body: upload() });
    expect(created).toMatchObject({ patient_id: full.id, uploaded_by: MOCK_PATIENT_ID });
    // the mock patient's own access history shows a caregiver acting for THEM: approve the pending request and use it
    await patient().request("POST", "/caregiver-authorizations/c-caregiver/approve");
    await as(CAREGIVER_TOKEN).request("GET", `/patients/${MOCK_PATIENT_ID}/timeline`);
    const entry = (await history()).find((h) => h.actor_role === "caregiver");
    expect(entry).toMatchObject({ action: "timeline.read", purpose: "CAREGIVER", result: "allow", consent_id: "c-caregiver" });
  });

  it("refuses pending and revoked authorizations, and stops at the next request after the patient revokes", async () => {
    expect(await failure(patient().request("GET", `/patients/${pending.id}/timeline`))).toEqual([403, "consent_required"]);
    expect(await failure(patient().request("GET", `/patients/${revoked.id}/timeline`))).toEqual([403, "consent_required"]);
    const caregiver = as(CAREGIVER_TOKEN);
    expect(await failure(caregiver.request("GET", `/patients/${MOCK_PATIENT_ID}/timeline`))).toEqual([403, "consent_required"]); // still pending
    await patient().request("POST", "/caregiver-authorizations/c-caregiver/approve");
    await caregiver.request("GET", `/patients/${MOCK_PATIENT_ID}/timeline`);
    await patient().request("POST", "/consents/c-caregiver/revoke");
    expect(await failure(caregiver.request("GET", `/patients/${MOCK_PATIENT_ID}/timeline`))).toEqual([403, "consent_required"]);
    expect((await history()).filter((h) => h.actor_role === "caregiver" && h.action === "timeline.read").map((h) => h.result))
      .toEqual(["deny", "allow", "deny"]); // newest first
    expect((await history()).some((h) => h.action === "caregiver.granted" && h.consent_id === "c-caregiver")).toBe(true);
  });

  it("enforces each scope: no view_documents, no documents; no upload_documents, no upload", async () => {
    expect(await patient().request<TimelineEvent[]>("GET", `/patients/${timelineOnly.id}/timeline`)).toHaveLength(1);
    expect(await failure(patient().request("GET", `/patients/${timelineOnly.id}/documents`))).toEqual([403, "category_not_allowed"]);
    expect(await failure(patient().request("GET", "/documents/d-timeline-verified"))).toEqual([403, "category_not_allowed"]);
    expect(await failure(patient().request("GET", "/documents/d-timeline-verified/images/1"))).toEqual([403, "category_not_allowed"]);
    expect(await failure(patient().request("POST", `/patients/${timelineOnly.id}/documents`, { body: upload() }))).toEqual([403, "category_not_allowed"]);
  });

  it("never lets a caregiver verify, manage consent or read the access history, whatever the scopes", async () => {
    for (const [method, path] of [["GET", "/documents/d-full-review/extraction"], ["PUT", "/documents/d-full-review/review"],
      ["POST", "/documents/d-full-review/confirm"], ["POST", "/documents/d-full-review/reject"]] as const) {
      expect(await failure(patient().request(method, path, { body: { fields: {} } }))).toEqual([403, "role_not_allowed"]);
    }
    const caregiver = as(CAREGIVER_TOKEN);
    await patient().request("POST", "/caregiver-authorizations/c-caregiver/approve");
    expect(await failure(caregiver.request("GET", "/me/access-history"))).toEqual([401, "unauthenticated"]);
    expect(await failure(caregiver.request("GET", "/consents"))).toEqual([401, "unauthenticated"]);
    expect(await failure(caregiver.request("POST", "/consents/c-active/revoke"))).toEqual([401, "unauthenticated"]);
    expect(await failure(caregiver.request("POST", "/caregiver-authorizations/c-caregiver/approve"))).toEqual([401, "unauthenticated"]);
    expect(await failure(caregiver.request("POST", "/verifier/sessions", { body: { health_id: MOCK_HEALTH_ID } }))).toEqual([403, "role_not_allowed"]);
    // the mock patient cannot approve or revoke another patient's authorizations either
    expect(await failure(patient().request("POST", "/caregiver-authorizations/c-care-pending/approve"))).toEqual([404, "not_found"]);
    expect(await failure(patient().request("POST", "/consents/c-care-full/revoke"))).toEqual([404, "not_found"]);
  });

  it("keeps patients apart: one authorization opens one record, and a doctor's consent opens no one else", async () => {
    for (const other of [timelineOnly, revoked, pending]) {
      expect((await failure(patient().request("GET", `/patients/${other.id}/documents`)))[0]).toBe(403);
    }
    expect(await failure(patient().request("GET", "/documents/d-pending-review"))).toEqual([403, "consent_required"]);
    expect(await failure(as(CAREGIVER_TOKEN).request("GET", `/patients/${full.id}/timeline`))).toEqual([403, "consent_required"]);
    expect(await failure(as(CAREGIVER_TOKEN).request("GET", "/documents/d-review"))).toEqual([403, "consent_required"]);
    expect(await failure(as(DOCTOR_TOKEN).request("GET", `/patients/${full.id}/timeline`))).toEqual([403, "consent_required"]);
    expect(await failure(as(DOCTOR_TOKEN).request("GET", "/documents/d-full-verified"))).toEqual([403, "consent_required"]);
    // the full caregiver's own records are not the other patient's: the timeline holds only that patient's events
    const events = await patient().request<TimelineEvent[]>("GET", `/patients/${full.id}/timeline`);
    expect(events.map((e) => e.event_id)).toEqual(["e-full-med"]);
  });
});
