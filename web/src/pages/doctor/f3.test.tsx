import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiRequest, Transport } from "../../api/client";
import { MOCK_CODE, MOCK_DOCTOR_PHONE, MOCK_HEALTH_ID, MOCK_PATIENT_ID, mockTransport } from "../../api/mock";
import { axeViolations, DOCTOR_TOKEN, PENDING_DOCTOR_TOKEN, renderApp } from "../../test-utils";
import { clock } from "./doctor";

// jsdom has no layout engine: the 375px and desktop checks happen in the browser. Every flow here runs on the in-memory mock.
let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => { fetchSpy = vi.spyOn(globalThis, "fetch"); });
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled();
  fetchSpy.mockRestore();
  vi.unstubAllEnvs();
  cleanup();
  localStorage.clear();
});

function spy() {
  const inner = mockTransport();
  const seen: ApiRequest[] = [];
  const transport: Transport = (r) => { seen.push(r); return inner(r); };
  return { seen, transport };
}
const type = (label: RegExp | string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: RegExp | string) => fireEvent.click(screen.getByRole("button", { name }));
const asDoctor = (path: string, lang: "bn" | "en" = "en", transport?: Transport, token = DOCTOR_TOKEN) =>
  renderApp(path, { lang, token, transport });

/** Request consent for the synthetic patient with these categories and confirm it with the code: lands in the workspace. */
async function openPatient(categories: Array<"Timeline" | "Documents" | "Safety information"> = ["Timeline", "Documents", "Safety information"]) {
  await screen.findByText("Request patient consent");
  type("Patient's Health ID", MOCK_HEALTH_ID.toLowerCase()); // case does not matter
  for (const c of ["Documents", "Safety information"] as const) if (categories.includes(c)) fireEvent.click(screen.getByLabelText(c.toLowerCase())); // English category labels are lowercase
  if (!categories.includes("Timeline")) fireEvent.click(screen.getByLabelText("timeline"));
  await waitFor(() => expect((screen.getByRole("button", { name: "Send consent request" }) as HTMLButtonElement).disabled).toBe(false));
  click("Send consent request");
  type(await screen.findByLabelText("Code from the patient") && "Code from the patient", MOCK_CODE);
  click("Confirm with the code");
  await screen.findByRole("region", { name: "Patient record" });
}

