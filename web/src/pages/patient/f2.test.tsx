import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiRequest, Transport } from "../../api/client";
import { MOCK_RED_FLAG, mockTransport } from "../../api/mock";
import { axeViolations, renderApp } from "../../test-utils";

// jsdom has no layout engine, so screen-width behaviour (375px and desktop) is checked in the browser, not here.
let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, "fetch"); // every F2 flow must run on the in-memory mock: zero network requests
});
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
  const transport: Transport = (r) => {
    seen.push(r);
    return inner(r);
  };
  return { seen, transport };
}
const type = (label: RegExp | string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: RegExp | string) => fireEvent.click(screen.getByRole("button", { name }));
const open = (path: string, lang: "bn" | "en" = "en", transport?: Transport) => renderApp(path, { lang, signedIn: true, transport });
const NEVER_SAFE = /you are safe|you're safe|আপনি নিরাপদ/i;

describe("More menu", () => {
  it("lists the health tools; the emergency profile only when M10's flag is on", async () => {
    open("/patient/more");
    const names = screen.getAllByRole("link").map((a) => a.textContent);
    expect(names.filter((n) => /Home vitals|Reminders|Feeling unwell|First aid|Emergency card/.test(n ?? ""))).toHaveLength(5);
    expect(screen.queryByText("Emergency profile")).toBeNull();
    cleanup();
    vi.stubEnv("VITE_FEATURE_EMERGENCY_ACCESS", "1");
    open("/patient/more");
    expect(screen.getByText("Emergency profile")).toBeTruthy();
  });

  it("the emergency-profile page does not exist while the flag is off", async () => {
    open("/patient/emergency-profile");
    expect((await screen.findAllByRole("heading", { level: 1 }))[0].textContent).not.toBe("Emergency profile");
  });
});

