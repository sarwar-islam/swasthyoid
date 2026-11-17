import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type ApiRequest, createClient, type Transport } from "../api/client";
import { mockTransport } from "../api/mock";
import { axeViolations, PATIENT_TOKEN, renderApp } from "../test-utils";

let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, "fetch");
});
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled(); // no network: the landing page and logout run on the mock
  fetchSpy.mockRestore();
  vi.unstubAllEnvs();
  cleanup();
});

const SAFE_OR_MADE_UP = /you are safe|you're safe|আপনি নিরাপদ|[0-9০-৯]+\s*(lakh|million|লাখ)|certified|সার্টিফায়েড/i;

describe("W1 landing page", () => {
  for (const lang of ["bn", "en"] as const) {
    it(`shows the patient story first, doctors after, staff sign-in in the footer (${lang})`, async () => {
      const { container } = renderApp("/", { lang });
      const h1 = screen.getByRole("heading", { level: 1 });
      expect(h1.textContent).toBe(lang === "en" ? "Your prescriptions and reports, in one place, under your control"
        : "আপনার প্রেসক্রিপশন আর রিপোর্ট, এক জায়গায়, আপনার নিয়ন্ত্রণে");
      for (const a of screen.getAllByRole("link", { name: lang === "en" ? /Create patient account/ : /রোগী অ্যাকাউন্ট খুলুন/ })) expect(a.getAttribute("href")).toBe("/patient/login");
      for (const a of screen.getAllByRole("link", { name: lang === "en" ? "Sign in" : "লগইন" })) expect(a.getAttribute("href")).toBe("/patient/login");
      expect(screen.getByRole("link", { name: lang === "en" ? "Sign in or register as a doctor" : "ডাক্তার হিসেবে লগইন বা নিবন্ধন" })
        .getAttribute("href")).toBe("/doctor/login");
      const staff = screen.getByRole("navigation", { name: lang === "en" ? "Staff sign-in" : "কর্মীদের লগইন" });
      expect(within(staff).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["/verifier/login", "/console/login", "/portals"]);
      expect(screen.getByRole("link", { name: /999|৯৯৯/ }).getAttribute("href")).toBe("tel:999");
      expect(screen.getByText(lang === "en" ? /This is a prototype/ : /এটি একটি প্রোটোটাইপ/)).toBeTruthy();
      expect(document.body.textContent).not.toMatch(SAFE_OR_MADE_UP);
      expect(document.body.textContent).not.toMatch(/reminder|রিমাইন্ডার|triage/i); // not on the server yet (P8)
      expect(await axeViolations(container)).toEqual([]);
    });
  }

  it("says the emergency card exception only when M10's flag is on", () => {
    renderApp("/", { lang: "en" });
    expect(screen.getByText("No doctor can see your record without your code or QR.")).toBeTruthy();
    cleanup();
    vi.stubEnv("VITE_FEATURE_EMERGENCY_ACCESS", "1");
    renderApp("/", { lang: "en" });
    expect(screen.getByText(/only the emergency card you set up may be seen, and you are told/)).toBeTruthy();
  });

  it("the developer portal list moved to /portals", () => {
    renderApp("/portals", { lang: "en" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Choose a portal");
  });
});

describe("W2 sign out", () => {
  function spy() {
    const inner = mockTransport();
    const seen: ApiRequest[] = [];
    const transport: Transport = (r) => {
      seen.push(r);
      return inner(r);
    };
    return { seen, transport };
  }

  it("sign out tells the server, which then refuses that token; the screen goes to sign-in", async () => {
    const { seen, transport } = spy();
    renderApp("/patient", { lang: "en", signedIn: true, transport });
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes, sign out" }));
    await waitFor(() => expect(seen.some((r) => r.method === "POST" && r.path === "/auth/logout")).toBe(true));
    await screen.findByRole("button", { name: /Send code/ });
    await expect(createClient(transport, () => PATIENT_TOKEN).request("GET", "/me")).rejects.toMatchObject({ status: 401 });
  });

  for (const lang of ["bn", "en"] as const) {
    it(`sign out on all devices is on More, explained, and ends the session (${lang})`, async () => {
      const { seen, transport } = spy();
      const { container } = renderApp("/patient/more", { lang, signedIn: true, transport });
      expect(await axeViolations(container)).toEqual([]);
      fireEvent.click(screen.getByRole("button", { name: lang === "en" ? "Sign out on all devices" : "সব ডিভাইস থেকে লগআউট" }));
      await waitFor(() => expect(seen.some((r) => r.method === "POST" && r.path === "/auth/logout-all")).toBe(true));
      await screen.findByLabelText(lang === "en" ? "Mobile number" : /মোবাইল নম্বর/);
    });
  }

  it("still signs out on this screen when the server cannot be reached", async () => {
    const inner = mockTransport();
    const offline: Transport = async (r) => (r.path.startsWith("/auth/logout") ? { status: 503, body: null } : inner(r));
    renderApp("/patient", { lang: "en", signedIn: true, transport: offline });
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes, sign out" }));
    await screen.findByRole("button", { name: /Send code/ });
  });
});