describe("M1 doctor sign-in and BMDC status", () => {
  it("a verified doctor signs in as staff and lands on Find patient with no status banner", async () => {
    const { seen, transport } = spy();
    renderApp("/doctor/login", { lang: "en", transport });
    type("Mobile number", MOCK_DOCTOR_PHONE);
    click("Send code");
    type(await screen.findByLabelText("One-time code") && "One-time code", MOCK_CODE);
    click("Sign in");
    expect(await screen.findByText("Request patient consent")).toBeTruthy();
    expect((seen.find((r) => r.path === "/auth/otp/verify")!.body as { account: string }).account).toBe("staff");
    await waitFor(() => expect(seen.some((r) => r.path === "/me")).toBe(true));
    expect(screen.queryByText(/registration is waiting|Submit your BMDC/)).toBeNull();
  });

  it("a new doctor registers with a name, sees why they can't request consent, and submits a BMDC number", async () => {
    const { seen, transport } = spy();
    renderApp("/doctor/login", { lang: "en", transport });
    type("Mobile number", "+8801900000099");
    click("Send code");
    type(await screen.findByLabelText("One-time code") && "One-time code", MOCK_CODE);
    click("Sign in");
    type(await screen.findByLabelText("Full name") && "Full name", "Dr. New Synthetic");
    expect(screen.queryByLabelText("Date of birth")).toBeNull(); // staff give a name only
    click("Send a new code with these details");
    type(await screen.findByLabelText("One-time code") && "One-time code", MOCK_CODE);
    click("Sign in");
    expect(await screen.findByText(/Submit your BMDC registration number/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Send consent request" }) as HTMLButtonElement).disabled).toBe(true);
    expect((seen.filter((r) => r.path === "/auth/otp/verify").at(-1)!.body as { staff: object }).staff).toEqual({ role: "doctor", name: "Dr. New Synthetic" });
    fireEvent.click(screen.getByRole("link", { name: "View registration" }));
    type(await screen.findByLabelText("BMDC registration number") && "BMDC registration number", "SYNTH-BMDC-0099");
    click("Submit for verification");
    expect(await screen.findByText("Submitted. An admin will verify it.")).toBeTruthy();
    expect(await screen.findByText("SYNTH-BMDC-0099")).toBeTruthy();
  });

  it("a pending doctor sees the banner and cannot request consent", async () => {
    asDoctor("/doctor", "bn", undefined, PENDING_DOCTOR_TOKEN);
    expect(await screen.findByText(/যাচাই না হওয়া পর্যন্ত রোগীর সম্মতি চাইতে পারবেন না/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /সম্মতির অনুরোধ পাঠান/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("a patient's session cannot open the doctor portal", () => {
    renderApp("/doctor", { lang: "en", signedIn: true });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Sign in");
  });
});

describe("M1/C1 consent request and the patient context bar", () => {
  it("refuses a malformed Health ID before sending, and a wrong code says so", async () => {
    const { seen, transport } = spy();
    asDoctor("/doctor", "en", transport);
    await screen.findByText("Request patient consent");
    await waitFor(() => expect((screen.getByRole("button", { name: "Send consent request" }) as HTMLButtonElement).disabled).toBe(false));
    type("Patient's Health ID", "SID-123");
    click("Send consent request");
    expect(screen.getByText("A Health ID is SID- followed by ten digits.")).toBeTruthy();
    expect(seen.some((r) => r.path === "/consents/requests")).toBe(false);
    type("Patient's Health ID", MOCK_HEALTH_ID);
    click("Send consent request");
    type(await screen.findByLabelText("Code from the patient") && "Code from the patient", "000000");
    click("Confirm with the code");
    expect((await screen.findByRole("alert")).textContent).toMatch("That code is wrong or has expired.");
  });

  it("after the patient's code, the bar shows the Health ID, the categories and the exact time left", async () => {
    const { seen, transport } = spy();
    asDoctor("/doctor", "en", transport);
    await openPatient(["Timeline", "Safety information"]);
    const bar = screen.getByRole("region", { name: "Patient record" });
    expect(within(bar).getByText(MOCK_HEALTH_ID)).toBeTruthy();
    expect(bar.textContent).toMatch("Allowed: timeline, safety information");
    expect(bar.textContent).toMatch(/Consent ends in 2[34]:\d\d:\d\d/);
    expect(seen.find((r) => r.path === "/consents/requests")!.body).toEqual({ health_id: MOCK_HEALTH_ID, categories: ["timeline", "safety"] });
  });

  it("the countdown is hours:minutes:seconds, in Bangla digits in Bangla", () => {
    expect(clock(3661, "en")).toBe("01:01:01");
    expect(clock(86399, "bn")).toBe("২৩:৫৯:৫৯");
    expect(clock(0, "en")).toBe("00:00:00");
  });
});

describe("M5 summary, timeline and search, filtered by consent", () => {
  it("shows the template mode, every section, clickable citations, and patient-reported vitals apart", async () => {
    asDoctor("/doctor", "en");
    await openPatient();
    expect(await screen.findByText(/Template summary: built straight from verified events, no AI/)).toBeTruthy();
    for (const s of ["Active medications", "Allergies", "Documented diagnoses", "Recent labs and trend", "Recent visits", "Pending follow-ups"]) {
      expect(screen.getByRole("heading", { name: s })).toBeTruthy();
    }
    const meds = screen.getByRole("heading", { name: "Active medications" }).closest("section")!;
    expect(within(meds).getByRole("link", { name: "Source event 1" }).getAttribute("href")).toBe(`/doctor/patients/${MOCK_PATIENT_ID}/timeline#event-e-med`);
    expect(screen.getByText(/SYNTH-TEST-A: 5.4 mg\/dL \(2026-09-15\) → 5.9 mg\/dL \(2026-11-01\)/)).toBeTruthy();
    const reported = screen.getByRole("heading", { name: "Reported by patient, not verified" }).closest("section")!;
    expect(within(reported).getByText(/130\/85 mmHg/)).toBeTruthy();
    expect(meds.textContent).not.toMatch(/mmHg/); // vitals never mix into verified sections
    expect(document.body.textContent).not.toMatch("150/95"); // the corrected reading is not summarised
  });

  it("a citation opens the timeline at that event", async () => {
    asDoctor("/doctor", "en");
    await openPatient();
    const meds = (await screen.findByRole("heading", { name: "Active medications" })).closest("section")!;
    fireEvent.click(within(meds).getByRole("link", { name: "Source event 1" }));
    await waitFor(() => expect(document.activeElement?.id).toBe("event-e-med"));
  });

  it("without the documents or safety categories, no source link and no alerts tab; the server refuses the alerts too", async () => {
    asDoctor("/doctor", "en");
    await openPatient(["Timeline"]);
    const tabs = within(screen.getByRole("navigation", { name: "Record sections" }));
    expect(tabs.getAllByRole("link").map((a) => a.textContent)).toEqual(["Summary", "Timeline", "Search"]);
    fireEvent.click(tabs.getByRole("link", { name: "Timeline" }));
    await screen.findAllByRole("article");
    expect(screen.queryByRole("link", { name: "View the source document" })).toBeNull();
  });

  it("with the documents category, a source link opens the photos, view only", async () => {
    asDoctor("/doctor", "en");
    await openPatient(["Timeline", "Documents"]);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Record sections" })).getByRole("link", { name: "Timeline" }));
    fireEvent.click((await screen.findAllByRole("link", { name: "View the source document" }))[0]);
    expect(await screen.findByText(/Document photos \(view only\)/)).toBeTruthy();
    expect(screen.queryByText("Check against the photo")).toBeNull(); // never the unverified extraction
  });

  it("search returns events inside the consent, linked to the timeline", async () => {
    asDoctor("/doctor", "en");
    await openPatient(["Timeline"]);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Record sections" })).getByRole("link", { name: "Search" }));
    type(await screen.findByLabelText("Search the record") && "Search the record", "synth-test");
    click("Search");
    const links = await screen.findAllByRole("link", { name: "View the event on the timeline" });
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      `/doctor/patients/${MOCK_PATIENT_ID}/timeline#event-e-lab-1`, `/doctor/patients/${MOCK_PATIENT_ID}/timeline#event-e-lab-2`]);
  });
});

describe("M6 safety alerts", () => {
  it("acknowledge works; override needs a reason, here and in the request", async () => {
    const { seen, transport } = spy();
    asDoctor("/doctor", "en", transport);
    await openPatient(["Timeline", "Safety information"]);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Record sections" })).getByRole("link", { name: "Safety alerts" }));
    expect(await screen.findByText("An alert is never a diagnosis, and no alert never means safe.")).toBeTruthy();
    const [first, second] = screen.getAllByRole("listitem").filter((li) => li.className.includes("alert-item"));
    expect(within(first).getByText("Major")).toBeTruthy();
    expect(within(first).getByText("SYNTH-DDI-0001")).toBeTruthy();
    expect(within(first).getByText(/\[REVIEWER-PENDING\]/)).toBeTruthy();
    expect(within(first).getAllByRole("link", { name: /Source event/ }).length).toBe(2);
    fireEvent.click(within(first).getByRole("button", { name: "Acknowledge" }));
    expect(await within(first).findByText("Acknowledged")).toBeTruthy();
    fireEvent.click(within(second).getByRole("button", { name: "Override with a reason" }));
    fireEvent.click(within(second).getByRole("button", { name: "Confirm override" }));
    expect(within(second).getByText("Write a reason to override.")).toBeTruthy();
    expect(seen.filter((r) => r.path.endsWith("/ack"))).toHaveLength(1); // nothing sent without a reason
    fireEvent.change(within(second).getByLabelText("Reason for the override (required)"), { target: { value: "Synthetic reason" } });
    fireEvent.click(within(second).getByRole("button", { name: "Confirm override" }));
    expect(await within(second).findByText("Overridden · reason: Synthetic reason")).toBeTruthy();
    expect(seen.filter((r) => r.path.endsWith("/ack")).map((r) => r.body)).toEqual([
      { action: "acknowledge" }, { action: "override", reason: "Synthetic reason" }]);
  });

  it("the Safety alerts menu lists alerts for open patients with the safety category", async () => {
    asDoctor("/doctor", "en");
    await openPatient(["Timeline", "Safety information"]);
    fireEvent.click(screen.getAllByRole("link", { name: "Safety alerts" })[0]);
    expect(await screen.findByRole("heading", { name: MOCK_HEALTH_ID })).toBeTruthy();
  });
});

describe("M10 break-glass", () => {
  it("does not exist while the flag is off", async () => {
    asDoctor("/doctor/emergency", "en");
    expect(await screen.findByText("Request patient consent")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Emergency access" })).toBeNull();
  });

  it("needs a reason and a facility, then shows only the time-boxed card", async () => {
    vi.stubEnv("VITE_FEATURE_EMERGENCY_ACCESS", "1");
    const { seen, transport } = spy();
    asDoctor("/doctor/emergency", "en", transport);
    type(await screen.findByLabelText("Patient's Health ID") && "Patient's Health ID", MOCK_HEALTH_ID);
    click("Open the emergency card");
    expect(screen.getByText("Write both a reason and a facility.")).toBeTruthy();
    expect(seen.some((r) => r.path === "/emergency/access")).toBe(false);
    type("Reason", "Synthetic emergency reason");
    type("Facility", "Synthetic Clinic");
    click("Open the emergency card");
    expect(await screen.findByText("The patient's emergency profile is off. There's nothing to show.")).toBeTruthy();
    expect(screen.getByText(/Session ends in 0[12]:\d\d:\d\d/)).toBeTruthy();
    expect(seen.find((r) => r.path === "/emergency/access")!.body).toEqual({ health_id: MOCK_HEALTH_ID, reason: "Synthetic emergency reason", facility: "Synthetic Clinic" });
    // B8c: the server cannot end a session early, so the button only closes the card and says so; the intro promises no
    // notice to the emergency contact (not built)
    expect(screen.queryByRole("button", { name: "End session" })).toBeNull();
    click("Close the card");
    expect(await screen.findByLabelText("Reason")).toBeTruthy();
    expect(screen.getByText(/Telling the emergency contact is not built yet\./)).toBeTruthy();
  });

  it("an earlier refusal does not stay on screen next to a new message (B8c)", async () => {
    vi.stubEnv("VITE_FEATURE_EMERGENCY_ACCESS", "1");
    const inner = mockTransport();
    const refusing: Transport = async (r) => (r.path === "/emergency/access"
      ? { status: 403, body: { code: "emergency_not_enabled", message: "x", details: {} } } : inner(r));
    asDoctor("/doctor/emergency", "en", refusing);
    type(await screen.findByLabelText("Patient's Health ID") && "Patient's Health ID", MOCK_HEALTH_ID);
    type("Reason", "Synthetic emergency reason");
    type("Facility", "Synthetic Clinic");
    click("Open the emergency card");
    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    type("Reason", " ");
    click("Open the emergency card");
    await waitFor(() => expect(screen.getAllByRole("alert").map((a) => a.textContent)).toEqual(["Write both a reason and a facility."]));
  });
});

describe("accessibility of the doctor portal, in Bangla and in English", () => {
  it.each([["bn"], ["en"]] as const)("login, find patient, every workspace section, alerts, registration and break-glass (%s)", async (lang) => {
    vi.stubEnv("VITE_FEATURE_EMERGENCY_ACCESS", "1");
    const login = renderApp("/doctor/login", { lang });
    expect(await axeViolations(login.container)).toEqual([]);
    cleanup();
    for (const path of ["/doctor/credentials", "/doctor/emergency", "/doctor/alerts"]) {
      const view = asDoctor(path, lang);
      await screen.findAllByRole("heading", { level: 1 });
      await waitFor(() => expect(screen.queryByRole("status", { name: "" })?.textContent ?? "").not.toMatch(/লোড হচ্ছে|Loading/));
      expect(await axeViolations(view.container), path).toEqual([]);
      cleanup();
    }
    const view = asDoctor("/doctor", "en"); // the shared flow helper speaks English; the language is switched after
    await openPatient();
    if (lang === "bn") fireEvent.click(screen.getByRole("button", { name: "Change language: বাংলা" }));
    for (const tab of lang === "bn" ? ["সারাংশ", "টাইমলাইন", "খুঁজুন", "নিরাপত্তা সতর্কতা"] : ["Summary", "Timeline", "Search", "Safety alerts"]) {
      fireEvent.click(within(screen.getByRole("navigation", { name: lang === "bn" ? "রেকর্ডের অংশ" : "Record sections" })).getByRole("link", { name: tab }));
      await waitFor(() => expect(screen.queryByText(lang === "bn" ? "লোড হচ্ছে…" : "Loading…")).toBeNull());
      expect(await axeViolations(view.container), tab).toEqual([]);
    }
  });
});
