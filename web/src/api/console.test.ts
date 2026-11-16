import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ADMIN_TOKEN, CAREGIVER_TOKEN, DOCTOR_TOKEN, PATIENT_TOKEN, REVIEWER_TOKEN, VERIFIER_TOKEN } from "../test-utils";
import { ApiError, createClient, type Transport } from "./client";
import { MOCK_DOCTOR_ID, MOCK_HEALTH_ID, MOCK_PATIENT_ID, MOCK_SUBMITTED_DOCTOR_ID, mockTransport } from "./mock";
import type { AuditPage, CatalogImport, CredentialReview, DoctorConsent, EmergencyReview, Rule, StaffMe, WorkerMetrics } from "./types";

// F5 console rules at the API layer, called around the UI: a clinical reviewer and an admin each reach only their own routes, and
// neither reaches any patient's record.

let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => { fetchSpy = vi.spyOn(globalThis, "fetch"); });
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled();
  fetchSpy.mockRestore();
});

let transport: Transport;
beforeEach(() => { transport = mockTransport(); });
const as = (token: string) => createClient(transport, () => token);
const reviewer = () => as(REVIEWER_TOKEN);
const admin = () => as(ADMIN_TOKEN);

async function failure(call: Promise<unknown>): Promise<[number, string]> {
  try {
    await call;
  } catch (e) {
    if (e instanceof ApiError) return [e.status, e.code];
    throw e;
  }
  throw new Error("expected the API to refuse");
}

const draft = (extra: object = {}) => ({ rule_type: "allergy", severity: "moderate", definition: { placeholder: "REVIEWER-PENDING" },
  explanation: { en: "[REVIEWER-PENDING] text", bn: "[রিভিউয়ার-অনুমোদন বাকি] লেখা" }, ...extra });
const csv = (name = "synthetic.csv", body = "generic\nSYNTH-DRUG-001\n") => {
  const form = new FormData();
  form.append("file", new File([body], name, { type: "text/csv" }));
  return form;
};

describe("clinical reviewer: the rule registry", () => {
  it("lists rules by type", async () => {
    const ddi = await reviewer().request<Rule[]>("GET", "/rules?type=ddi");
    expect(ddi.map((r) => r.id)).toEqual(["SYNTH-DDI-0001-v1", "SYNTH-DDI-0001-v2"]);
    expect((await reviewer().request<Rule[]>("GET", "/rules")).length).toBe(6);
  });

  it("drafts a rule, approves it, and a new version supersedes the approved one", async () => {
    const created = await reviewer().request<Rule>("POST", "/rules", { body: draft() });
    expect(created).toMatchObject({ status: "draft", version: 1, rule_type: "allergy" });
    expect(await failure(reviewer().request("POST", "/rules", { body: draft({ rule_id: created.rule_id }) }))).toEqual([409, "draft_exists"]);
    await reviewer().request("POST", `/rules/${created.id}/approve`);
    const v2 = await reviewer().request<Rule>("POST", "/rules", { body: draft({ rule_id: created.rule_id, severity: "minor" }) });
    expect(v2.version).toBe(2);
    await reviewer().request("POST", `/rules/${v2.id}/approve`);
    const versions = (await reviewer().request<Rule[]>("GET", "/rules")).filter((r) => r.rule_id === created.rule_id);
    expect(versions.map((r) => r.status)).toEqual(["superseded", "approved"]); // only one approved version runs
  });

  it("rejects only with a reason, and a reviewed version cannot be reviewed again", async () => {
    expect(await failure(reviewer().request("POST", "/rules/SYNTH-VT-0001-v1/reject", { body: { reason: " " } }))).toEqual([422, "reason_required"]);
    const rejected = await reviewer().request<Rule>("POST", "/rules/SYNTH-VT-0001-v1/reject", { body: { reason: "Placeholder values" } });
    expect(rejected).toMatchObject({ status: "rejected", reason: "Placeholder values" });
    expect(await failure(reviewer().request("POST", "/rules/SYNTH-VT-0001-v1/approve"))).toEqual([409, "not_draft"]);
    expect(await failure(reviewer().request("POST", "/rules/SYNTH-DDI-0001-v1/approve"))).toEqual([409, "not_draft"]);
  });

  it("refuses a malformed rule", async () => {
    for (const bad of [{ rule_type: "dosing" }, { severity: "fatal" }, { definition: [] }, { definition: {} },
      { explanation: { en: "only English", bn: " " } }, { rule_id: "SYNTH-ALG-0001", rule_type: "ddi" }]) {
      expect(await failure(reviewer().request("POST", "/rules", { body: draft(bad) }))).toEqual([422, "invalid_rule"]);
    }
    expect(await failure(reviewer().request("POST", "/rules", { body: draft({ rule_id: "NO-SUCH-RULE" }) }))).toEqual([404, "not_found"]);
  });

  it("only a verified clinical reviewer may read, draft or review rules", async () => {
    for (const token of [ADMIN_TOKEN, DOCTOR_TOKEN, PATIENT_TOKEN, VERIFIER_TOKEN, CAREGIVER_TOKEN]) {
      expect(await failure(as(token).request("GET", "/rules"))).toEqual([403, "role_not_allowed"]);
      expect(await failure(as(token).request("POST", "/rules", { body: draft() }))).toEqual([403, "role_not_allowed"]);
      expect(await failure(as(token).request("POST", "/rules/SYNTH-EM-0001-v1/approve"))).toEqual([403, "role_not_allowed"]);
    }
    expect(await failure(createClient(transport).request("GET", "/rules"))).toEqual([401, "unauthenticated"]);
  });
});

