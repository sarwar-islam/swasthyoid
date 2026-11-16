import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiRequest, Transport } from "../api/client";
import { MOCK_CODE, MOCK_HEALTH_ID, MOCK_OTHERS, MOCK_VERIFIER_PHONE, mockTransport } from "../api/mock";
import { axeViolations, renderApp, VERIFIER_TOKEN } from "../test-utils";

// F4 screens: the verifier/CHW app and caregiver mode, in Bangla and English, on the in-memory mock (no network). jsdom has no
// layout engine and does not draw focus rings: the 375px, desktop and visible-focus checks happen in the browser pane.
let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => { fetchSpy = vi.spyOn(globalThis, "fetch"); });
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled();
  fetchSpy.mockRestore();
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
const { full, timeline: timelineOnly, revoked } = MOCK_OTHERS;

/** On the verifier start page: send the code to the mock patient's phone and enter `code`. */
async function startSession(code = MOCK_CODE) {
  type(await screen.findByLabelText("Patient's Health ID") && "Patient's Health ID", MOCK_HEALTH_ID);
  click("Send a code to the patient's phone");
  type(await screen.findByLabelText("Code from the patient") && "Code from the patient", code);
  click("Start with the code");
}

describe("verifier/CHW app", () => {
  it("a verifier signs in as staff and must enter the patient's code before any document opens", async () => {
    const { seen, transport } = spy();
    renderApp("/verifier/login", { lang: "en", transport });
    type("Mobile number", MOCK_VERIFIER_PHONE);
    click("Send code");
    type(await screen.findByLabelText("One-time code") && "One-time code", MOCK_CODE);
    click("Sign in");
    expect(await screen.findByRole("heading", { name: "Start with the patient present" })).toBeTruthy();
    expect((seen.find((r) => r.path === "/auth/otp/verify")!.body as { account: string }).account).toBe("staff");
    expect(screen.queryByRole("checkbox")).toBeNull(); // no tick-box stands in for the patient's code
    expect(screen.queryByLabelText("Page photos (one to ten, JPEG or PNG)")).toBeNull();

    await startSession("000000");
    expect((await screen.findByRole("alert")).textContent).toMatch("That code is wrong or has expired.");
    expect(screen.queryByRole("region", { name: "Current session" })).toBeNull();
    type("Code from the patient", MOCK_CODE);
    click("Start with the code");
    const bar = await screen.findByRole("region", { name: "Current session" });
    expect(within(bar).getByText(MOCK_HEALTH_ID)).toBeTruthy();
    expect(within(bar).getByText(/Session ends in/)).toBeTruthy();
    expect(screen.getByText(/REVIEWER-PENDING/)).toBeTruthy(); // the session length is a placeholder
    expect(screen.getByLabelText(/Page photos/)).toBeTruthy();
    // no request ever carried the code back, and no screen shows the code outside the mock-mode notice
    const confirm = seen.find((r) => r.path.endsWith("/confirm"))!;
    expect(seen.filter((r) => JSON.stringify(r.body ?? "").includes(MOCK_CODE)).map((r) => r.path)).toEqual(["/auth/otp/verify", confirm.path]);
  });

  it("the queue holds only unverified documents; the check has no way to the timeline", async () => {
    renderApp("/verifier", { lang: "en", token: VERIFIER_TOKEN });
    await startSession();
    await screen.findByRole("region", { name: "Current session" });
    fireEvent.click(screen.getByRole("link", { name: "Verification queue" }));
    expect(await screen.findByRole("region", { name: "Documents to check" })).toBeTruthy();
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Prescription|Lab report/ }).length).toBe(3));
    expect(screen.queryByText("Verified")).toBeNull();
    fireEvent.click(screen.getAllByRole("link", { name: /Prescription/ })[0]);
    expect(await screen.findByRole("heading", { name: "Check against the photo" })).toBeTruthy();
    click("All correct, confirm");
    expect(await screen.findByText("Confirmed. The details are now on the patient's timeline.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /timeline/i })).toBeNull();
  });

  it("ending the session closes the patient's pages", async () => {
    renderApp("/verifier", { lang: "en", token: VERIFIER_TOKEN });
    await startSession();
    await screen.findByRole("region", { name: "Current session" });
    click("End session");
    expect(await screen.findByRole("heading", { name: "Start with the patient present" })).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: "Verification queue" }));
    expect(await screen.findByText("First start a session with the patient's code.")).toBeTruthy();
  });

  it("only a verifier reaches the app; anyone else is sent to sign in", async () => {
    renderApp("/verifier/queue", { lang: "en", signedIn: true });
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
  });

  it.each(["bn", "en"] as const)("has no axe violations and keeps focus on the code field (%s)", async (lang) => {
    const { container } = renderApp("/verifier", { lang, token: VERIFIER_TOKEN });
    await screen.findByRole("heading", { level: 1 });
    expect(await axeViolations(container)).toEqual([]);
    const healthId = lang === "bn" ? "রোগীর Health ID" : "Patient's Health ID";
    type(healthId, MOCK_HEALTH_ID);
    click(lang === "bn" ? "রোগীর ফোনে কোড পাঠান" : "Send a code to the patient's phone");
    const code = await screen.findByLabelText(lang === "bn" ? "রোগীর বলা কোড" : "Code from the patient");
    expect(document.activeElement).toBe(code);
    expect(await axeViolations(container)).toEqual([]);
    type(lang === "bn" ? "রোগীর বলা কোড" : "Code from the patient", MOCK_CODE);
    click(lang === "bn" ? "কোড দিয়ে শুরু করুন" : "Start with the code");
    await screen.findByRole("region", { name: lang === "bn" ? "চলমান সেশন" : "Current session" });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("switches language in the session without losing it", async () => {
    renderApp("/verifier", { token: VERIFIER_TOKEN });
    expect(await screen.findByRole("heading", { name: "রোগীর উপস্থিতিতে কাজ শুরু" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "ভাষা বদলান: English" }));
    expect(screen.getByRole("heading", { name: "Start with the patient present" })).toBeTruthy();
    expect(document.documentElement.lang).toBe("en");
  });
});