describe("M13 home vitals", () => {
  it("a BP reading typed in Bangla digits is sent in ASCII, saved as patient-reported, and never called safe", async () => {
    const { seen, transport } = spy();
    open("/patient/vitals", "bn", transport);
    type("উপরের সংখ্যা (সিস্টোলিক)", "১২৮");
    type("নিচের সংখ্যা (ডায়াস্টোলিক)", "৮২");
    click("সংরক্ষণ করুন");
    const status = await screen.findByText("সংরক্ষিত হয়েছে।");
    expect(within(status.closest("[role=status]")!).getByText("রোগীর নিজের দেওয়া · যাচাই হয়নি")).toBeTruthy();
    expect(screen.getByText(/অনুমোদিত নিয়ম এখনো নেই/)).toBeTruthy();
    const body = seen.find((r) => r.method === "POST" && r.path === "/vitals")!.body as Record<string, string>;
    expect([body.vital_type, body.value, body.unit, body.context]).toEqual(["bp", "128/82", "mmHg", "home"]);
    expect(document.body.textContent).not.toMatch(NEVER_SAFE);
  });

  it("a critical reading shows the reviewed escalation message (pending here) with the 999 call and the emergency card", async () => {
    open("/patient/vitals");
    type("Top number (systolic)", "180");
    type("Bottom number (diastolic)", "120");
    click("Save");
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Urgent alert")).toBeTruthy();
    expect(within(alert).getByText(/\[REVIEWER-PENDING\] Approved escalation message goes here./)).toBeTruthy();
    expect(within(alert).getByRole("link", { name: "Call 999" }).getAttribute("href")).toBe("tel:999");
    expect(within(alert).getByRole("link", { name: "Open the emergency card" }).getAttribute("href")).toBe("/patient/emergency");
    expect(document.body.textContent).not.toMatch(NEVER_SAFE);
  });

  it("an implausible value needs confirmation before it is saved, and the confirmation is sent", async () => {
    const { seen, transport } = spy();
    open("/patient/vitals", "en", transport);
    type("Top number (systolic)", "80"); // top not above bottom: the mock calls it implausible, not critical
    type("Bottom number (diastolic)", "90");
    click("Save");
    expect(await screen.findByText("This value looks unusual. Check the number and the unit again.")).toBeTruthy();
    expect(seen.filter((r) => r.path === "/vitals" && r.method === "POST")).toHaveLength(1);
    click("Yes, the value is right");
    expect(await screen.findByText("Saved.")).toBeTruthy();
    expect((seen.filter((r) => r.path === "/vitals" && r.method === "POST").at(-1)!.body as { confirmed?: boolean }).confirmed).toBe(true);
  });

  it("glucose records its unit and context; non-numbers are refused before sending", async () => {
    const { seen, transport } = spy();
    open("/patient/vitals", "en", transport);
    fireEvent.click(screen.getByLabelText("Blood glucose"));
    type("Value", "six");
    click("Save");
    expect(screen.getByText("Enter numbers only.")).toBeTruthy();
    expect(seen.some((r) => r.method === "POST")).toBe(false);
    type("Value", "110");
    fireEvent.change(screen.getByLabelText("Unit"), { target: { value: "mg/dL" } });
    fireEvent.change(screen.getByLabelText("When you measured"), { target: { value: "post_meal" } });
    click("Save");
    await screen.findByText("Saved.");
    const body = seen.find((r) => r.method === "POST")!.body as Record<string, string>;
    expect([body.vital_type, body.value, body.unit, body.context]).toEqual(["glucose", "110", "mg/dL", "post_meal"]);
  });

  it("correcting a reading posts a correction and keeps the original in its history", async () => {
    const { seen, transport } = spy();
    open("/patient/vitals", "en", transport);
    const glucose = (await screen.findByText(/6\.1 mmol\/L/)).closest("li")!;
    fireEvent.click(within(glucose).getByRole("button", { name: "Correct" }));
    expect(screen.getByText(/You're correcting an earlier reading/)).toBeTruthy();
    type("Value", "6.4");
    click("Save");
    await screen.findByText("Saved.");
    expect(seen.some((r) => r.method === "POST" && r.path === "/vitals/v-3/correct")).toBe(true);
    const corrected = (await screen.findByText(/6\.4 mmol\/L/)).closest("li")!;
    expect(within(corrected).getByText("Corrected (version 2)")).toBeTruthy();
    expect(within(corrected).getByText(/6\.1 mmol\/L/)).toBeTruthy(); // the original, under "Earlier versions"
  });
});

describe("M7 triage, emergency card and first aid", () => {
  it("a red flag in the first message goes straight to the 999 card and asks nothing", async () => {
    open("/patient/help");
    type("Describe your problem", `synthetic text ${MOCK_RED_FLAG}`);
    click("Start");
    const card = await screen.findByRole("alert");
    expect(within(card).getByRole("link", { name: "Call 999" }).getAttribute("href")).toBe("tel:999");
    expect(screen.queryByRole("button", { name: "Yes" })).toBeNull();
  });

  it("otherwise asks the guide's questions, then suggests a department with the not-a-diagnosis notice", async () => {
    open("/patient/help");
    type("Describe your problem", "synthetic complaint");
    click("Start");
    click(await screen.findByRole("button", { name: "Yes" }) && "Yes");
    click(await screen.findByRole("button", { name: "No" }) && "No");
    expect(await screen.findByText("Where you could go")).toBeTruthy();
    expect(screen.getByText(/\[REVIEWER-PENDING\] Department from the approved guide table/)).toBeTruthy();
    expect(screen.getAllByText("This is guidance, not a diagnosis. If it feels like an emergency, call 999 now.").length).toBeGreaterThan(0);
  });

  it("fails safe: if the triage service errors, the emergency card and general advice show", async () => {
    const broken: Transport = async () => ({ status: 500, body: null });
    open("/patient/help", "en", broken);
    type("Describe your problem", "synthetic complaint");
    click("Start");
    const card = await screen.findByRole("alert");
    expect(within(card).getByText("Contact your nearest health facility.")).toBeTruthy();
  });

  it("first-aid cards and the emergency message are marked as waiting for the reviewer", () => {
    open("/patient/first-aid");
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.getAllByText(/\[REVIEWER-PENDING\]/).length).toBeGreaterThan(3);
    cleanup();
    open("/patient/emergency", "bn");
    expect(screen.getByText(/\[রিভিউয়ার-অনুমোদন বাকি\]/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "৯৯৯-এ ফোন করুন" })).toBeTruthy();
  });
});