describe("clinical reviewer: break-glass post-hoc review", () => {
  it("unjustified needs a note and suspends the doctor's emergency capability; a session cannot be reviewed twice", async () => {
    expect(await failure(reviewer().request("POST", "/admin/emergency/reviews/er-1/review", { body: { decision: "unjustified" } })))
      .toEqual([422, "reason_required"]);
    const done = await reviewer().request<EmergencyReview>("POST", "/admin/emergency/reviews/er-1/review",
      { body: { decision: "unjustified", note: "No emergency documented" } });
    expect(done).toMatchObject({ status: "unjustified", capability_suspended: true });
    expect((await as(DOCTOR_TOKEN).request<StaffMe>("GET", "/me")).emergency_enabled).toBe(false);
    expect(await failure(as(DOCTOR_TOKEN).request("POST", "/emergency/access", { body: { health_id: MOCK_HEALTH_ID, reason: "x", facility: "y" } })))
      .toEqual([403, "emergency_not_enabled"]);
    expect(await failure(reviewer().request("POST", "/admin/emergency/reviews/er-1/review", { body: { decision: "justified" } })))
      .toEqual([409, "not_pending"]);
  });

  it("justified keeps the capability, every new break-glass session lands in the queue, and no patient data is in it", async () => {
    await reviewer().request("POST", "/admin/emergency/reviews/er-2/review", { body: { decision: "justified" } });
    expect((await as(DOCTOR_TOKEN).request<StaffMe>("GET", "/me")).emergency_enabled).toBe(true);
    await as(DOCTOR_TOKEN).request("POST", "/emergency/access", { body: { health_id: MOCK_HEALTH_ID, reason: "Synthetic reason", facility: "Synthetic clinic" } });
    const queue = await reviewer().request<EmergencyReview[]>("GET", "/admin/emergency/reviews");
    expect(queue[0]).toMatchObject({ status: "review_pending", doctor_id: MOCK_DOCTOR_ID, reason: "Synthetic reason" });
    const text = JSON.stringify(queue);
    for (const leak of [MOCK_PATIENT_ID, MOCK_HEALTH_ID, "SYNTH-DRUG-003"]) expect(text).not.toContain(leak);
    expect(await failure(reviewer().request("POST", "/admin/emergency/reviews/er-2/review", { body: { decision: "maybe" } }))).toEqual([409, "not_pending"]);
    expect(await failure(admin().request("GET", "/admin/emergency/reviews"))).toEqual([403, "role_not_allowed"]);
  });
});

