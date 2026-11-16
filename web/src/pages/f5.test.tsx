import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiRequest, Transport } from "../api/client";
import { MOCK_ADMIN_PHONE, MOCK_CODE, MOCK_REVIEWER_PHONE, mockTransport } from "../api/mock";
import { ADMIN_TOKEN, axeViolations, renderApp, REVIEWER_TOKEN } from "../test-utils";

// F5 console screens in Bangla and English on the in-memory mock (no network). Widths and focus rings are checked in the browser.
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
const asReviewer = (path: string, lang: "bn" | "en" = "en", transport?: Transport) => renderApp(path, { lang, token: REVIEWER_TOKEN, transport });
const asAdmin = (path: string, lang: "bn" | "en" = "en", transport?: Transport) => renderApp(path, { lang, token: ADMIN_TOKEN, transport });

async function signIn(phone: string) {
  type("Mobile number", phone);
  click("Send code");
  type(await screen.findByLabelText("One-time code") && "One-time code", MOCK_CODE);
  click("Sign in");
}

describe("console sign-in", () => {
  it("an admin lands on credential approvals and a reviewer on the rule registry", async () => {
    renderApp("/console/login", { lang: "en" });
    await signIn(MOCK_ADMIN_PHONE);
    expect(await screen.findByRole("heading", { level: 1, name: "Credential approvals" })).toBeTruthy();
    cleanup();
    renderApp("/console/login", { lang: "en" });
    await signIn(MOCK_REVIEWER_PHONE);
    expect(await screen.findByRole("heading", { level: 1, name: "Rule registry" })).toBeTruthy();
  });

  it("never offers self-registration for a console account", async () => {
    renderApp("/console/login", { lang: "en" });
    await signIn("+8801900000099");
    expect((await screen.findByRole("alert")).textContent).toMatch("Only an admin can create console accounts.");
    expect(screen.queryByLabelText("Full name")).toBeNull();
  });

  it("each role is kept to its own pages", async () => {
    asReviewer("/console/audit");
    expect(await screen.findByRole("heading", { level: 1, name: "Rule registry" })).toBeTruthy();
    cleanup();
    asAdmin("/console/rules");
    expect(await screen.findByRole("heading", { level: 1, name: "Credential approvals" })).toBeTruthy();
    cleanup();
    renderApp("/console", { lang: "en", signedIn: true }); // a patient
    expect(await screen.findByRole("heading", { level: 1, name: "Sign in" })).toBeTruthy();
  });
});

