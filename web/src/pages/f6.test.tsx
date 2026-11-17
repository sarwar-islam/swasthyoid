import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, createClient, type ApiRequest, type Transport } from "../api/client";
import { MOCK_CODE, MOCK_HEALTH_ID, MOCK_PATIENT_ID, mockTransport } from "../api/mock";
import type { AccessEntry, DoctorConsent, DoctorQrConsent, PatientNotification, QrConsentRequest, VitalThresholds } from "../api/types";
import { axeViolations, CAREGIVER_TOKEN, DOCTOR_TOKEN, PATIENT_TOKEN, renderApp, VERIFIER_TOKEN } from "../test-utils";

// F6: consent by QR, the patient's inbox and per-patient vital thresholds. API rules are called straight on the mock (around
// the UI); screens are checked in Bangla and English with axe. No network.
let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => { fetchSpy = vi.spyOn(globalThis, "fetch"); });
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled();
  fetchSpy.mockRestore();
  vi.unstubAllEnvs();
  vi.useRealTimers();
  cleanup();
  localStorage.clear();
});

const client = (transport: Transport, token: string) => createClient(transport, () => token);
async function failure(call: Promise<unknown>): Promise<[number, string]> {
  try {
    await call;
  } catch (e) {
    if (e instanceof ApiError) return [e.status, e.code];
    throw e;
  }
  throw new Error("expected the API to refuse");
}
const qrRequest = (transport: Transport, categories = ["timeline", "safety"]) =>
  client(transport, DOCTOR_TOKEN).request<DoctorQrConsent>("POST", "/consents/requests", { body: { health_id: MOCK_HEALTH_ID, categories, method: "qr" } });
/** A doctor with an active consent by the code read out (the BUILT flow). */
async function openConsent(transport: Transport, categories: string[]) {
  const doctor = client(transport, DOCTOR_TOKEN);
  const c = await doctor.request<DoctorConsent>("POST", "/consents/requests", { body: { health_id: MOCK_HEALTH_ID, categories } });
  return doctor.request<DoctorConsent>("POST", `/consents/requests/${c.id}/confirm`, { body: { code: MOCK_CODE } });
}

describe("consent by QR (API)", () => {
  it("only the named patient approves, once, in their own app; no SMS code can confirm it", async () => {
    const t = mockTransport();
    const req = await qrRequest(t);
    expect(req.status).toBe("pending");
    expect(req.qr.short_code).toMatch(/^[A-Z2-9]{8}$/);
    const doctor = client(t, DOCTOR_TOKEN);
    expect(await failure(doctor.request("POST", `/consents/requests/${req.id}/confirm`, { body: { code: MOCK_CODE } }))).toEqual([403, "invalid_code"]);
    // anyone but the patient: the same 404 or a role refusal, never the request
    expect(await failure(client(t, CAREGIVER_TOKEN).request("GET", `/consents/qr/${req.qr.token}`))).toEqual([403, "role_not_allowed"]);
    expect(await failure(client(t, VERIFIER_TOKEN).request("POST", `/consents/qr/${req.qr.token}/approve`))).toEqual([403, "role_not_allowed"]);
    expect(await failure(doctor.request("POST", `/consents/qr/${req.qr.token}/approve`))).toEqual([403, "role_not_allowed"]);
    const patient = client(t, PATIENT_TOKEN);
    expect(await failure(patient.request("GET", "/consents/qr/NOSUCHCODE"))).toEqual([404, "not_found"]);
    // the short code, typed in any case, finds the same request
    const seen = await patient.request<QrConsentRequest>("GET", `/consents/qr/${req.qr.short_code.toLowerCase()}`);
    expect(seen).toMatchObject({ consent_id: req.id, status: "pending", categories: ["timeline", "safety"] });
    expect((await patient.request<QrConsentRequest>("POST", `/consents/qr/${req.qr.token}/approve`)).status).toBe("active");
    expect(await failure(patient.request("POST", `/consents/qr/${req.qr.token}/approve`))).toEqual([404, "not_found"]); // used
    expect((await doctor.request<DoctorConsent>("GET", `/consents/requests/${req.id}`)).status).toBe("active");
    const history = await patient.request<AccessEntry[]>("GET", "/me/access-history");
    expect(history[0]).toMatchObject({ action: "consent.qr.approve", consent_id: req.id });
  });

  it("expires with the OTP lifetime, and a decline leaves the record closed", async () => {
    const t = mockTransport();
    const late = await qrRequest(t);
    vi.useFakeTimers({ now: Date.now() + 5 * 60_000 + 1000 });
    const patient = client(t, PATIENT_TOKEN);
    expect((await patient.request<QrConsentRequest>("GET", `/consents/qr/${late.qr.token}`)).status).toBe("expired");
    expect(await failure(patient.request("POST", `/consents/qr/${late.qr.token}/approve`))).toEqual([404, "not_found"]);
    vi.useRealTimers();
    const req = await qrRequest(t);
    expect((await patient.request<QrConsentRequest>("POST", `/consents/qr/${req.qr.short_code}/decline`)).status).toBe("declined");
    expect((await client(t, DOCTOR_TOKEN).request<DoctorConsent>("GET", `/consents/requests/${req.id}`)).status).toBe("declined");
  });
});

