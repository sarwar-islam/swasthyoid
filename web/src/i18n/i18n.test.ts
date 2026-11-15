import { describe, expect, it } from "vitest";
import { formatDate, formatNumber, localDigits, toAsciiDigits, toBanglaDigits } from "./i18n";
import { bn, en } from "./strings";

describe("Bangla numerals", () => {
  it("convert both ways and leave everything else alone", () => {
    expect(toBanglaDigits("SID-4827190356")).toBe("SID-৪৮২৭১৯০৩৫৬");
    expect(toAsciiDigits("১২০/৮০ mmHg")).toBe("120/80 mmHg");
    expect(toAsciiDigits(toBanglaDigits("0123456789"))).toBe("0123456789");
    expect(toBanglaDigits("no digits")).toBe("no digits");
  });

  it("follow the language for display", () => {
    expect(localDigits("৯৯৯ 999", "bn")).toBe("৯৯৯ ৯৯৯");
    expect(localDigits("999", "en")).toBe("999");
    expect(formatNumber(0.85, "bn")).toBe("০.৮৫");
    expect(formatNumber(180, "en")).toBe("180");
  });

  it("formats dates in Bangla with Bangla digits", () => {
    expect(formatDate("2026-11-14T12:00:00Z", "bn")).toMatch(/১৪/);
    expect(formatDate("2026-11-14T12:00:00Z", "en")).toMatch(/14 November 2026/);
  });
});

describe("strings", () => {
  it("every key has non-empty text in both languages, and Bangla text carries no ASCII digit", () => {
    for (const key of Object.keys(bn) as Array<keyof typeof bn>) {
      expect(bn[key].trim(), key).not.toBe("");
      expect(en[key].trim(), key).not.toBe("");
      expect(bn[key], key).not.toMatch(/[0-9]/);
    }
    expect(Object.keys(en).sort()).toEqual(Object.keys(bn).sort());
  });
});
