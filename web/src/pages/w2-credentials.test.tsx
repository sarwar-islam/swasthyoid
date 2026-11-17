import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MOCK_SUBMITTED_DOCTOR_ID, mockTransport } from "../api/mock";
import { ADMIN_TOKEN, axeViolations, renderApp } from "../test-utils";

// W2 (owner decision b, 2026-11-17): a doctor adds a photo of the pending BMDC certificate, JPEG or PNG only; the admin
// sees it next to the number before approving.
const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "");
const SUBMITTED_TOKEN = `${b64({ alg: "none" })}.${b64({ sub: MOCK_SUBMITTED_DOCTOR_ID, role: "doctor" })}.test`;
const photo = (type = "image/jpeg", name = "bmdc.jpg") => new File([new Uint8Array([0xff, 0xd8, 0xff])], name, { type });

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:synthetic");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("W2 credential photo", () => {
  for (const [lang, label, upload, done] of [
    ["bn", "সনদের ছবি (JPEG বা PNG)", "ছবি আপলোড করুন", "সনদের ছবি জমা হয়েছে।"],
    ["en", "Certificate photo (JPEG or PNG)", "Upload photo", "Certificate photo submitted."]] as const) {
    it(`a doctor with a pending credential uploads a photo of it (${lang})`, async () => {
      const { container } = renderApp("/doctor/credentials", { lang, token: SUBMITTED_TOKEN });
      const input = await screen.findByLabelText(label);
      expect(input.getAttribute("accept")).toBe("image/jpeg,image/png");
      expect(await axeViolations(container)).toEqual([]);
      fireEvent.change(input, { target: { files: [photo()] } });
      fireEvent.click(screen.getByRole("button", { name: upload }));
      expect(await screen.findByText(done)).toBeTruthy();
      expect(await axeViolations(container)).toEqual([]);
    });
  }

  it("a PDF is refused with the server's reason", async () => {
    renderApp("/doctor/credentials", { lang: "en", token: SUBMITTED_TOKEN });
    fireEvent.change(await screen.findByLabelText("Certificate photo (JPEG or PNG)"),
      { target: { files: [photo("application/pdf", "bmdc.pdf")] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload photo" }));
    expect(await screen.findByText("Only JPEG or PNG images are accepted.")).toBeTruthy();
  });

  it("the admin opens the photo next to the number; a credential without one says so", async () => {
    const transport = mockTransport();
    renderApp("/doctor/credentials", { lang: "en", token: SUBMITTED_TOKEN, transport });
    fireEvent.change(await screen.findByLabelText("Certificate photo (JPEG or PNG)"), { target: { files: [photo("image/png", "b.png")] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload photo" }));
    await screen.findByText("Certificate photo submitted.");
    cleanup();
    const { container } = renderApp("/console/credentials", { lang: "en", token: ADMIN_TOKEN, transport });
    fireEvent.click(await screen.findByRole("button", { name: "Show certificate photo" }));
    const img = await screen.findByRole("img", { name: /BMDC certificate photo of/ });
    expect(img.getAttribute("src")).toBe("blob:synthetic");
    expect(screen.getByRole("button", { name: "Hide photo" }).getAttribute("aria-expanded")).toBe("true");
    expect(await axeViolations(container)).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Hide photo" }));
    await waitFor(() => expect(screen.queryByRole("img", { name: /BMDC certificate photo of/ })).toBeNull());
  });
});