describe("caregiver mode", () => {
  it("lists only the people I may act for now, and opens one with only the granted pages", async () => {
    renderApp("/patient/caregiving", { lang: "en", signedIn: true });
    expect(await screen.findByRole("link", { name: `Open ${full.name}'s record` })).toBeTruthy();
    expect(screen.getByRole("link", { name: `Open ${timelineOnly.name}'s record` })).toBeTruthy();
    expect(screen.queryByText(revoked.name)).toBeNull();
    expect(screen.queryByText(MOCK_OTHERS.pending.name)).toBeNull();
    fireEvent.click(screen.getByRole("link", { name: `Open ${timelineOnly.name}'s record` }));
    expect(await screen.findByRole("region", { name: `You are acting for ${timelineOnly.name}` })).toBeTruthy();
    const tabs = screen.getByRole("navigation", { name: "Record sections" });
    expect(within(tabs).getAllByRole("link").map((a) => a.textContent)).toEqual(["Timeline"]);
    expect(await screen.findByText("SYNTH-DRUG-101")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Source document" })).toBeNull(); // no view_documents, no source links
  });

  it("a page outside the scopes says so, and a revoked authorization opens nothing", async () => {
    renderApp(`/patient/for/${timelineOnly.id}/documents`, { lang: "en", signedIn: true });
    expect(await screen.findByText("The patient hasn't allowed this.")).toBeTruthy();
    cleanup();
    renderApp(`/patient/for/${revoked.id}`, { lang: "en", signedIn: true });
    expect(await screen.findByText("You have no active access to this patient's record now.")).toBeTruthy();
  });

  it("with full scopes: timeline, documents (photos only, no check) and upload for that patient", async () => {
    const { seen, transport } = spy();
    renderApp(`/patient/for/${full.id}`, { lang: "en", signedIn: true, transport });
    expect(await screen.findByText("SYNTH-DRUG-100")).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: "Documents" }));
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Prescription/ }).length).toBe(2));
    fireEvent.click(screen.getAllByRole("link", { name: /Prescription/ })[0]);
    expect(await screen.findByRole("heading", { name: /Document photos/ })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Check against the photo" })).toBeNull();
    expect(seen.some((r) => r.path.endsWith("/extraction"))).toBe(false);
    fireEvent.click(screen.getByRole("link", { name: "Upload for them" }));
    fireEvent.change(await screen.findByLabelText(/Page photos/), { target: { files: [new File(["x"], "page.png", { type: "image/png" })] } });
    click(/Upload/);
    await screen.findByRole("heading", { name: /Document photos/ });
    expect(seen.some((r) => r.method === "POST" && r.path === `/patients/${full.id}/documents`)).toBe(true);
    expect(seen.some((r) => r.path === "/consents" || r.path === "/me/access-history")).toBe(false);
  });

  it("asks for access, then confirms with the code the patient reads out", async () => {
    const { seen, transport } = spy();
    renderApp("/patient/caregiving", { lang: "en", signedIn: true, transport });
    type(await screen.findByLabelText("Patient's Health ID") && "Patient's Health ID", revoked.health_id);
    fireEvent.click(screen.getByLabelText("view documents"));
    click("Send request");
    expect(await screen.findByText(/Request sent/)).toBeTruthy();
    expect(seen.find((r) => r.path === "/caregiver-authorizations" && r.method === "POST")!.body)
      .toEqual({ patient_health_id: revoked.health_id, scopes: ["view_timeline", "view_documents"], duration_days: 30 });
    type("Code from the patient", "000000");
    click("Confirm with the code");
    expect((await screen.findByRole("alert")).textContent).toMatch("That code is wrong or has expired.");
    type("Code from the patient", MOCK_CODE);
    click("Confirm with the code");
    expect(await screen.findByText("Access is now active.")).toBeTruthy();
    expect(await screen.findByRole("link", { name: `Open ${revoked.name}'s record` })).toBeTruthy();
  });

  it.each(["bn", "en"] as const)("caregiver pages have no axe violations (%s)", async (lang) => {
    const list = renderApp("/patient/caregiving", { lang, signedIn: true });
    await screen.findAllByRole("link", { name: new RegExp(full.name) });
    expect(await axeViolations(list.container)).toEqual([]);
    cleanup();
    const frame = renderApp(`/patient/for/${full.id}/timeline`, { lang, signedIn: true });
    await screen.findByText(/SYNTH-DRUG-(100|১০০)/); // Bangla shows Bangla digits
    expect(await axeViolations(frame.container)).toEqual([]);
    cleanup();
    const upload = renderApp(`/patient/for/${full.id}/upload`, { lang, signedIn: true });
    await screen.findAllByRole("link", { name: /Prescription|প্রেসক্রিপশন/ });
    expect(await axeViolations(upload.container)).toEqual([]);
  });

  it("the More page offers caregiver mode in Bangla", async () => {
    renderApp("/patient/more", { signedIn: true });
    expect(await screen.findByRole("link", { name: /যাঁদের দেখাশোনা করি/ })).toBeTruthy();
  });
});
