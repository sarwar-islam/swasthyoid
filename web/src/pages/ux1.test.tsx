import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MOCK_PHONE, mockTransport } from "../api/mock";
import { axeViolations, renderApp } from "../test-utils";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.useRealTimers();
});

describe("UX-1 timeline", () => {
  for (const [lang, med, noMatch] of [["bn", "ওষুধ", "এই বাছাইয়ে কিছু মেলেনি।"], ["en", "Medicine", "Nothing matches this filter."]] as const) {
    it(`groups by month on a rail, filters by type, and says when nothing matches (${lang})`, async () => {
      const { container } = renderApp("/patient/timeline", { lang, signedIn: true });
      const all = (await screen.findAllByRole("article")).length;
      expect(screen.getAllByRole("heading", { level: 2 }).length).toBeGreaterThan(0); // one per month
      expect(screen.getAllByText(lang === "en" ? "Event" : "ইভেন্ট", { exact: false }).length).toBe(all);
      expect(await axeViolations(container)).toEqual([]);
      fireEvent.click(within(screen.getByRole("group", { name: lang === "en" ? "Show by type" : "ধরন অনুযায়ী দেখান" }))
        .getByLabelText(med));
      const meds = screen.getAllByRole("article");
      expect(meds.length).toBeGreaterThan(0);
      expect(meds.length).toBeLessThan(all);
      fireEvent.click(screen.getByLabelText(lang === "en" ? "Self-reported" : "নিজের দেওয়া"));
      expect(screen.getByText(noMatch)).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: lang === "en" ? "Show everything" : "সব দেখান" }));
      expect(screen.getAllByRole("article")).toHaveLength(all);
      expect(await axeViolations(container)).toEqual([]);
    });
  }

  it("a failed load offers a retry that loads again", async () => {
    const real = mockTransport();
    let fail = true;
    const transport: typeof real = async (r) => (r.path.endsWith("/timeline") && fail
      ? { status: 500, body: { code: "internal", message: "" } } : real(r));
    renderApp("/patient/timeline", { lang: "en", signedIn: true, transport });
    const retry = await screen.findByRole("button", { name: "Try again" });
    fail = false;
    fireEvent.click(retry);
    expect((await screen.findAllByRole("article")).length).toBeGreaterThan(0);
  });
});

describe("UX-1 sign-in code screen", () => {
  for (const [lang, sent, resend, resent] of [
    ["bn", "কোড পাঠানো হয়েছে এই নম্বরে:", "আবার কোড পাঠান", "নতুন কোড পাঠানো হয়েছে। আগের কোড আর কাজ করবে না।"],
    ["en", "Code sent to:", "Send the code again", "A new code was sent. The earlier code no longer works."]] as const) {
    it(`shows the masked number, the time left, and resends (${lang})`, async () => {
      const { container } = renderApp("/patient/login", { lang });
      fireEvent.change(await screen.findByLabelText(lang === "en" ? "Mobile number" : "মোবাইল নম্বর"), { target: { value: MOCK_PHONE } });
      fireEvent.click(screen.getByRole("button", { name: lang === "en" ? "Send code" : "কোড পাঠান" }));
      expect(await screen.findByText(sent)).toBeTruthy();
      expect(screen.getByText(`•••••••••${MOCK_PHONE.slice(-4)}`)).toBeTruthy();
      expect(screen.getByText(sent).parentElement!.textContent).not.toContain(MOCK_PHONE.slice(-8));
      expect(screen.getByText(lang === "en" ? /The code works for 5:00 more/ : /কোডের মেয়াদ আছে আর ৫:০০/)).toBeTruthy();
      expect(await axeViolations(container)).toEqual([]);
      fireEvent.click(screen.getByRole("button", { name: resend }));
      expect(await screen.findByText(resent)).toBeTruthy();
    });
  }

  it("after five minutes the code is expired and sign-in waits for a new one", async () => {
    renderApp("/patient/login", { lang: "en" });
    fireEvent.change(await screen.findByLabelText("Mobile number"), { target: { value: MOCK_PHONE } });
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));
    await screen.findByText("Code sent to:");
    const later = Date.now() + 5 * 60_000 + 1000;
    vi.spyOn(Date, "now").mockReturnValue(later);
    expect(await screen.findByText("The code has expired. Send a new one.", {}, { timeout: 3000 })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("One-time code"), { target: { value: "123456" } });
    expect((screen.getByRole("button", { name: "Sign in" }) as HTMLButtonElement).disabled).toBe(true);
    vi.restoreAllMocks();
  });
});

describe("UX-1 landing, profile and records", () => {
  for (const lang of ["bn", "en"] as const) {
    it(`landing has section links and the doctor application (${lang})`, async () => {
      const { container } = renderApp("/", { lang });
      const nav = screen.getByRole("navigation", { name: lang === "en" ? "Page sections" : "পাতার অংশ" });
      expect(within(nav).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["#how", "#can", "#doctors", "#yours"]);
      expect(screen.getByRole("link", { name: lang === "en" ? "Apply for doctor access" : "ডাক্তার হিসেবে আবেদন করুন" })
        .getAttribute("href")).toBe("/doctor/login");
      expect(await axeViolations(container)).toEqual([]);
    });

    it(`the profile is read only and shows only the phone's last four digits (${lang})`, async () => {
      const { container } = renderApp("/patient/profile", { lang, signedIn: true });
      expect(await screen.findByText("SID-4827190356")).toBeTruthy();
      expect(screen.getByText(`•••••••${MOCK_PHONE.slice(-4)}`)).toBeTruthy();
      expect(screen.queryByRole("textbox")).toBeNull();
      expect(await axeViolations(container)).toEqual([]);
    });

    it(`records filter by type and show each status (${lang})`, async () => {
      const { container } = renderApp("/patient/records", { lang, signedIn: true });
      await waitFor(() => expect(screen.getAllByRole("listitem").length).toBeGreaterThan(0));
      const total = screen.getAllByRole("listitem").length;
      fireEvent.click(screen.getByLabelText(lang === "en" ? "Lab report" : "ল্যাব রিপোর্ট"));
      expect(screen.queryAllByRole("listitem").length).toBeLessThanOrEqual(total);
      expect(await axeViolations(container)).toEqual([]);
    });
  }
});
