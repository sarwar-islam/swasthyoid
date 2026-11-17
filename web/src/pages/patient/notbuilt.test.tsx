import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Transport } from "../../api/client";
import { mockTransport } from "../../api/mock";
import { axeViolations, renderApp } from "../../test-utils";

// B8b: in live mode the M7, M8 and M13 routes are not on the server (docs/ROUTES.md); FastAPI answers a bare 404. The
// screen must say so in both languages and never show made-up data or a success.
const UNBUILT = /^\/(vitals|reminders|triage)/;
function liveLike(): Transport {
  const inner = mockTransport();
  return async (r) => (UNBUILT.test(r.path) ? { status: 404, body: { detail: "Not Found" } } : inner(r));
}
const NOT_BUILT = { bn: "এই অংশটি এখনো সার্ভারে চালু হয়নি। তাই এখানে কোনো তথ্য দেখানো হচ্ছে না।", en: "This part isn't on the server yet, so nothing is shown here." };

afterEach(() => cleanup());

describe("screens the server does not serve yet", () => {
  for (const lang of ["bn", "en"] as const) {
    for (const path of ["/patient/vitals", "/patient/reminders"]) {
      it(`${path} says it is not on the server yet (${lang})`, async () => {
        const { container } = renderApp(path, { lang, signedIn: true, transport: liveLike() });
        expect((await screen.findByRole("alert")).textContent).toBe(NOT_BUILT[lang]);
        expect(screen.queryByRole("status", { name: /saved|সংরক্ষিত/i })).toBeNull();
        expect(await axeViolations(container)).toEqual([]);
      });
    }

    it(`triage says so and still shows the emergency card (fail safe, ${lang})`, async () => {
      const { container } = renderApp("/patient/help", { lang, signedIn: true, transport: liveLike() });
      fireEvent.change(screen.getByRole("textbox"), { target: { value: "SYNTH symptom" } });
      fireEvent.submit(screen.getByRole("textbox").closest("form")!);
      await screen.findByText(NOT_BUILT[lang]);
      const alerts = screen.getAllByRole("alert");
      expect(alerts.map((a) => a.textContent === NOT_BUILT[lang])).toEqual([true, false]); // the note, then the emergency card
      if (lang === "en") expect(within(alerts[1]).getByText("Contact your nearest health facility.")).toBeTruthy();
      expect(await axeViolations(container)).toEqual([]);
    });
  }
});
