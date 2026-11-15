import { AlertTriangle, CheckCircle2, FileCheck2, UserRound } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { ApiError } from "../api/client";
import type { DocStatus, Provenance } from "../api/types";
import { useI18n } from "../i18n/i18n";
import { bn, type Key } from "../i18n/strings";

/** Text for an error: the matching `err.<code>` string, or the generic one. Never a raw server message. */
export function useErrorText() {
  const { t } = useI18n();
  return (error: unknown): string => {
    const key = error instanceof ApiError ? (`err.${error.code}` as Key) : null;
    return key && key in bn ? t(key) : t("common.error");
  };
}

export function ErrorNote({ error }: { error: unknown }) {
  const text = useErrorText();
  return error ? <p className="error-note" role="alert"><AlertTriangle size={18} aria-hidden="true" />{text(error)}</p> : null;
}

export function Loading() {
  const { t } = useI18n();
  return <p role="status" className="muted">{t("common.loading")}</p>;
}

/** Only the two provenances the timeline has (owner decision 2026-11-15): icon + words + style, never colour alone. */
export function ProvenanceBadge({ value }: { value: Provenance }) {
  const { t } = useI18n();
  const Icon = value === "document_verified" ? FileCheck2 : UserRound;
  return <span className={`badge badge-${value}`}><Icon size={16} aria-hidden="true" />{t(`prov.${value}`)}</span>;
}

export function StatusChip({ status }: { status: DocStatus }) {
  const { t } = useI18n();
  return <span className={`chip chip-${status}`}>{status === "verified" && <CheckCircle2 size={14} aria-hidden="true" />}{t(`status.${status}`)}</span>;
}

/** A confirmation step for actions that cannot be undone (revoke, reject). Focus starts on the safe choice; Escape cancels. */
export function ConfirmDialog({ open, title, confirmLabel, onConfirm, onCancel, danger = true }:
  { open: boolean; title: string; confirmLabel: string; onConfirm: () => void; onCancel: () => void; danger?: boolean }) {
  const { t } = useI18n();
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [open, onCancel]);
  if (!open) return null;
  return (
    <div className="dialog-backdrop">
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" className="dialog card">
        <p id="confirm-title" className="dialog-title">{title}</p>
        <div className="actions">
          <button type="button" ref={cancelRef} onClick={onCancel}>{t("common.cancel")}</button>
          <button type="button" className={danger ? "btn-danger" : "btn-primary"} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

export function Section({ title, children, id }: { title: string; children: ReactNode; id: string }) {
  return (
    <section aria-labelledby={id} className="section">
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  );
}
