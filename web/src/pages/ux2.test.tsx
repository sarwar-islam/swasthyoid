import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Transport } from "../api/client";
import { MOCK_CODE, MOCK_HEALTH_ID, mockTransport } from "../api/mock";
import { axeViolations, renderApp, VERIFIER_TOKEN } from "../test-utils";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("UX-2 sign-out confirmation", () => {
  for (const [lang, out, title, yes, back] of [["bn", "লগআউট", "এখন লগআউট করবেন?", "হ্যাঁ, লগআউট করুন", "না, ফিরে যান"],
                                              ["en", "Sign out", "Sign out now?", "Yes, sign out", "No, go back"]] as const) {
    it(`asks first; going back keeps the session, yes signs out (${lang})`, async () => {
      const { container } = renderApp("/patient", { lang, signedIn: true });
      fireEvent.click(await screen.findByRole("button", { name: out }));
      const dialog = screen.getByRole("alertdialog", { name: title });
      expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: back })); // the safe choice
      expect(await axeViolations(container)).toEqual([]);
      fireEvent.click(within(dialog).getByRole("button", { name: back }));
      expect(screen.queryByRole("alertdialog")).toBeNull();
      expect(screen.getByRole("button", { name: out })).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: out }));
      fireEvent.click(screen.getByRole("button", { name: yes }));
      await screen.findByLabelText(lang === "en" ? "Mobile number" : "মোবাইল নম্বর");
    });
  }

  it("warns about what was typed on a form and not sent", async () => {
    renderApp("/patient/vitals", { lang: "en", signedIn: true });
    const input = (await screen.findAllByRole("textbox"))[0] ?? (await screen.findAllByRole("spinbutton"))[0];
    fireEvent.input(input, { target: { value: "120" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.getByText("What you typed on this form is not saved and will be lost.")).toBeTruthy();
  });

  it("without changes there is no warning", async () => {
    renderApp("/patient", { lang: "en", signedIn: true });
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(screen.queryByText("What you typed on this form is not saved and will be lost.")).toBeNull();
  });

  for (const [lang, warn] of [["bn", "রোগীর সাথে চলমান সহায়তা সেশন এই স্ক্রিনে শেষ হয়ে যাবে।"],
                              ["en", "The assisted session with the patient will end on this screen."]] as const) {
    it(`warns a verifier with an assisted session open (${lang})`, async () => {
      const { container } = renderApp("/verifier", { lang, token: VERIFIER_TOKEN });
      await screen.findByRole("heading", { level: 1 });
      type(lang === "bn" ? "রোগীর Health ID" : "Patient's Health ID", MOCK_HEALTH_ID);
      fireEvent.click(screen.getByRole("button", { name: lang === "bn" ? "রোগীর ফোনে কোড পাঠান" : "Send a code to the patient's phone" }));
      await screen.findByLabelText(lang === "bn" ? "রোগীর বলা কোড" : "Code from the patient");
      type(lang === "bn" ? "রোগীর বলা কোড" : "Code from the patient", MOCK_CODE);
      fireEvent.click(screen.getByRole("button", { name: lang === "bn" ? "কোড দিয়ে শুরু করুন" : "Start with the code" }));
      await screen.findByRole("region", { name: lang === "bn" ? "চলমান সেশন" : "Current session" });
      fireEvent.click(screen.getByRole("button", { name: lang === "bn" ? "লগআউট" : "Sign out" }));
      expect(within(screen.getByRole("alertdialog")).getByText(warn)).toBeTruthy();
      expect(await axeViolations(container)).toEqual([]);
    });
  }
});

describe("UX-2 patient health summary", () => {
  for (const [lang, verified, reported, title] of [
    ["bn", "নথি থেকে, মানুষ যাচাই করেছে", "রোগীর দেওয়া, যাচাই করা নয়", "আমার স্বাস্থ্য সারাংশ"],
    ["en", "From a document, checked by a person", "Reported by the patient, not verified", "My health summary"]] as const) {
    it(`shows recorded items with provenance in words and no internal fields (${lang})`, async () => {
      const { container } = renderApp("/patient/summary", { lang, signedIn: true });
      expect(await screen.findByRole("heading", { level: 1, name: title })).toBeTruthy();
      await waitFor(() => expect(screen.getAllByText(verified).length).toBeGreaterThan(0));
      expect(screen.getAllByText(reported).length).toBeGreaterThan(0);
      expect(screen.getByText(/SYNTH-DRUG-003/)).toBeTruthy();
      const text = document.querySelector("main")!.textContent!;
      for (const internal of ["manual_entry", "correction", "e-bp-2", "d-verified", "SYNTH typed"]) expect(text).not.toContain(internal);
      expect(await axeViolations(container)).toEqual([]);
    });
  }

  it("an empty record says only that nothing is recorded, in every section", async () => {
    const inner = mockTransport();
    const empty: Transport = async (r) => (r.path.endsWith("/timeline") ? { status: 200, body: [] } : inner(r));
    renderApp("/patient/summary", { lang: "bn", signedIn: true, transport: empty });
    await waitFor(() => expect(screen.getAllByText("কোনো তথ্য রেকর্ড করা নেই")).toHaveLength(5));
  });

  it("never asks for safety alerts", async () => {
    const inner = mockTransport();
    const paths: string[] = [];
    const spy: Transport = async (r) => (paths.push(r.path), inner(r));
    renderApp("/patient/summary", { lang: "en", signedIn: true, transport: spy });
    await screen.findAllByText("From a document, checked by a person");
    expect(paths.some((p) => p.includes("alert") || p.includes("summary"))).toBe(false);
  });
});
