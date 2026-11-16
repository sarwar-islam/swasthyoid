import { AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert, Upload } from "lucide-react";
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import type { AuditPage as AuditData, CatalogImport, CredentialReview, DocStatus, StaffAccount, StaffCreateBody, WorkerMetrics } from "../../api/types";
import { ConfirmDialog, ErrorNote, Loading, Section } from "../../components/ui";
import { formatDateTime, formatNumber, localDigits, toAsciiDigits, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";
import { useAction } from "./console";

/** A reason form for reject or suspend: the action needs a reason, here and on the server. */
function ReasonForm({ id, label, submit, busy, onSubmit, onCancel }:
  { id: string; label: string; submit: string; busy: boolean; onSubmit: (reason: string) => void; onCancel: () => void }) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  return (
    <form className="stack" noValidate onSubmit={(e) => { e.preventDefault(); if (reason.trim()) onSubmit(reason.trim()); else setMissing(true); }}>
      <div className="field">
        <label htmlFor={id}>{label}</label>
        <textarea id={id} rows={2} value={reason} aria-invalid={missing} aria-describedby={missing ? `${id}-err` : undefined}
                  onChange={(e) => { setReason(e.target.value); setMissing(false); }} />
        {missing && <span id={`${id}-err`} className="error-note" role="alert">{t("common.reasonRequired")}</span>}
      </div>
      <div className="actions">
        <button type="submit" className="btn-danger" disabled={busy}>{submit}</button>
        <button type="button" onClick={onCancel}>{t("req.cancel")}</button>
      </div>
    </form>
  );
}

/** M1 credential approval: pending BMDC numbers to approve or reject (with a reason), verified doctors to suspend (with a reason;
 * every active consent of theirs is suspended at once, FRD section 2). The admin sees the registration number, never clinical content. */
export function CredentialsPage() {
  const { t } = useI18n();
  const { api } = useSession();
  const pending = useLoad(() => api.request<CredentialReview[]>("GET", "/credentials?status=pending"), []);
  const verified = useLoad(() => api.request<CredentialReview[]>("GET", "/credentials?status=verified"), []);
  const [open, setOpen] = useState<string | null>(null); // "<reject|suspend>:<id>"
  const [approving, setApproving] = useState<CredentialReview | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const act = useAction(() => { pending.reload(); verified.reload(); setOpen(null); });
  const after = (message: string) => (ok: boolean) => ok && setDone(message);

  const item = (c: CredentialReview, actions: ReactNode) => (
    <li key={c.id} className="card stack">
      <div className="row"><strong>{c.name}</strong><span className="mono" lang="en">{c.type} {c.number}</span></div>
      {actions}
    </li>
  );
  return (
    <>
      <h1>{t("nav.approvals")}</h1>
      <p className="notice">{t("cr.intro")}</p>
      {done && <p className="ok-note" role="status">{done}</p>}
      <ErrorNote error={act.error} />
      <Section id="cr-pending" title={t("cr.pending")}>
        {pending.loading && !pending.data ? <Loading /> : <ErrorNote error={pending.error} />}
        {pending.data?.length === 0 && <p className="muted">{t("cr.nonePending")}</p>}
        <ul className="list">
          {pending.data?.map((c) => item(c, open === `reject:${c.id}` ? (
            <ReasonForm id={`reject-${c.id}`} label={t("cr.rejectReason")} submit={t("cr.reject")} busy={act.busy} onCancel={() => setOpen(null)}
                        onSubmit={(reason) => act.run(() => api.request("POST", `/credentials/${c.id}/reject`, { body: { reason } }))
                          .then(after(t("cr.rejected", { name: c.name })))} />
          ) : (
            <div className="actions">
              <button type="button" className="btn-primary" disabled={act.busy} onClick={() => setApproving(c)}>{t("cr.approve")}</button>
              <button type="button" disabled={act.busy} onClick={() => setOpen(`reject:${c.id}`)}>{t("cr.reject")}</button>
            </div>
          )))}
        </ul>
      </Section>
      <Section id="cr-verified" title={t("cr.verified")}>
        {verified.data?.length === 0 && <p className="muted">{t("cr.noneVerified")}</p>}
        <ul className="list">
          {verified.data?.map((c) => item(c, open === `suspend:${c.id}` ? (
            <ReasonForm id={`suspend-${c.id}`} label={t("cr.suspendReason")} submit={t("cr.suspend")} busy={act.busy} onCancel={() => setOpen(null)}
                        onSubmit={(reason) => act.run(() => api.request("POST", `/admin/users/${c.user_id}/suspend`, { body: { reason } }))
                          .then(after(t("cr.suspended", { name: c.name })))} />
          ) : (
            <div className="actions"><button type="button" disabled={act.busy} onClick={() => setOpen(`suspend:${c.id}`)}>{t("cr.suspend")}</button></div>
          )))}
        </ul>
      </Section>
      <ConfirmDialog open={!!approving} danger={false} title={approving ? t("cr.approveAsk", { name: approving.name, number: approving.number }) : ""}
                     confirmLabel={t("cr.approve")} onCancel={() => setApproving(null)}
                     onConfirm={() => { const c = approving!; setApproving(null);
                       act.run(() => api.request("POST", `/credentials/${c.id}/approve`)).then(after(t("cr.approved", { name: c.name }))); }} />
    </>
  );
}

