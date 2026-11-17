import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axeViolations, DOCTOR_TOKEN, renderApp } from "../test-utils";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("UX-3 command menu", () => {
  for (const [lang, open, query, page, heading] of [
    ["bn", "পাতা খুঁজুন", "সারাংশ", "আমার স্বাস্থ্য সারাংশ", "আমার স্বাস্থ্য সারাংশ"],
    ["en", "Find a page", "summ", "My health summary", "My health summary"]] as const) {
    it(`Ctrl+K opens it; typing filters; Enter opens the page (${lang})`, async () => {
      const { container } = renderApp("/patient", { lang, signedIn: true });
      await screen.findByRole("button", { name: open });
      fireEvent.keyDown(document, { key: "k", ctrlKey: true });
      const dialog = screen.getByRole("dialog");
      const input = within(dialog).getByRole("combobox");
      expect(document.activeElement).toBe(input);
      expect(await axeViolations(container)).toEqual([]);
      fireEvent.change(input, { target: { value: query } });
      expect(within(dialog).getAllByRole("option").map((o) => o.textContent)).toEqual([page]);
      fireEvent.keyDown(input, { key: "Enter" });
      expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeTruthy();
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  }

  it("arrow keys move, Escape closes and returns focus to the button", async () => {
    renderApp("/patient", { lang: "en", signedIn: true });
    const button = await screen.findByRole("button", { name: "Find a page" });
    fireEvent.click(button);
    const input = within(screen.getByRole("dialog")).getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const options = within(screen.getByRole("dialog")).getAllByRole("option");
    expect(options[1].getAttribute("aria-selected")).toBe("true");
    expect(input.getAttribute("aria-activedescendant")).toBe(options[1].id);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it("a doctor sees only the doctor's own pages", async () => {
    renderApp("/doctor", { lang: "en", token: DOCTOR_TOKEN });
    fireEvent.click(await screen.findByRole("button", { name: "Find a page" }));
    const names = within(screen.getByRole("dialog")).getAllByRole("option").map((o) => o.textContent);
    expect(names).toContain("Find patient");
    expect(names.some((n) => /Audit|Rule registry|Timeline/.test(n ?? ""))).toBe(false);
  });

  it("is not on the sign-in or landing pages", async () => {
    renderApp("/", { lang: "en" });
    expect(screen.queryByRole("button", { name: "Find a page" })).toBeNull();
  });
});

describe("UX-3 copy button", () => {
  it("says copied, or says it could not copy", async () => {
    const writeText = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("blocked"));
    Object.assign(navigator, { clipboard: { writeText } });
    renderApp("/patient/profile", { lang: "en", signedIn: true });
    fireEvent.click(await screen.findByRole("button", { name: "Copy number" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
    expect(writeText).toHaveBeenCalledWith("SID-4827190356");
    fireEvent.click(screen.getByRole("button", { name: "Copied" }));
    expect(await screen.findByText("Could not copy. Read the number from the screen.")).toBeTruthy();
  });
});

describe("UX-3 landing and sign-in", () => {
  for (const lang of ["bn", "en"] as const) {
    it(`landing has a skip link and a menu button that opens the section links (${lang})`, async () => {
      const { container } = renderApp("/", { lang });
      expect(screen.getByRole("link", { name: lang === "en" ? "Skip to main content" : "মূল অংশে যান" }).getAttribute("href")).toBe("#main");
      const menu = screen.getByRole("button", { name: lang === "en" ? "Menu" : "মেনু" });
      expect(menu.getAttribute("aria-expanded")).toBe("false");
      fireEvent.click(menu);
      expect(menu.getAttribute("aria-expanded")).toBe("true");
      expect(document.getElementById("land-nav")!.className).toContain("open");
      expect(await axeViolations(container)).toEqual([]);
    });
  }

  it("a sign-in error sits under its field, marks it invalid, and says how to fix it", async () => {
    const { container } = renderApp("/patient/login", { lang: "en" });
    const phone = await screen.findByLabelText("Mobile number");
    fireEvent.change(phone, { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));
    await waitFor(() => expect(phone.getAttribute("aria-invalid")).toBe("true"));
    expect(phone.getAttribute("aria-describedby")).toContain("phone-error");
    expect(document.getElementById("phone-error")!.textContent).toContain("Enter an 11-digit mobile number");
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("W1 landing refinement", () => {
  for (const [lang, demo, features] of [
    ["bn", "নমুনা (ডেমো) · বানানো তথ্য", ["এক টাইমলাইন", "মেডিকেল রেকর্ড", "স্বাস্থ্য সারাংশ", "অনুমতি আপনার হাতে", "বাসায় মাপা রিডিং", "কে দেখেছে"]],
    ["en", "Preview (demo) · made-up data", ["One timeline", "Medical records", "Health summary", "Consent in your hands", "Home readings", "Access history"]],
  ] as const) {
    it(`hero preview is labelled a demo; three steps; six features; both audiences (${lang})`, async () => {
      const { container } = renderApp("/", { lang });
      expect(screen.getByRole("figure", { name: demo })).toBeTruthy();
      const how = screen.getByRole("region", { name: lang === "en" ? "How it works" : "কীভাবে কাজ করে" });
      expect(within(how).getAllByRole("heading", { level: 3 })).toHaveLength(3);
      const feats = document.getElementById("features")!;
      expect(within(feats).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(features);
      expect(document.getElementById("patients")).toBeTruthy();
      expect(document.getElementById("doctors")).toBeTruthy();
      const footer = screen.getByRole("navigation", { name: lang === "en" ? "Page links" : "পাতার লিংক" });
      expect(within(footer).getAllByRole("link").map((a) => a.getAttribute("href")))
        .toEqual(["#how", "#patients", "#doctors", "#yours", "/patient/login"]);
      expect(await axeViolations(container)).toEqual([]);
    });
  }
});
