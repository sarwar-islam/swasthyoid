import { Languages } from "lucide-react";
import { useI18n } from "../i18n/i18n";
import { useTheme, type Theme } from "../theme";

export function LanguageToggle() {
  const { lang, setLang, t } = useI18n();
  return (
    <button type="button" onClick={() => setLang(lang === "bn" ? "en" : "bn")} aria-label={t("lang.switchLabel")}
            lang={lang === "bn" ? "en" : "bn"}>
      <Languages size={18} aria-hidden="true" />
      {t("lang.switch")}
    </button>
  );
}

export function ThemeSelect() {
  const { theme, setTheme } = useTheme();
  const { t } = useI18n();
  return (
    <label>
      <span className="sr-only">{t("theme.label")}</span>
      <select value={theme} onChange={(e) => setTheme(e.target.value as Theme)} className="btn">
        <option value="system">{t("theme.system")}</option>
        <option value="light">{t("theme.light")}</option>
        <option value="dark">{t("theme.dark")}</option>
      </select>
    </label>
  );
}
