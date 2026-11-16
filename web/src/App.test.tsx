import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it } from "vitest";
import { ADMIN_TOKEN, renderApp, REVIEWER_TOKEN } from "./test-utils";

afterEach(() => {
  cleanup();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

const renderAt = (path: string, lang: "bn" | "en" = "bn") => renderApp(path, { lang, signedIn: true });

const PORTALS = ["/", "/patient", "/doctor", "/verifier", "/console"];

describe("portal shells", () => {
  it.each(PORTALS)("%s has a main landmark, a heading and no axe violations", async (path) => {
    const { container } = renderAt(path);
    expect(screen.getByRole("main")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 })).toBeTruthy();
    const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } }); // jsdom cannot compute colour
    expect(result.violations.map((v) => `${v.id}: ${v.nodes[0]?.target}`)).toEqual([]);
  });

  it("the patient app keeps the 999 emergency bar and a bottom bar of five, in Bangla by default", () => {
    renderAt("/patient");
    expect(screen.getByRole("link", { name: /জরুরি সাহায্য · ৯৯৯/ }).getAttribute("href")).toBe("tel:999");
    const nav = screen.getByRole("navigation", { name: "প্রধান মেনু" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent))
      .toEqual(["হোম", "টাইমলাইন", "নথি তুলুন", "সম্মতি", "আরও"]);
    expect(within(nav).getByRole("link", { name: "হোম" }).getAttribute("aria-current")).toBe("page");
  });

  it("switches to English and back, and sets the page language", () => {
    renderAt("/patient");
    fireEvent.click(screen.getByRole("button", { name: "ভাষা বদলান: English" }));
    expect(document.documentElement.lang).toBe("en");
    expect(screen.getByRole("link", { name: /Emergency help · 999/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Change language: বাংলা" }));
    expect(document.documentElement.lang).toBe("bn");
  });

  it("the theme choice sets data-theme, and Device removes it", () => {
    renderAt("/doctor", "en");
    const select = screen.getByRole("combobox", { name: "Theme" });
    fireEvent.change(select, { target: { value: "dark" } });
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    fireEvent.change(select, { target: { value: "system" } });
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("console menus hold only each role's in-scope pages; the M10 review stays hidden while its flag is off", () => {
    const menu = () => within(screen.getByRole("navigation", { name: "Main menu" })).getAllByRole("link").map((a) => a.textContent);
    renderApp("/console", { lang: "en", token: ADMIN_TOKEN });
    expect(menu()).toEqual(["Credential approvals", "Staff accounts", "Drug catalog import", "Audit log", "Worker metrics"]);
    for (const removed of [/referral/i, /pharmac/i, /appointment/i, /dispens/i, /prescription writer/i]) {
      expect(document.body.textContent).not.toMatch(removed);
    }
    cleanup();
    renderApp("/console", { lang: "en", token: REVIEWER_TOKEN });
    expect(menu()).toEqual(["Rule registry"]);
  });
});