describe("admin: credentials, catalog, audit, metrics", () => {
  const pendingList = () => admin().request<CredentialReview[]>("GET", "/credentials?status=pending");

  it("approves a pending BMDC credential, and the doctor becomes verified", async () => {
    const [c] = await pendingList();
    expect(c).toMatchObject({ user_id: MOCK_SUBMITTED_DOCTOR_ID, number: "SYNTH-BMDC-0042", status: "pending" });
    expect(await admin().request("POST", `/credentials/${c.id}/approve`)).toEqual({ user_id: MOCK_SUBMITTED_DOCTOR_ID, status: "verified" });
    expect(await pendingList()).toEqual([]);
    expect(await failure(admin().request("POST", `/credentials/${c.id}/approve`))).toEqual([404, "not_found"]);
  });

  it("rejects only with a reason, and the doctor may submit again", async () => {
    const [c] = await pendingList();
    expect(await failure(admin().request("POST", `/credentials/${c.id}/reject`, { body: {} }))).toEqual([422, "reason_required"]);
    await admin().request("POST", `/credentials/${c.id}/reject`, { body: { reason: "Number does not match" } });
    expect(await pendingList()).toEqual([]);
    const doctor = createClient(transport, () => `${btoa(JSON.stringify({ alg: "none" }))}.${btoa(JSON.stringify({ sub: MOCK_SUBMITTED_DOCTOR_ID, role: "doctor" }))}.t`);
    await doctor.request("POST", "/credentials", { body: { type: "BMDC", number: "SYNTH-BMDC-0043" } });
    expect((await pendingList())[0].number).toBe("SYNTH-BMDC-0043");
  });

  it("suspends a doctor with a reason: every active consent is suspended and their next read is refused", async () => {
    expect(await failure(admin().request("POST", `/admin/users/${MOCK_DOCTOR_ID}/suspend`, { body: { reason: "" } }))).toEqual([422, "reason_required"]);
    await as(DOCTOR_TOKEN).request("GET", `/patients/${MOCK_PATIENT_ID}/summary`); // allowed before
    await admin().request("POST", `/admin/users/${MOCK_DOCTOR_ID}/suspend`, { body: { reason: "Investigation" } });
    expect((await as(PATIENT_TOKEN).request<DoctorConsent[]>("GET", "/consents")).find((c) => c.id === "c-active")!.status).toBe("suspended");
    expect(await failure(as(DOCTOR_TOKEN).request("GET", `/patients/${MOCK_PATIENT_ID}/summary`))).toEqual([403, "consent_required"]);
    expect((await as(DOCTOR_TOKEN).request<StaffMe>("GET", "/me")).status).toBe("suspended");
  });

  it("queues a CSV catalog import and refuses anything else", async () => {
    expect(await failure(admin().request("POST", "/catalog/import", { body: new FormData() }))).toEqual([422, "invalid_file"]);
    expect(await failure(admin().request("POST", "/catalog/import", { body: csv("catalog.xlsx") }))).toEqual([422, "invalid_file"]);
    expect(await failure(admin().request("POST", "/catalog/import", { body: csv("empty.csv", "") }))).toEqual([422, "invalid_file"]);
    expect(await admin().request<CatalogImport>("POST", "/catalog/import", { body: csv() })).toMatchObject({ status: "queued", file_name: "synthetic.csv" });
  });

  it("shows an intact, linked hash chain with metadata only: no names, IP, device, ids or free text", async () => {
    await as(DOCTOR_TOKEN).request("POST", "/emergency/access", { body: { health_id: MOCK_HEALTH_ID, reason: "Free-text reason", facility: "Synthetic clinic" } });
    await reviewer().request("POST", "/rules/SYNTH-EM-0001-v1/approve");
    const page = await admin().request<AuditPage>("GET", "/audit");
    expect(page.chain).toMatchObject({ status: "intact", first_broken_id: null });
    expect(page.chain.entries_checked).toBe(page.entries.length);
    page.entries.forEach((e, i) => { if (i + 1 < page.entries.length) expect(e.prev_hash).toBe(page.entries[i + 1].entry_hash); });
    expect(page.entries.at(-1)!.prev_hash).toBe("0".repeat(64));
    const keys = new Set(page.entries.flatMap((e) => Object.keys(e)));
    for (const k of ["actor_name", "actor_id", "patient_id", "ip", "device_id", "user_agent"]) expect(keys.has(k)).toBe(false);
    const text = JSON.stringify(page);
    for (const leak of ["Free-text reason", "সিনথেটিক", MOCK_PATIENT_ID, MOCK_DOCTOR_ID, MOCK_HEALTH_ID]) expect(text).not.toContain(leak);
    expect(page.entries.find((e) => e.action === "emergency.access")!.reason).toBe("free_text_hidden");
    expect(page.entries.find((e) => e.action === "rule.approve")).toMatchObject({ actor_role: "clinical_reviewer", result: "allow" });
  });

  it("filters the audit log on the server", async () => {
    const deny = await admin().request<AuditPage>("GET", "/audit?result=deny");
    expect(deny.entries.length).toBeGreaterThan(0);
    expect(deny.entries.every((e) => e.result === "deny")).toBe(true);
    const doctors = await admin().request<AuditPage>("GET", "/audit?role=doctor&action=timeline");
    expect(doctors.entries.every((e) => e.actor_role === "doctor" && e.action.startsWith("timeline"))).toBe(true);
  });

  it("reads the worker metrics (BUILT shape): documents per status and the worker counts", async () => {
    const m = await admin().request<WorkerMetrics>("GET", "/internal/metrics");
    expect(Object.keys(m.documents).sort()).toEqual(["extracting", "extraction_failed", "needs_review", "rejected", "uploaded", "verified"]);
    expect(m.documents.needs_review).toBeGreaterThan(0);
    expect(m.worker.lease_expired).toBe(1);
  });

  it("only a verified admin reaches these routes", async () => {
    for (const token of [REVIEWER_TOKEN, DOCTOR_TOKEN, PATIENT_TOKEN, VERIFIER_TOKEN]) {
      for (const [method, path] of [["GET", "/credentials"], ["GET", "/audit"], ["GET", "/internal/metrics"], ["POST", "/credentials/cred-66666666/approve"],
        [`POST`, `/admin/users/${MOCK_DOCTOR_ID}/suspend`]] as const) {
        expect(await failure(as(token).request(method, path, { body: { reason: "x" } }))).toEqual([403, "role_not_allowed"]);
      }
      expect(await failure(as(token).request("POST", "/catalog/import", { body: csv() }))).toEqual([403, "role_not_allowed"]);
    }
  });
});

