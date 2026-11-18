import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { mockTransport } from "../api/mock";
import type { ApiRequest } from "../api/client";
import { axeViolations, DOCTOR_TOKEN, renderApp } from "../test-utils";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("UX-3c where you're signed in", () => {
  for (const [lang, title, other, end, confirm, ended] of [
    ["bn", "কোথায় লগইন আছে", "Firefox · Windows", "এই সেশন বন্ধ করুন", "এই ডিভাইস থেকে লগআউট করবেন?", "সেশন বন্ধ হয়েছে।"],
    ["en", "Where you're signed in", "Firefox · Windows", "End this session", "Sign out that device?", "Session ended."]] as const) {
    it(`lists devices by family, marks this one, and ends another only after a confirmation (${lang})`, async () => {
      const seen: ApiRequest[] = [];
      const real = mockTransport();
      const { container } = renderApp("/patient/more", { lang, signedIn: true, transport: (r) => (seen.push(r), real(r)) });
      const section = (await screen.findByRole("heading", { name: title })).closest("section")!;
      await within(section).findByText(other);
      expect(within(section).getAllByRole("button", { name: end })).toHaveLength(1); // not on this device
      expect(await axeViolations(container)).toEqual([]);
      fireEvent.click(within(section).getByRole("button", { name: end }));
      const dialog = screen.getByRole("alertdialog", { name: confirm });
      expect(seen.some((r) => r.path.endsWith("/revoke"))).toBe(false);
      fireEvent.click(within(dialog).getByRole("button", { name: end }));
      expect(await screen.findByText(ended, { exact: false })).toBeTruthy();
      await waitFor(() => expect(within(section).queryByText(other)).toBeNull());
      expect(seen.filter((r) => r.method === "POST" && r.path.endsWith("/revoke"))).toHaveLength(1);
    });
  }

  it("a doctor has an account page with the same list", async () => {
    const { container } = renderApp("/doctor/account", { lang: "en", token: DOCTOR_TOKEN });
    expect(await screen.findByRole("heading", { level: 1, name: "My account" })).toBeTruthy();
    expect(await screen.findByText("This device")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});
