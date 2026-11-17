import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axeViolations, DOCTOR_TOKEN, renderApp } from "../test-utils";

// W2 (owner decisions c and d, 2026-11-17): the patient downloads their own data as one JSON file; home vitals in a separate
// patient-reported part; no document images.
let saved: Blob[] = [];
let clicked: string[] = [];
beforeEach(() => {
  saved = [];
  clicked = [];
  URL.createObjectURL = vi.fn((b: Blob) => (saved.push(b), "blob:synthetic-export"));
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push(this.download);
  });
});
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("W2 download my data", () => {
  for (const [lang, button, done] of [["bn", "আমার তথ্য ডাউনলোড", "ফাইল ডাউনলোড হয়েছে।"],
                                      ["en", "Download my data", "File downloaded."]] as const) {
    it(`the patient saves one JSON file from More (${lang})`, async () => {
      const { container } = renderApp("/patient/more", { lang, signedIn: true });
      fireEvent.click(await screen.findByRole("button", { name: button }));
      expect(await screen.findByText(done)).toBeTruthy();
      expect(clicked).toEqual(["swasthyoid-export.json"]);
      const data = JSON.parse(await saved[0].text());
      expect(Object.keys(data.patient_reported)).toEqual(["vitals"]);
      expect(data.not_included).toEqual(["document_images"]);
      expect(Array.isArray(data.events) && Array.isArray(data.consents) && Array.isArray(data.access_history)).toBe(true);
      expect(await axeViolations(container)).toEqual([]);
    });
  }

  it("a doctor cannot export (the mock refuses by role, as the server)", async () => {
    const { mockTransport } = await import("../api/mock");
    const { createClient } = await import("../api/client");
    await expect(createClient(mockTransport(), () => DOCTOR_TOKEN).request("GET", "/me/export")).rejects.toMatchObject({ status: 403 });
  });
});
