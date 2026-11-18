import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { mockTransport } from "../api/mock";
import { axeViolations, renderApp } from "../test-utils";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("document page waits for the reader", () => {
  for (const [lang, waiting] of [
    ["bn", "নথিটি পড়ার অপেক্ষায় আছে। এই পাতা নিজে থেকে আপডেট হবে। চাইলে নিজে তথ্যগুলো লিখে দিতে পারেন।"],
    ["en", "Waiting to be read. This page updates by itself. You can also enter the details yourself."]] as const) {
    it(`says it is waiting, then shows the check by itself once the document is read (${lang})`, async () => {
      const real = mockTransport();
      let read = false; // the worker has not read it yet
      const transport: typeof real = async (r) => {
        const got = await real(r);
        if (!read && r.method === "GET" && r.path === "/documents/d-review" && got.status === 200) {
          return { ...got, body: { ...(got.body as object), status: "uploaded" } };
        }
        return got;
      };
      const { container } = renderApp("/patient/documents/d-review", { lang, signedIn: true, transport });
      expect(await screen.findByText(waiting)).toBeTruthy();
      expect(await axeViolations(container)).toEqual([]);
      read = true;
      await screen.findByRole("button", { name: lang === "en" ? /confirm/i : /নিশ্চিত/ }, { timeout: 6000 });
      expect(screen.queryByText(waiting)).toBeNull();
    }, 15_000);
  }
});