/** Staff provisioning (owner decision 2026-11-16, routes GAP): approve a verifier's own registration, create verifier and clinical
 * reviewer accounts (console roles never self-register), and suspend with a reason. Doctors are approved by their BMDC credential. */
export function StaffPage() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const pending = useLoad(() => api.request<StaffAccount[]>("GET", "/admin/staff?status=pending"), []);
  const active = useLoad(() => api.request<StaffAccount[]>("GET", "/admin/staff?status=verified"), []);
  const [role, setRole] = useState<StaffCreateBody["role"]>("verifier");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [approving, setApproving] = useState<StaffAccount | null>(null);
  const [suspending, setSuspending] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const act = useAction(() => { pending.reload(); active.reload(); setSuspending(null); });
  const after = (message: string) => (ok: boolean) => ok && setDone(message);
  const roleName = (a: StaffAccount) => t(`role.${a.role}`);
  const line = (a: StaffAccount) => (
    <div className="row">
      <strong>{a.name}</strong>
      <span className="muted">{roleName(a)}{a.phone_tail && <> · {t("staff.phoneTail", { tail: localDigits(a.phone_tail, lang) })}</>}</span>
    </div>
  );
  const add = (e: FormEvent) => {
    e.preventDefault();
    const body: StaffCreateBody = { role, name: name.trim(), phone: toAsciiDigits(phone.trim()) };
    act.run(() => api.request("POST", "/admin/staff", { body })).then((ok) => {
      if (!ok) return;
      setDone(t("staff.added", { name: body.name }));
      setName("");
      setPhone("");
    });
  };
  return (
    <>
      <h1>{t("nav.staff")}</h1>
      <p className="notice">{t("staff.intro")}</p>
      {done && <p className="ok-note" role="status">{done}</p>}
      <ErrorNote error={act.error} />
      <Section id="staff-pending" title={t("staff.pending")}>
        {pending.loading && !pending.data ? <Loading /> : <ErrorNote error={pending.error} />}
        {pending.data?.length === 0 && <p className="muted">{t("staff.nonePending")}</p>}
        <ul className="list">
          {pending.data?.map((a) => (
            <li key={a.id} className="card stack">
              {line(a)}
              <div className="actions"><button type="button" className="btn-primary" disabled={act.busy} onClick={() => setApproving(a)}>{t("cr.approve")}</button></div>
            </li>
          ))}
        </ul>
      </Section>
      <Section id="staff-add" title={t("staff.addTitle")}>
        <form onSubmit={add} className="card" noValidate>
          <div className="field">
            <label htmlFor="staff-role">{t("audit.role")}</label>
            <select id="staff-role" value={role} onChange={(e) => setRole(e.target.value as StaffCreateBody["role"])}>
              <option value="verifier">{t("role.verifier")}</option>
              <option value="clinical_reviewer">{t("role.clinical_reviewer")}</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="staff-name">{t("login.name")}</label>
            <input id="staff-name" autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="staff-phone">{t("login.phone")}</label>
            <input id="staff-phone" type="tel" inputMode="tel" autoComplete="off" value={phone} aria-describedby="staff-phone-hint" onChange={(e) => setPhone(e.target.value)} />
            <span id="staff-phone-hint" className="hint">{t("staff.phoneHint")}</span>
          </div>
          <button type="submit" className="btn-primary" disabled={act.busy || !name.trim() || !phone.trim()}>{t("staff.add")}</button>
        </form>
      </Section>
      <Section id="staff-active" title={t("staff.active")}>
        {active.data?.length === 0 && <p className="muted">{t("staff.noneActive")}</p>}
        <ul className="list">
          {active.data?.map((a) => (
            <li key={a.id} className="card stack">
              {line(a)}
              {suspending === a.id ? (
                <ReasonForm id={`suspend-${a.id}`} label={t("cr.suspendReason")} submit={t("cr.suspend")} busy={act.busy} onCancel={() => setSuspending(null)}
                            onSubmit={(reason) => act.run(() => api.request("POST", `/admin/users/${a.id}/suspend`, { body: { reason } }))
                              .then(after(t("staff.suspended", { name: a.name })))} />
              ) : (
                <div className="actions"><button type="button" disabled={act.busy} onClick={() => setSuspending(a.id)}>{t("cr.suspend")}</button></div>
              )}
            </li>
          ))}
        </ul>
      </Section>
      <ConfirmDialog open={!!approving} danger={false} title={approving ? t("staff.approveAsk", { name: approving.name, role: roleName(approving) }) : ""}
                     confirmLabel={t("cr.approve")} onCancel={() => setApproving(null)}
                     onConfirm={() => { const a = approving!; setApproving(null);
                       act.run(() => api.request("POST", `/admin/staff/${a.id}/approve`)).then(after(t("staff.approved", { name: a.name }))); }} />
    </>
  );
}