describe("clinical reviewer", () => {
  it("filters by type and marks every placeholder REVIEWER-PENDING", async () => {
    const { seen, transport } = spy();
    asReviewer("/console/rules", "en", transport);
    await screen.findAllByText("SYNTH-DDI-0001");
    fireEvent.change(screen.getByLabelText("Rule type"), { target: { value: "allergy" } });
    await waitFor(() => expect(screen.queryByText("SYNTH-DDI-0001")).toBeNull());
    expect(screen.getByText("SYNTH-ALG-0001")).toBeTruthy();
    expect(seen.some((r) => r.path === "/rules?type=allergy")).toBe(true);
    expect(document.querySelectorAll(".reviewer-pending").length).toBe(1); // even the approved placeholder is marked
  });

  it("drafts a rule from reviewer content only, then approves it", async () => {
    asReviewer("/console/rules");
    await screen.findAllByText("SYNTH-DDI-0001");
    click("Draft a new rule");
    await waitFor(() => expect(document.activeElement?.id).toBe("rule-form-title")); // focus moves to the form
    type("Type", "red_flag"); // the form's field ("Rule type" is the list filter)
    type("Definition (JSON)", "[1, 2]");
    type("Explanation (Bangla)", "[রিভিউয়ার-অনুমোদন বাকি] লেখা");
    type("Explanation (English)", "[REVIEWER-PENDING] text");
    click("Save draft");
    expect((await screen.findByRole("alert")).textContent).toBe("The definition must be a JSON object.");
    type("Definition (JSON)", '{ "placeholder": "REVIEWER-PENDING" }');
    click("Save draft");
    expect(await screen.findByText("Draft saved. It won't run until it is approved.")).toBeTruthy();
    const card = (await screen.findAllByText(/^RULE-/))[0].closest("li")!;
    fireEvent.click(within(card).getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("alertdialog");
    expect(document.activeElement?.textContent).toBe("No, go back"); // focus starts on the safe choice
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Rule approved. The earlier approved version no longer runs.")).toBeTruthy();
    expect(within((await screen.findAllByText(/^RULE-/))[0].closest("li")!).getByText("Approved")).toBeTruthy();
  });

  it("rejects a draft only with a reason", async () => {
    asReviewer("/console/rules");
    const card = (await screen.findAllByText("SYNTH-VT-0001"))[0].closest("li")!;
    fireEvent.click(within(card).getByRole("button", { name: "Reject" }));
    fireEvent.click(within(card).getByRole("button", { name: "Reject" }));
    expect(within(card).getByRole("alert").textContent).toBe("Write a reason.");
    fireEvent.change(within(card).getByLabelText("Reason for rejecting"), { target: { value: "Placeholder values" } });
    fireEvent.click(within(card).getByRole("button", { name: "Reject" }));
    expect(await screen.findByText("Rejected because: Placeholder values")).toBeTruthy();
  });

  it("break-glass reviews exist only with the M10 flag; unjustified needs a note and suspends the doctor's capability", async () => {
    asReviewer("/console/reviews");
    expect(await screen.findByRole("heading", { level: 1, name: "Rule registry" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Break-glass reviews" })).toBeNull();
    cleanup();
    vi.stubEnv("VITE_FEATURE_EMERGENCY_ACCESS", "1");
    asReviewer("/console/reviews");
    const item = (await screen.findByText(/unconscious on arrival/)).closest("li")!;
    expect(within(item).getByText("Blood group, Allergies")).toBeTruthy(); // the field names, never the values
    fireEvent.click(within(item).getByRole("button", { name: "Unjustified" }));
    expect(within(item).getByRole("alert").textContent).toBe("Write a reason.");
    fireEvent.change(within(item).getByLabelText("Note"), { target: { value: "No emergency documented" } });
    fireEvent.click(within(item).getByRole("button", { name: "Unjustified" }));
    expect(await screen.findByText(/emergency access is suspended/)).toBeTruthy();
  });
});

describe("admin", () => {
  it("approves a pending BMDC credential after a confirmation, and suspends a doctor only with a reason", async () => {
    asAdmin("/console/credentials");
    const pending = (await screen.findByText("BMDC SYNTH-BMDC-0042")).closest("li")!;
    fireEvent.click(within(pending).getByRole("button", { name: "Approve" }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/registration is approved/)).toBeTruthy();
    expect(await screen.findByText("Nothing is waiting for approval.")).toBeTruthy();
    const verified = screen.getByText("BMDC SYNTH-BMDC-0001").closest("li")!;
    fireEvent.click(within(verified).getByRole("button", { name: "Suspend" }));
    fireEvent.click(within(verified).getByRole("button", { name: "Suspend" }));
    expect(within(verified).getByRole("alert").textContent).toBe("Write a reason.");
    fireEvent.change(within(verified).getByLabelText("Reason for suspending"), { target: { value: "Investigation" } });
    fireEvent.click(within(verified).getByRole("button", { name: "Suspend" }));
    expect(await screen.findByText(/is suspended, and so are all their active consents/)).toBeTruthy();
  });

  it("sends a CSV for catalog import under the licence warning, with no catalog data in the app", async () => {
    const { seen, transport } = spy();
    asAdmin("/console/catalog", "en", transport);
    expect(await screen.findByText(/source and licence aren't decided yet/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Send for import" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Catalog file (CSV)"), { target: { files: [new File(["generic\n"], "synthetic.csv", { type: "text/csv" })] } });
    click("Send for import");
    expect(await screen.findByText(/Received synthetic\.csv .* it is queued\./)).toBeTruthy();
    expect(seen.some((r) => r.method === "POST" && r.path === "/catalog/import")).toBe(true);
  });

  it("shows the audit chain status and metadata only, and filters on the server", async () => {
    const { seen, transport } = spy();
    asAdmin("/console/audit", "en", transport);
    expect(await screen.findByText(/Hash chain intact/)).toBeTruthy();
    const table = screen.getByRole("table", { name: "Audit entries, newest first" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(
      ["Time", "Role", "Who", "Action", "Purpose", "Result", "Reason", "Patient", "Previous → this hash"]);
    expect(table.textContent).not.toMatch(/সিনথেটিক|ডা\./); // no names
    type("Result", "deny");
    click("Show");
    await waitFor(() => expect(seen.some((r) => r.path === "/audit?result=deny")).toBe(true));
    await waitFor(() => expect(within(screen.getByRole("table")).getAllByRole("row").slice(1)
      .every((row) => within(row).getByText("Denied"))).toBe(true));
  });

  it("shows the worker metrics and the expired-lease alert", async () => {
    asAdmin("/console/metrics");
    expect((await screen.findByRole("alert")).textContent).toMatch("Expired leases: 1");
    expect(screen.getByText("Needs checking").nextElementSibling?.textContent).toMatch(/^\d+$/);
    click("Read again");
    expect(await screen.findByRole("heading", { name: "Worker" })).toBeTruthy();
  });
});

describe("console accessibility", () => {
  const pages: Array<[string, "admin" | "reviewer", RegExp]> = [
    ["/console/rules", "reviewer", /SYNTH-DDI-0001/], ["/console/reviews", "reviewer", /unconscious on arrival/],
    ["/console/credentials", "admin", /SYNTH-BMDC-0042/], ["/console/catalog", "admin", /CSV/], ["/console/audit", "admin", /SID|timeline|rule|assist|\d/],
    ["/console/metrics", "admin", /[0-9০-৯]/],
  ];
  it.each((["bn", "en"] as const).flatMap((lang) => pages.map(([path, role, ready]) => [lang, path, role, ready] as const)))(
    "%s %s has no axe violations", async (lang, path, role, ready) => {
      vi.stubEnv("VITE_FEATURE_EMERGENCY_ACCESS", "1");
      const { container } = (role === "admin" ? asAdmin : asReviewer)(path, lang);
      await screen.findByRole("heading", { level: 1 });
      await screen.findAllByText(ready); // the page's data is on screen
      expect(await axeViolations(container)).toEqual([]);
    });

  it("switches the console to English and back", async () => {
    asAdmin("/console/metrics", "bn");
    expect(await screen.findByRole("heading", { level: 1, name: "ওয়ার্কার মেট্রিক" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "ভাষা বদলান: English" }));
    expect(screen.getByRole("heading", { level: 1, name: "Worker metrics" })).toBeTruthy();
    expect(document.documentElement.lang).toBe("en");
  });
});