describe("notifications (API)", () => {
  it("are the patient's own; break-glass notices exist only with M10 and always reach the patient", async () => {
    const t = mockTransport();
    const patient = client(t, PATIENT_TOKEN);
    expect((await patient.request<PatientNotification[]>("GET", "/notifications")).map((n) => n.kind).sort()).toEqual(["caregiver_request", "consent_request"]);
    expect(await failure(client(t, DOCTOR_TOKEN).request("GET", "/notifications"))).toEqual([403, "role_not_allowed"]);
    expect(await failure(client(t, CAREGIVER_TOKEN).request("GET", "/notifications"))).toEqual([403, "role_not_allowed"]);

    vi.stubEnv("VITE_FEATURE_EMERGENCY_ACCESS", "1");
    const m10 = mockTransport();
    await client(m10, DOCTOR_TOKEN).request("POST", "/emergency/access",
      { body: { health_id: MOCK_HEALTH_ID, reason: "SYNTH-REASON", facility: "Synthetic Clinic" } });
    const notes = await client(m10, PATIENT_TOKEN).request<PatientNotification[]>("GET", "/notifications");
    expect(notes[0]).toMatchObject({ kind: "emergency_access", facility: "Synthetic Clinic", read_at: null });
    expect(JSON.stringify(notes)).not.toContain("SYNTH-REASON"); // never the reason
    const read = await client(m10, PATIENT_TOKEN).request<PatientNotification>("POST", `/notifications/${notes[0].id}/read`);
    expect(read.read_at).not.toBeNull();
  });
});

describe("vital thresholds (API)", () => {
  it("need a consent covering safety, keep REVIEWER-PENDING defaults, and refuse unknown fields and stale versions", async () => {
    const t = mockTransport();
    const doctor = client(t, DOCTOR_TOKEN);
    const path = `/patients/${MOCK_PATIENT_ID}/vital-thresholds`;
    await client(t, PATIENT_TOKEN).request("POST", "/consents/c-active/revoke"); // the seeded consent of this doctor
    expect(await failure(doctor.request("GET", path))).toEqual([403, "consent_required"]);
    await openConsent(t, ["timeline"]);
    expect(await failure(doctor.request("GET", path))).toEqual([403, "category_not_allowed"]);
    expect(await failure(client(t, PATIENT_TOKEN).request("PUT", path, { body: { version: 1, overrides: {} } }))).toEqual([403, "role_not_allowed"]);
    await openConsent(t, ["timeline", "safety"]);
    const th = await doctor.request<VitalThresholds>("GET", path);
    expect(th.fields.every((f) => f.default_value === null && f.label.status === "REVIEWER-PENDING")).toBe(true);
    const key = th.fields[0].key;
    expect(await failure(doctor.request("PUT", path, { body: { version: 1, overrides: { made_up: 1 } } }))).toEqual([422, "invalid_threshold"]);
    expect(await failure(doctor.request("PUT", path, { body: { version: 1, overrides: { [key]: "x" } } }))).toEqual([422, "invalid_threshold"]);
    const next = await doctor.request<VitalThresholds>("PUT", path, { body: { version: 1, overrides: { [key]: 150 } } });
    expect(next).toMatchObject({ version: 2, updated_by_name: expect.any(String) });
    expect(next.fields[0].override_value).toBe(150);
    expect(await failure(doctor.request("PUT", path, { body: { version: 1, overrides: { [key]: null } } }))).toEqual([409, "version_conflict"]);
    const history = await client(t, PATIENT_TOKEN).request<AccessEntry[]>("GET", "/me/access-history");
    expect(history[0]).toMatchObject({ action: "vital_thresholds.update", result: "allow" });
  });
});

