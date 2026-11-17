import { FilePlus2, ShieldOff } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import type { EmergencyReview, ReviewedText, Rule, RuleDraftBody, RuleType, Severity } from "../../api/types";
import { ConfirmDialog, ErrorNote, Loading, Reviewed, Section } from "../../components/ui";
import { formatDate, formatDateTime, formatNumber, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";
import { SeverityChip } from "../doctor/Workspace";
import { useAction } from "./console";

const TYPES: RuleType[] = ["ddi", "allergy", "duplicate", "drug_disease", "class_lookback", "vital_threshold", "vital_plausibility",
  "red_flag", "emergency_message"];
const SEVERITIES: Severity[] = ["contraindicated", "major", "moderate", "minor"];

/** A rule's explanation counts as approved text only on an approved version that is not a placeholder; anything else is marked. */
const explanationOf = (r: Rule): ReviewedText => ({ ...r.explanation,
  status: r.status === "approved" && !/^\[(REVIEWER-PENDING|রিভিউয়ার)/.test(r.explanation.en + r.explanation.bn) ? "approved" : "REVIEWER-PENDING" });

function RuleStatusChip({ status }: { status: Rule["status"] }) {
  const { t } = useI18n();
  const style = { draft: "chip-needs_review", approved: "chip-verified", rejected: "chip-extraction_failed", superseded: "" }[status];
  return <span className={`chip ${style}`}>{t(`rule.status.${status}`)}</span>;
}

/** Draft a new rule, or a new version of `initial.rule_id`. The reviewer writes the content; nothing here is a rule until approved. */
function RuleForm({ initial, onDone, onCancel }: { initial: Partial<RuleDraftBody>; onDone: () => void; onCancel: () => void }) {
  const { t } = useI18n();
  const { api } = useSession();
  const [type, setType] = useState<RuleType>(initial.rule_type ?? "ddi");
  const [severity, setSeverity] = useState<Severity | "">(initial.severity ?? "");
  const [definition, setDefinition] = useState(initial.definition ? JSON.stringify(initial.definition, null, 2) : "");
  const [en, setEn] = useState(initial.explanation?.en ?? "");
  const [bn, setBn] = useState(initial.explanation?.bn ?? "");
  const [badJson, setBadJson] = useState(false);
  const act = useAction(onDone);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    let parsed: unknown;
    try {
      parsed = JSON.parse(definition);
    } catch {
      parsed = null;
    }
    const isObject = !!parsed && typeof parsed === "object" && !Array.isArray(parsed);
    setBadJson(!isObject);
    if (!isObject) return;
    act.run(() => api.request("POST", "/rules", { body: { ...(initial.rule_id ? { rule_id: initial.rule_id } : {}), rule_type: type,
      severity: severity || null, definition: parsed as Record<string, unknown>, explanation: { en: en.trim(), bn: bn.trim() } } satisfies RuleDraftBody }));
  };

  return (
    <form onSubmit={submit} className="card" noValidate aria-labelledby="rule-form-title">
      <h2 id="rule-form-title" tabIndex={-1}>{initial.rule_id ? t("rule.newVersionOf", { id: initial.rule_id }) : t("rule.draftTitle")}</h2>
      <div className="field">
        <label htmlFor="rule-type">{t("rule.type")}</label>
        <select id="rule-type" value={type} disabled={!!initial.rule_id} onChange={(e) => setType(e.target.value as RuleType)}>
          {TYPES.map((x) => <option key={x} value={x}>{t(`rule.type.${x}`)}</option>)}
        </select>
      </div>
      <div className="field">
        <label htmlFor="rule-severity">{t("rule.severity")}</label>
        <select id="rule-severity" value={severity} onChange={(e) => setSeverity(e.target.value as Severity | "")}>
          <option value="">{t("rule.noSeverity")}</option>
          {SEVERITIES.map((x) => <option key={x} value={x}>{t(`al.sev.${x}`)}</option>)}
        </select>
      </div>
      <div className="field">
        <label htmlFor="rule-def">{t("rule.definition")}</label>
        <textarea id="rule-def" rows={6} className="mono" lang="en" spellCheck={false} value={definition} aria-invalid={badJson}
                  aria-describedby="rule-def-hint" onChange={(e) => { setDefinition(e.target.value); setBadJson(false); }} />
        <span id="rule-def-hint" className="hint">{t("rule.definitionHint")}</span>
        {badJson && <span className="error-note" role="alert">{t("rule.badJson")}</span>}
      </div>
      <div className="field">
        <label htmlFor="rule-bn">{t("rule.explanationBn")}</label>
        <textarea id="rule-bn" rows={3} lang="bn" value={bn} onChange={(e) => setBn(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="rule-en">{t("rule.explanationEn")}</label>
        <textarea id="rule-en" rows={3} lang="en" value={en} onChange={(e) => setEn(e.target.value)} />
      </div>
      <ErrorNote error={act.error} />
      <div className="actions">
        <button type="submit" className="btn-primary" disabled={act.busy || !definition.trim() || !en.trim() || !bn.trim()}>{t("rule.saveDraft")}</button>
        <button type="button" onClick={onCancel}>{t("req.cancel")}</button>
      </div>
    </form>
  );
}

/** M6/M7/M13 rule registry (FRD M6): every rule type in one list, each version kept; a draft is approved or rejected with a reason.
 * Only approved rules run, on the server. The UI holds no rule of its own. */
export function RulesPage() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const [type, setType] = useState<RuleType | "">("");
  const rules = useLoad(() => api.request<Rule[]>("GET", `/rules${type ? `?type=${type}` : ""}`), [type]);
  const [form, setForm] = useState<Partial<RuleDraftBody> | null>(null);
  const [approving, setApproving] = useState<Rule | null>(null);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  const [saved, setSaved] = useState<Key | null>(null);
  const act = useAction(() => rules.reload());
  const formTop = useRef<HTMLDivElement>(null);

  const list = [...(rules.data ?? [])].sort((a, b) => a.rule_id.localeCompare(b.rule_id) || b.version - a.version);
  const latestApproved = (r: Rule) => r.status === "approved" && !list.some((x) => x.rule_id === r.rule_id && x.status === "draft");
  const openForm = (initial: Partial<RuleDraftBody>) => {
    setForm(initial);
    setSaved(null);
    requestAnimationFrame(() => formTop.current?.querySelector<HTMLElement>("#rule-form-title")?.focus());
  };
  const approve = () => {
    const r = approving!;
    setApproving(null);
    act.run(() => api.request("POST", `/rules/${r.id}/approve`)).then((ok) => ok && setSaved("rule.approved"));
  };
  const reject = (e: FormEvent, r: Rule) => {
    e.preventDefault();
    if (!reason.trim()) {
      setMissing(true);
      return;
    }
    act.run(() => api.request("POST", `/rules/${r.id}/reject`, { body: { reason: reason.trim() } })).then((ok) => {
      if (!ok) return;
      setRejecting(null);
      setReason("");
      setSaved("rule.rejected");
    });
  };

  return (
    <>
      <h1>{t("nav.rules")}</h1>
      <p className="notice">{t("rule.note")}</p>
      <div className="row section">
        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="rule-filter">{t("rule.filter")}</label>
          <select id="rule-filter" value={type} onChange={(e) => setType(e.target.value as RuleType | "")}>
            <option value="">{t("rule.allTypes")}</option>
            {TYPES.map((x) => <option key={x} value={x}>{t(`rule.type.${x}`)}</option>)}
          </select>
        </div>
        {!form && <button type="button" className="btn-primary" onClick={() => openForm({})}><FilePlus2 size={18} aria-hidden="true" />{t("rule.draftTitle")}</button>}
      </div>
      <div ref={formTop} className="section">
        {form && <RuleForm initial={form} onCancel={() => setForm(null)} onDone={() => { setForm(null); setSaved("rule.saved"); rules.reload(); }} />}
      </div>
      {saved && <p className="ok-note" role="status">{t(saved)}</p>}
      <ErrorNote error={act.error} />
      {rules.loading && !rules.data ? <Loading /> : <ErrorNote error={rules.error} />}
      {rules.data?.length === 0 && <p className="muted">{t("rule.none")}</p>}
      <ul className="list section">
        {list.map((r) => (
          <li key={r.id} className="card stack">
            <div className="row">
              <span><strong className="mono" lang="en">{r.rule_id}</strong> · {t("rule.version", { n: formatNumber(r.version, lang) })}</span>
              <RuleStatusChip status={r.status} />
            </div>
            <p className="muted">{t(`rule.type.${r.rule_type}`)}{r.severity && <> · <SeverityChip severity={r.severity} /></>}</p>
            <Reviewed text={explanationOf(r)} />
            <details>
              <summary>{t("rule.definition")}</summary>
              <pre className="mono" lang="en">{JSON.stringify(r.definition, null, 2)}</pre>
            </details>
            <p className="muted">
              {t("rule.by", { name: r.created_by_name, date: formatDate(r.created_at, lang) })}
              {r.reviewed_by_name && r.reviewed_at && <> · {t("rule.reviewedBy", { name: r.reviewed_by_name, date: formatDate(r.reviewed_at, lang) })}</>}
            </p>
            {r.reason && <p>{t("rule.rejectedBecause", { reason: r.reason })}</p>}
            {r.status === "draft" && (rejecting === r.id ? (
              <form className="stack" onSubmit={(e) => reject(e, r)} noValidate>
                <div className="field">
                  <label htmlFor={`reject-${r.id}`}>{t("rule.rejectReason")}</label>
                  <textarea id={`reject-${r.id}`} rows={3} value={reason} aria-invalid={missing} aria-describedby={missing ? `reject-err-${r.id}` : undefined}
                            onChange={(e) => { setReason(e.target.value); setMissing(false); }} />
                  {missing && <span id={`reject-err-${r.id}`} className="error-note" role="alert">{t("common.reasonRequired")}</span>}
                </div>
                <div className="actions">
                  <button type="submit" className="btn-danger" disabled={act.busy}>{t("rule.reject")}</button>
                  <button type="button" onClick={() => { setRejecting(null); setReason(""); setMissing(false); }}>{t("req.cancel")}</button>
                </div>
              </form>
            ) : (
              <div className="actions">
                <button type="button" className="btn-primary" disabled={act.busy} onClick={() => setApproving(r)}>{t("rule.approve")}</button>
                <button type="button" disabled={act.busy} onClick={() => { setRejecting(r.id); setReason(""); setMissing(false); }}>{t("rule.reject")}</button>
              </div>
            ))}
            {latestApproved(r) && !form && (
              <div className="actions">
                <button type="button" onClick={() => openForm({ rule_id: r.rule_id, rule_type: r.rule_type, severity: r.severity, definition: r.definition,
                  explanation: r.explanation })}>{t("rule.newVersion")}</button>
              </div>
            )}
          </li>
        ))}
      </ul>
      <ConfirmDialog open={!!approving} danger={false} title={approving ? t("rule.approveAsk", { id: approving.rule_id, n: formatNumber(approving.version, lang) }) : ""}
                     confirmLabel={t("rule.approve")} onCancel={() => setApproving(null)} onConfirm={approve} />
    </>
  );
}

function ReviewItem({ item, onDone }: { item: EmergencyReview; onDone: () => void }) {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const [note, setNote] = useState("");
  const [missing, setMissing] = useState(false);
  const act = useAction(onDone);
  const decide = (decision: "justified" | "unjustified") => {
    if (decision === "unjustified" && !note.trim()) {
      setMissing(true);
      return;
    }
    act.run(() => api.request("POST", `/admin/emergency/reviews/${item.id}/review`, { body: { decision, note: note.trim() || undefined } }));
  };
  const noteId = `note-${item.id}`;
  return (
    <li className="card stack">
      <div className="row">
        <strong>{item.doctor_name}</strong>
        <span className={`chip ${item.status === "review_pending" ? "chip-needs_review" : item.status === "justified" ? "chip-verified" : "chip-extraction_failed"}`}>
          {t(`bgr.status.${item.status}`)}
        </span>
      </div>
      <dl className="facts">
        <dt>{t("bg.facility")}</dt><dd>{item.facility}</dd>
        <dt>{t("bg.reason")}</dt><dd>{item.reason}</dd>
        <dt>{t("bgr.when")}</dt><dd>{formatDateTime(item.opened_at, lang)} – {formatDateTime(item.closed_at, lang)}</dd>
        <dt>{t("bgr.fields")}</dt><dd>{item.fields_shown.length ? item.fields_shown.map((f) => t(`profile.f.${f}`)).join(", ") : t("bgr.noFields")}</dd>
      </dl>
      {item.status === "review_pending" ? (
        <>
          <div className="field">
            <label htmlFor={noteId}>{t("bgr.note")}</label>
            <textarea id={noteId} rows={3} value={note} aria-invalid={missing} aria-describedby={`${noteId}-hint${missing ? ` ${noteId}-err` : ""}`}
                      onChange={(e) => { setNote(e.target.value); setMissing(false); }} />
            <span id={`${noteId}-hint`} className="hint">{t("bgr.noteHint")}</span>
            {missing && <span id={`${noteId}-err`} className="error-note" role="alert">{t("common.reasonRequired")}</span>}
          </div>
          <ErrorNote error={act.error} />
          <div className="actions">
            <button type="button" className="btn-primary" disabled={act.busy} onClick={() => decide("justified")}>{t("bgr.justified")}</button>
            <button type="button" className="btn-danger" disabled={act.busy} onClick={() => decide("unjustified")}>{t("bgr.unjustified")}</button>
          </div>
        </>
      ) : (
        <>
          {item.note && <p>{t("bgr.noteWas", { note: item.note })}</p>}
          {item.capability_suspended && <p className="error-note" role="status"><ShieldOff size={18} aria-hidden="true" />{t("bgr.suspended", { name: item.doctor_name })}</p>}
        </>
      )}
    </li>
  );
}

/** M10 post-hoc review of break-glass sessions (only with VITE_FEATURE_EMERGENCY_ACCESS=1). The reviewer sees who, why, where,
 * when and which card fields were shown, never the patient or the values. Unjustified suspends the doctor's emergency capability. */
export function ReviewsPage() {
  const { t } = useI18n();
  const { api } = useSession();
  const reviews = useLoad(() => api.request<EmergencyReview[]>("GET", "/admin/emergency/reviews"), []);
  const pending = reviews.data?.filter((r) => r.status === "review_pending") ?? [];
  const done = reviews.data?.filter((r) => r.status !== "review_pending") ?? [];
  return (
    <>
      <h1>{t("nav.reviews")}</h1>
      <p className="notice">{t("bgr.intro")}</p>
      {reviews.loading && !reviews.data ? <Loading /> : <ErrorNote error={reviews.error} />}
      <Section id="bgr-pending" title={t("bgr.pending")}>
        {reviews.data && pending.length === 0 && <p className="muted">{t("bgr.nonePending")}</p>}
        <ul className="list">{pending.map((r) => <ReviewItem key={r.id} item={r} onDone={reviews.reload} />)}</ul>
      </Section>
      {done.length > 0 && (
        <Section id="bgr-done" title={t("bgr.done")}>
          <ul className="list">{done.map((r) => <ReviewItem key={r.id} item={r} onDone={reviews.reload} />)}</ul>
        </Section>
      )}
    </>
  );
}