/** M6 drug catalog import: the upload trigger only. The catalog source and its licence are undecided (FRD question 1), so no
 * catalog data ships with the app and the prototype stores nothing it receives. */
export function CatalogPage() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<CatalogImport | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const act = useAction(() => undefined);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const form = new FormData();
    if (file) form.append("file", file, file.name);
    act.run(async () => {
      setResult(await api.request<CatalogImport>("POST", "/catalog/import", { body: form }));
      setFile(null);
      if (input.current) input.current.value = "";
    });
  };
  return (
    <>
      <h1>{t("nav.catalog")}</h1>
      <p className="notice" role="note"><AlertTriangle size={18} aria-hidden="true" /> {t("catalog.licence")}</p>
      <form onSubmit={submit} className="card section" noValidate>
        <div className="field">
          <label htmlFor="catalog-file">{t("catalog.file")}</label>
          <input id="catalog-file" ref={input} type="file" accept=".csv,text/csv" aria-describedby="catalog-hint"
                 onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); }} />
          <span id="catalog-hint" className="hint">{t("catalog.hint")}</span>
        </div>
        <ErrorNote error={act.error} />
        <button type="submit" className="btn-primary" disabled={act.busy || !file}><Upload size={18} aria-hidden="true" />{t("catalog.send")}</button>
      </form>
      {result && (
        <p className="ok-note section" role="status">
          {t("catalog.queued", { file: result.file_name, size: formatNumber(Math.ceil(result.size_bytes / 1024), lang) })}
        </p>
      )}
    </>
  );
}

const ROLES = ["patient", "caregiver", "doctor", "verifier", "clinical_reviewer", "admin"];
const short = (hash: string) => hash.slice(0, 8);

/** C2 audit log, read only: metadata and the hash chain, never PHI or PII. The chain status is the server's verification of the
 * whole log; each row shows its own and its predecessor's hash. Filters run on the server. */
