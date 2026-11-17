import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Transport } from "../api/client";
import { mockTransport } from "../api/mock";
import { axeViolations, DOCTOR_TOKEN, renderApp } from "../test-utils";

// B8c, with W2: when the server refuses the token (401) and it cannot be renewed from the refresh cookie (none here), the user is
// signed out and the sign-in page says why, instead of every screen saying "sign in again" with no way forward.
afterEach(() => cleanup());

function expiresAfter(n: number): Transport {
  const inner = mockTransport();
  let calls = 0;
  return async (r) => (r.headers.Authorization && ++calls > n
    ? { status: 401, body: { code: "unauthenticated", message: "A valid access token is required.", details: {} } } : inner(r));
}

describe("an expired session", () => {
  for (const [lang, note, title] of [["bn", "আপনার সেশন শেষ হয়ে গেছে। আবার লগইন করুন।", "লগইন"],
                                     ["en", "Your session has ended. Please sign in again.", "Sign in"]] as const) {
    it(`patient: the next refused request signs out and the sign-in page says why (${lang})`, async () => {
      const { container } = renderApp("/patient/timeline", { lang, signedIn: true, transport: expiresAfter(0) });
      expect(await screen.findByText(note)).toBeTruthy();
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(title);
      expect(screen.queryByText(/SYNTH-DRUG/)).toBeNull(); // nothing from the record stays on screen
      expect(await axeViolations(container)).toEqual([]);
    });
  }

  it("staff: a doctor whose token expires lands on the doctor sign-in page", async () => {
    renderApp("/doctor", { lang: "en", token: DOCTOR_TOKEN, transport: expiresAfter(0) });
    expect(await screen.findByText("Your session has ended. Please sign in again.")).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Sign in"));
  });

  it("a wrong sign-in code (401 without a token) is not an expired session", async () => {
    renderApp("/patient/login", { lang: "en", transport: expiresAfter(0) });
    fireEvent.change(screen.getByLabelText("Mobile number"), { target: { value: "01700000001" } });
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));
    fireEvent.change(await screen.findByLabelText("One-time code"), { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("That code is wrong or has expired.")).toBeTruthy();
    expect(screen.queryByText("Your session has ended. Please sign in again.")).toBeNull();
  });
});