describe("console roles never reach a patient's record", () => {
  it.each([["clinical reviewer", REVIEWER_TOKEN], ["admin", ADMIN_TOKEN]])("the %s is refused every patient read and write", async (_, token) => {
    const client = as(token);
    const calls: Array<[method: "GET" | "POST", path: string]> = [
      ["GET", `/patients/${MOCK_PATIENT_ID}/timeline`], ["GET", `/patients/${MOCK_PATIENT_ID}/documents`], ["GET", `/patients/${MOCK_PATIENT_ID}/summary`],
      ["GET", `/patients/${MOCK_PATIENT_ID}/search?q=SYNTH`], ["GET", `/patients/${MOCK_PATIENT_ID}/safety-alerts`], ["GET", "/documents/d-review"],
      ["GET", "/documents/d-review/images/1"], ["GET", "/documents/d-review/extraction"], ["GET", "/consents"], ["GET", "/me/access-history"],
      ["GET", "/vitals"], ["GET", "/reminders"], ["GET", "/me/emergency-profile"], ["POST", `/patients/${MOCK_PATIENT_ID}/documents`],
      ["POST", "/emergency/access"], ["POST", "/consents/requests"],
    ];
    for (const [method, path] of calls) {
      const [status] = await failure(client.request(method, path, { body: { health_id: MOCK_HEALTH_ID, reason: "x", facility: "y" } }));
      expect([401, 403], `${method} ${path}`).toContain(status);
    }
  });
});
