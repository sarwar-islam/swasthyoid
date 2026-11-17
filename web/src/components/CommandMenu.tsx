import { Search } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router";
import { useScrollLock } from "./ui";
import { useI18n } from "../i18n/i18n";
import type { Key } from "../i18n/strings";

export interface Command { to: string; label: Key }

/** UX-3: go to any page of this portal by typing (Ctrl+K or Cmd+K, or the search button). Only pages the shell already shows
 * this user; it searches page names, never records. Arrow keys move, Enter opens, Escape closes. */
export function CommandMenu({ items }: { items: Command[] }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const id = useId();
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  useScrollLock(open);
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    input.current?.focus();
  }, [open]);

  const q = query.trim().toLowerCase();
  const shown = items.filter((c) => !q || t(c.label).toLowerCase().includes(q) || c.to.includes(q));
  const close = () => {
    setOpen(false);
    opener.current?.focus();
  };
  const go = (c?: Command) => {
    if (!c) return;
    setOpen(false);
    navigate(c.to);
  };
  const onKey = (e: ReactKeyboardEvent) => {
    if (e.key === "Escape") close();
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, shown.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); go(shown[active]); }
  };

  return (
    <>
      <button type="button" ref={opener} className="icon-btn" aria-haspopup="dialog" aria-label={t("cmd.open")}
              aria-keyshortcuts={mac ? "Meta+K" : "Control+K"} onClick={() => setOpen(true)}>
        <Search size={18} aria-hidden="true" />
        <span className="cmdk-hint" aria-hidden="true"><kbd>{mac ? "⌘" : "Ctrl"}</kbd> <kbd>K</kbd></span>
      </button>
      {open && createPortal(
        <div className="cmdk-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
          <div role="dialog" aria-modal="true" aria-label={t("cmd.title")} className="cmdk" onKeyDown={onKey}>
            <input ref={input} type="text" role="combobox" aria-expanded="true" aria-controls={`${id}-list`} aria-autocomplete="list"
                   aria-label={t("cmd.title")} placeholder={t("cmd.placeholder")} value={query}
                   aria-activedescendant={shown[active] ? `${id}-${active}` : undefined}
                   onChange={(e) => { setQuery(e.target.value); setActive(0); }} />
            <ul id={`${id}-list`} role="listbox" aria-label={t("cmd.results")}>
              {shown.map((c, i) => (
                <li key={c.to} id={`${id}-${i}`} role="option" aria-selected={i === active}
                    onMouseEnter={() => setActive(i)} onClick={() => go(c)}>{t(c.label)}</li>
              ))}
            </ul>
            {shown.length === 0 && <p className="muted" role="status">{t("cmd.none")}</p>}
            <p className="muted"><kbd>↑</kbd> <kbd>↓</kbd> {t("cmd.move")} · <kbd>Enter</kbd> {t("cmd.go")} · <kbd>Esc</kbd> {t("cmd.close")}</p>
          </div>
        </div>, document.body,
      )}
    </>
  );
}