describe("M8 reminders", () => {
  it("a proposed reminder runs only after the patient switches it on; then it can be logged and paused", async () => {
    const { seen, transport } = spy();
    open("/patient/reminders", "en", transport);
    const proposed = within((await screen.findByText("Suggested (needs your OK)")).closest("section")!);
    expect(proposed.getByText(/SYNTH-DRUG-003 · 1\+0\+1 \(as written\)/)).toBeTruthy();
    expect(proposed.queryByRole("button", { name: "Taken" })).toBeNull(); // nothing to log before it is on
    fireEvent.click(proposed.getByRole("button", { name: "Switch on" }));
    await waitFor(() => expect(within(screen.getByText("On").closest("section")!).getAllByRole("listitem")).toHaveLength(2));
    const on = within(screen.getByText("On").closest("section")!);
    fireEvent.click(on.getAllByRole("button", { name: "Taken" })[0]);
    await waitFor(() => expect(seen.some((r) => r.path.endsWith("/log"))).toBe(true));
    expect((seen.find((r) => r.path.endsWith("/log"))!.body as { action: string }).action).toBe("taken");
    expect(seen.find((r) => r.method === "PATCH")!.body).toEqual({ status: "active" });
  });

  it("stopping for good asks first", async () => {
    const { seen, transport } = spy();
    open("/patient/reminders", "en", transport);
    click((await screen.findAllByRole("button", { name: "Stop for good" }))[0] && "Resume");
    await waitFor(() => expect(seen.some((r) => r.method === "PATCH")).toBe(true));
    fireEvent.click(screen.getAllByRole("button", { name: "Stop for good" })[0]);
    expect(screen.getByRole("alertdialog").textContent).toMatch("Stop this reminder for good?");
    click("No, go back");
    expect(seen.filter((r) => r.method === "PATCH" && (r.body as { status: string }).status === "ended")).toHaveLength(0);
  });
});

describe("M10 emergency profile (flag on)", () => {
  beforeEach(() => vi.stubEnv("VITE_FEATURE_EMERGENCY_ACCESS", "1"));

  it("offers only verified fields, and saves the switch, chosen fields and contacts", async () => {
    const { seen, transport } = spy();
    open("/patient/emergency-profile", "en", transport);
    const blood = (await screen.findByLabelText(/Blood group/)) as HTMLInputElement;
    expect(blood.disabled).toBe(true); // nothing verified for it
    expect(screen.getByText("Profile off: the emergency card shows nothing.")).toBeTruthy();
    fireEvent.click(screen.getByRole("switch", { name: "Emergency profile on" }));
    fireEvent.click(screen.getByLabelText("Current medicines"));
    fireEvent.click(screen.getByLabelText("Emergency contacts"));
    click("Add another person");
    type("Name", "Synthetic Contact");
    type("Phone number", "+৮৮০১৭০০০০০০৪২");
    click("Save");
    expect(await screen.findByText("Emergency profile saved.")).toBeTruthy();
    expect(seen.find((r) => r.method === "PUT")!.body).toEqual({ enabled: true, fields: ["active_medications", "emergency_contacts"],
      contacts: [{ name: "Synthetic Contact", phone: "+8801700000042" }] });
    const preview = within(screen.getByText("What the emergency card shows").closest("section")!);
    expect(preview.getByText("SYNTH-DRUG-003")).toBeTruthy();
  });
});

describe("accessibility of every F2 page, in Bangla and in English", () => {
  const pages = ["/patient/more", "/patient/vitals", "/patient/help", "/patient/first-aid", "/patient/emergency", "/patient/reminders",
    "/patient/emergency-profile"];
  it.each(pages.flatMap((p) => [[p, "bn"], [p, "en"]]) as Array<[string, "bn" | "en"]>)("%s (%s) has no axe violations", async (path, lang) => {
    vi.stubEnv("VITE_FEATURE_EMERGENCY_ACCESS", "1");
    const { container } = open(path, lang);
    await screen.findAllByRole("heading", { level: 1 });
    await waitFor(() => expect(screen.queryByText(lang === "bn" ? "লোড হচ্ছে…" : "Loading…")).toBeNull());
    expect(await axeViolations(container)).toEqual([]);
  });
});
