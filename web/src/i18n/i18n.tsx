import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { bn, en, type Key } from "./strings";

export type Lang = "bn" | "en";
const BN_DIGITS = "০১২৩৪৫৬৭৮৯";
const LANG_KEY = "swasthyoid.lang"; // a display preference only; no health data is ever kept in browser storage

/** ASCII digits in `text` as Bangla digits (০-৯). Everything else is unchanged. */
export function toBanglaDigits(text: string): string {
  return text.replace(/[0-9]/g, (d) => BN_DIGITS[Number(d)]);
}

/** Bangla digits in `text` as ASCII digits: what is sent to the API and stored. */
export function toAsciiDigits(text: string): string {
  return text.replace(/[০-৯]/g, (d) => String(BN_DIGITS.indexOf(d)));
}

/** Digits for display in the current language (IDs, codes, numbers already formatted as text). */
export function localDigits(text: string, lang: Lang): string {
  return lang === "bn" ? toBanglaDigits(text) : text;
}

export function formatNumber(value: number, lang: Lang, options?: Intl.NumberFormatOptions): string {
  return localDigits(new Intl.NumberFormat("en-US", { useGrouping: false, ...options }).format(value), lang);
}

export function formatDate(iso: string, lang: Lang): string {
  return new Intl.DateTimeFormat(lang === "bn" ? "bn-BD" : "en-GB", { day: "numeric", month: "long", year: "numeric" })
    .format(new Date(iso));
}

/** Date and time to the minute (audit and metrics), in the local digits. */
export function formatDateTime(iso: string, lang: Lang): string {
  return localDigits(new Intl.DateTimeFormat(lang === "bn" ? "bn-BD" : "en-GB", { day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(iso)), lang); // 24-hour: no Latin AM/PM in Bangla
}

function readLang(): Lang {
  try {
    return localStorage.getItem(LANG_KEY) === "en" ? "en" : "bn";
  } catch {
    return "bn"; // storage blocked: Bangla first
  }
}

interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: Key, vars?: Record<string, string>) => string;
}

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Lang }) {
  const [lang, setLangState] = useState<Lang>(initial ?? readLang);
  useEffect(() => {
    document.documentElement.lang = lang;
    try {
      localStorage.setItem(LANG_KEY, lang);
    } catch {
      /* the choice just isn't remembered */
    }
  }, [lang]);
  const t = (key: Key, vars?: Record<string, string>) =>
    (lang === "bn" ? bn : en)[key].replace(/\{(\w+)\}/g, (_, name: string) => vars?.[name] ?? `{${name}}`);
  return <I18nContext.Provider value={{ lang, setLang: setLangState, t }}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n needs an I18nProvider");
  return value;
}