export function AuditPage() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const [action, setAction] = useState("");
  const [result, setResult] = useState("");
  const [role, setRole] = useState("");
  const [query, setQuery] = useState("");
  const log = useLoad(() => api.request<AuditData>("GET", `/audit${query}`), [query]);
  const apply = (e: FormEvent) => {
    e.preventDefault();
    const q = new URLSearchParams(Object.entries({ action: action.trim(), result, role }).filter(([, v]) => v)).toString();
    setQuery(q ? `?${q}` : "");
  };
  const chain = log.data?.chain;
  return (
    <>
      <h1>{t("nav.audit")}</h1>
      <p className="notice">{t("audit.intro")}</p>
      {chain && (chain.status === "intact" ? (
        <p className="ok-note" role="status"><CheckCircle2 size={18} aria-hidden="true" /> {t("audit.intact", {
          n: formatNumber(chain.entries_checked, lang), at: formatDateTime(chain.checked_at, lang) })}</p>
      ) : (
        <p className="error-note" role="alert"><ShieldAlert size={18} aria-hidden="true" /> {t("audit.broken", { id: chain.first_broken_id ?? "?" })}</p>
      ))}
      <form onSubmit={apply} className="card section filters" role="search" aria-label={t("audit.filters")} noValidate>
        <div className="field">
          <label htmlFor="audit-action">{t("audit.action")}</label>
          <input id="audit-action" lang="en" spellCheck={false} value={action} aria-describedby="audit-action-hint" onChange={(e) => setAction(e.target.value)} />
          <span id="audit-action-hint" className="hint">{t("audit.actionHint")}</span>
        </div>
        <div className="field">
          <label htmlFor="audit-result">{t("audit.result")}</label>
          <select id="audit-result" value={result} onChange={(e) => setResult(e.target.value)}>
            <option value="">{t("audit.any")}</option>
            <option value="allow">{t("audit.allow")}</option>
            <option value="deny">{t("audit.deny")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="audit-role">{t("audit.role")}</label>
          <select id="audit-role" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">{t("audit.any")}</option>
            {ROLES.map((r) => <option key={r} value={r}>{t(`role.${r}` as Key)}</option>)}
          </select>
        </div>
        <button type="submit" className="btn-primary">{t("audit.apply")}</button>
      </form>
      {log.loading && !log.data ? <Loading /> : <ErrorNote error={log.error} />}
      {log.data && (log.data.entries.length === 0 ? <p className="muted section">{t("audit.none")}</p> : (
        // a wide table scrolls inside its own region, never the page (WCAG reflow allows it for data tables)
        <div className="table-wrap section" role="region" aria-labelledby="audit-caption" tabIndex={0}>
          <table>
            <caption id="audit-caption">{t("audit.caption")}</caption>
            <thead>
              <tr>{(["audit.at", "audit.role", "audit.actor", "audit.colAction", "audit.purpose", "audit.result", "audit.reason", "audit.patient",
                "audit.hashes"] as Key[]).map((k) => <th key={k} scope="col">{t(k)}</th>)}</tr>
            </thead>
            <tbody>
              {log.data.entries.map((e) => (
                <tr key={e.id}>
                  <td>{formatDateTime(e.at, lang)}</td>
                  <td>{e.actor_role ? t(`role.${e.actor_role}` as Key) : "—"}</td>
                  <td className="mono" lang="en">{e.actor_ref ?? "—"}</td>
                  <td className="mono" lang="en">{e.action}</td>
                  <td className="mono" lang="en">{e.purpose ?? "—"}</td>
                  <td>{t(e.result === "allow" ? "audit.allow" : "audit.deny")}</td>
                  <td>{e.reason === "free_text_hidden" ? t("audit.textHidden") : <span className="mono" lang="en">{e.reason ?? "—"}</span>}</td>
                  <td className="mono" lang="en">{e.patient_ref ?? "—"}</td>
                  <td className="mono" lang="en"><span className="sr-only">{t("audit.prev")} </span>{short(e.prev_hash)} → {short(e.entry_hash)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </>
  );
}

const DOC_STATUSES: DocStatus[] = ["uploaded", "extracting", "needs_review", "extraction_failed", "verified", "rejected"];
const WORKER_KEYS: Array<keyof WorkerMetrics["worker"]> = ["due", "in_flight", "lease_expired", "waiting_backoff", "failed", "failed_retryable",
  "failed_permanent", "failed_budget_exhausted", "failed_no_retry_last_hour", "due_over_15_minutes", "attempts_open_runs", "ocr_executions_total"];

/** D13 worker and queue metrics (GET /internal/metrics, admin): counts only, read now; Refresh reads again. The operator alerts
 * themselves are the server's (workers/monitoring.py); this page only points out an expired lease, the D13 "> 0" condition. */
export function MetricsPage() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const metrics = useLoad(() => api.request<WorkerMetrics>("GET", "/internal/metrics"), []);
  const m = metrics.data;
  return (
    <>
      <div className="row">
        <h1>{t("nav.metrics")}</h1>
        <button type="button" onClick={metrics.reload} disabled={metrics.loading}><RefreshCw size={18} aria-hidden="true" />{t("met.refresh")}</button>
      </div>
      {m && <p className="muted" role="status">{t("met.at", { at: formatDateTime(m.at, lang) })}</p>}
      {metrics.loading && !m ? <Loading /> : <ErrorNote error={metrics.error} />}
      {m && m.worker.lease_expired > 0 && (
        <div className="status-banner suspended" role="alert">
          <AlertTriangle size={20} aria-hidden="true" /><span>{t("met.leaseAlert", { n: formatNumber(m.worker.lease_expired, lang) })}</span>
        </div>
      )}
      {m && (
        <div className="summary-grid">
          <Section id="met-docs" title={t("met.documents")}>
            <dl className="metrics">
              {DOC_STATUSES.map((s) => <div key={s}><dt>{t(`status.${s}`)}</dt><dd>{formatNumber(m.documents[s], lang)}</dd></div>)}
            </dl>
          </Section>
          <Section id="met-worker" title={t("met.worker")}>
            <dl className="metrics">
              {WORKER_KEYS.map((k) => <div key={k}><dt>{t(`met.${k}` as Key)}</dt><dd>{formatNumber(m.worker[k], lang)}</dd></div>)}
            </dl>
          </Section>
        </div>
      )}
    </>
  );
}