describe("F6 screens", () => {
  it("doctor: a QR request shows the QR and short code, then opens the record once the patient approves", async () => {
    const inner = mockTransport();
    const seen: ApiRequest[] = [];
    const transport: Transport = (r) => { seen.push(r); return inner(r); };
    const { container } = renderApp("/doctor", { lang: "en", token: DOCTOR_TOKEN, transport });
    fireEvent.change(await screen.findByLabelText("Patient's Health ID"), { target: { value: MOCK_HEALTH_ID } });
    fireEvent.click(screen.getByLabelText("QR on this screen, approved in the patient's own app"));
    await waitFor(() => expect((screen.getByRole("button", { name: "Send consent request" }) as HTMLButtonElement).disabled).toBe(false));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(screen.getByRole("button", { name: "Send consent request" }));
    expect(await screen.findByRole("img", { name: "QR code for this consent request" })).toBeTruthy();
    const req = seen.find((r) => r.path === "/consents/requests")!;
    expect(req.body).toMatchObject({ method: "qr" });
    expect(screen.getByText("Waiting for the patient…")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
    const qr = (await qrOf(inner));
    await client(inner, PATIENT_TOKEN).request("POST", `/consents/qr/${qr}/approve`);
    await act(() => vi.advanceTimersByTimeAsync(3500));
    expect(await screen.findByRole("heading", { level: 1, name: "Patient record" })).toBeTruthy();
  });

  it("patient: the QR link shows who asks and for what, and approving says so", async () => {
    const t = mockTransport();
    const req = await qrRequest(t);
    for (const lang of ["bn", "en"] as const) {
      const { container } = renderApp(`/patient/consent/qr/${req.qr.token}`, { lang, signedIn: true, transport: t });
      await screen.findByRole("button", { name: lang === "en" ? "Allow" : "অনুমতি দিন" });
      expect(await axeViolations(container)).toEqual([]);
      cleanup();
    }
    renderApp(`/patient/consent/qr/${req.qr.token}`, { lang: "en", signedIn: true, transport: t });
    expect(await screen.findByText("Can see: timeline, safety information")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Allow" }));
    expect(await screen.findByText("Access allowed. You can stop it at any time on the Consent page.")).toBeTruthy();
    cleanup();
    renderApp(`/patient/consent/qr/${req.qr.token}`, { lang: "en", signedIn: true, transport: t }); // used: closed
    expect(await screen.findByText(/This request is no longer open/)).toBeTruthy();
  });

  it("patient: the short code typed on the Consent page opens the same request; a QR link survives signing in", async () => {
    const t = mockTransport();
    const req = await qrRequest(t);
    renderApp("/patient/consent", { lang: "en", signedIn: true, transport: t });
    expect(await screen.findByText(/asked by QR to see your record/)).toBeTruthy(); // not "the code from the SMS"
    expect(screen.getAllByText(/code from the SMS/)).toHaveLength(1); // the seeded code request only
    fireEvent.change(await screen.findByLabelText("Code shown on the doctor's screen"), { target: { value: req.qr.short_code.toLowerCase() } });
    fireEvent.click(screen.getByRole("button", { name: "Open request" }));
    expect(await screen.findByRole("button", { name: "Allow" })).toBeTruthy();
    cleanup();
    renderApp(`/patient/consent/qr/${req.qr.token}`, { lang: "en", transport: t });
    fireEvent.change(await screen.findByLabelText("Mobile number"), { target: { value: "+8801700000001" } });
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));
    fireEvent.change(await screen.findByLabelText("One-time code"), { target: { value: MOCK_CODE } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Doctor's request" })).toBeTruthy();
  });

  it("patient: the inbox lists notices, marks them read, and offers no way to switch security notices off", async () => {
    vi.stubEnv("VITE_FEATURE_EMERGENCY_ACCESS", "1");
    for (const lang of ["bn", "en"] as const) {
      const { container } = renderApp("/patient/inbox", { lang, signedIn: true });
      await screen.findAllByRole("button", { name: lang === "en" ? "Mark as read" : "পড়া হয়েছে" });
      expect(await axeViolations(container)).toEqual([]);
      cleanup();
    }
    renderApp("/patient", { lang: "en", signedIn: true });
    fireEvent.click(await screen.findByRole("link", { name: "New notifications: 3" }));
    expect(await screen.findByText(/Emergency access: .* opened your emergency card at Synthetic General Hospital\./)).toBeTruthy();
    expect(screen.getAllByText("Security notice. It can't be switched off.")).toHaveLength(2);
    expect(screen.queryByRole("switch")).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "Mark as read" })[0]);
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Mark as read" })).toHaveLength(2));
  });

  it("patient: an approved QR request and caregiver show as granted notices (B3)", async () => {
    const t = mockTransport();
    const req = await qrRequest(t);
    await client(t, PATIENT_TOKEN).request("POST", `/consents/qr/${req.qr.token}/approve`);
    const pending = (await client(t, PATIENT_TOKEN).request<{ id: string; purpose: string; status: string }[]>("GET", "/consents"))
      .find((c) => c.purpose === "CAREGIVER" && c.status === "pending")!;
    await client(t, PATIENT_TOKEN).request("POST", `/caregiver-authorizations/${pending.id}/approve`);
    for (const lang of ["bn", "en"] as const) {
      const { container } = renderApp("/patient/inbox", { lang, signedIn: true, transport: t });
      await screen.findAllByRole("button", { name: lang === "en" ? "Mark as read" : "পড়া হয়েছে" });
      if (lang === "en") {
        expect(screen.getByText(/With your permission, .* can now see your record \(timeline, safety information\)\./)).toBeTruthy();
        expect(screen.getByText(/With your permission, .* is now your caregiver/)).toBeTruthy();
      }
      expect(await axeViolations(container)).toEqual([]);
      cleanup();
    }
  });

  it("patient: confirming without the document's date says so in both languages (B4a contract)", async () => {
    for (const [lang, text] of [["en", "Enter the document's date. It can't be confirmed without one."],
                                ["bn", "নথির তারিখ লিখুন। তারিখ ছাড়া নিশ্চিত করা যাবে না।"]] as const) {
      const { container } = renderApp("/patient/documents/d-review", { lang, signedIn: true });
      const date = await waitFor(() => {
        const el = container.querySelector<HTMLInputElement>("#f-prescription_date");
        expect(el).not.toBeNull();
        return el!;
      });
      fireEvent.change(date, { target: { value: "" } });
      fireEvent.click(screen.getByRole("button", { name: lang === "en" ? "All correct, confirm" : "সব ঠিক আছে, নিশ্চিত করুন" }));
      expect((await screen.findByRole("alert")).textContent).toContain(text);
      expect(await axeViolations(container)).toEqual([]);
      cleanup();
    }
  });

  it("patient without M10: no break-glass notice", async () => {
    renderApp("/patient/inbox", { lang: "en", signedIn: true });
    await screen.findAllByRole("button", { name: "Mark as read" });
    expect(screen.queryByText(/Emergency access:/)).toBeNull();
  });

  it("doctor: thresholds tab only with safety; REVIEWER-PENDING defaults; a non-number never reaches the server", async () => {
    const inner = mockTransport();
    await openConsent(inner, ["timeline", "safety"]);
    const seen: ApiRequest[] = [];
    const transport: Transport = (r) => { seen.push(r); return inner(r); };
    // the workspace needs the consent remembered in this session: confirm it through the screen
    const { container } = renderApp("/doctor", { lang: "en", token: DOCTOR_TOKEN, transport });
    fireEvent.change(await screen.findByLabelText("Patient's Health ID"), { target: { value: MOCK_HEALTH_ID } });
    fireEvent.click(screen.getByLabelText("safety information"));
    await waitFor(() => expect((screen.getByRole("button", { name: "Send consent request" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Send consent request" }));
    fireEvent.change(await screen.findByLabelText("Code from the patient"), { target: { value: MOCK_CODE } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm with the code" }));
    fireEvent.click(await screen.findByRole("link", { name: "Vital thresholds" }));
    expect((await screen.findAllByText("Default: REVIEWER-PENDING")).length).toBeGreaterThan(0);
    expect(await axeViolations(container)).toEqual([]);
    const inputs = screen.getAllByLabelText(/Limit for this patient/);
    fireEvent.change(inputs[0], { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Save thresholds" }));
    expect(await screen.findByText("Enter a number, or leave it empty for the default.")).toBeTruthy();
    expect(seen.some((r) => r.method === "PUT")).toBe(false);
    fireEvent.change(inputs[0], { target: { value: "150" } });
    fireEvent.click(screen.getByRole("button", { name: "Save thresholds" }));
    expect(await screen.findByText("Saved as version 2.")).toBeTruthy();
    const body = seen.find((r) => r.method === "PUT")!.body as { version: number; overrides: Record<string, number | null> };
    expect(body.version).toBe(1);
    expect(Object.values(body.overrides)).toEqual([150, null, null]);
  });

  it.each([
    ["en", "Patient's Health ID", "safety information", "Send consent request", "Code from the patient", "Confirm with the code",
     "Vital thresholds", "No approved threshold rules yet.", "Save thresholds"],
    ["bn", "রোগীর Health ID", "নিরাপত্তা তথ্য", "সম্মতির অনুরোধ পাঠান", "রোগীর বলা কোড", "কোড দিয়ে নিশ্চিত করুন",
     "ভাইটাল সীমা", "এখনো কোনো অনুমোদিত সীমার নিয়ম নেই।", "সীমা সংরক্ষণ করুন"],
  ] as const)("doctor (%s): with no approved threshold rule the screen says so and offers no save", async (lang, hid, safety, send, code, confirm, tab, note, save) => {
    const inner = mockTransport();
    // B6: the server lists fields only from approved vital_threshold rules, and none is approved yet
    const transport: Transport = async (r) => {
      const res = await inner(r);
      return r.method === "GET" && r.path.endsWith("/vital-thresholds") ? { ...res, body: { ...(res.body as object), fields: [] } } : res;
    };
    const { container } = renderApp("/doctor", { lang, token: DOCTOR_TOKEN, transport });
    fireEvent.change(await screen.findByLabelText(hid), { target: { value: MOCK_HEALTH_ID } });
    fireEvent.click(screen.getByLabelText(safety));
    await waitFor(() => expect((screen.getByRole("button", { name: send }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: send }));
    fireEvent.change(await screen.findByLabelText(code), { target: { value: MOCK_CODE } });
    fireEvent.click(screen.getByRole("button", { name: confirm }));
    fireEvent.click(await screen.findByRole("link", { name: tab }));
    expect(await screen.findByText(new RegExp(`^${note}`))).toBeTruthy();
    expect(screen.queryByRole("button", { name: save })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("doctor: no thresholds tab without safety; Bangla screen passes axe", async () => {
    renderApp("/doctor", { lang: "bn", token: DOCTOR_TOKEN });
    fireEvent.change(await screen.findByLabelText("রোগীর Health ID"), { target: { value: MOCK_HEALTH_ID } });
    fireEvent.click(screen.getByRole("button", { name: "সম্মতির অনুরোধ পাঠান" }));
    fireEvent.change(await screen.findByLabelText("রোগীর বলা কোড"), { target: { value: MOCK_CODE } });
    fireEvent.click(screen.getByRole("button", { name: "কোড দিয়ে নিশ্চিত করুন" }));
    const tabs = await screen.findByRole("navigation", { name: "রেকর্ডের অংশ" });
    expect(tabs.textContent).not.toContain("ভাইটাল সীমা");
    expect(screen.queryByRole("link", { name: "ভাইটাল সীমা" })).toBeNull();
  });
});

/** The token of the newest QR request, as the patient's phone would read it from the QR. */
async function qrOf(transport: Transport): Promise<string> {
  const notes = await client(transport, PATIENT_TOKEN).request<PatientNotification[]>("GET", "/notifications");
  expect(notes[0].kind).toBe("consent_request");
  // the screen holds the token only inside the QR image; the test takes the short code shown beside it instead
  return screen.getByText(/^[A-Z2-9]{8}$/).textContent!;
}
