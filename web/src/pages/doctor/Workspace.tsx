import { AlertOctagon, Clock, Search as SearchIcon, ShieldCheck, UserRound } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router";
import { ApiError, type Client } from "../../api/client";
import type { DoctorConsent, DocumentView, SafetyAlert, SafetyCheck, SearchHit, Summary as SummaryData, VitalThresholds } from "../../api/types";
import { ErrorNote, Loading, Reviewed, Section } from "../../components/ui";
import { formatDate, formatDateTime, formatNumber, toAsciiDigits, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { TimelineView } from "../patient/Timeline";
import { useLoad, useSession } from "../../session";
import { clock, useOpenPatients, useSecondsLeft } from "./doctor";

interface Ctx {
  consent: DoctorConsent;
  base: string;
}
const allows = (c: DoctorConsent, category: "timeline" | "documents" | "safety") => c.allowed_categories.includes(category);

/** The persistent patient context bar: who, what the consent covers, and the exact time left. Content goes away at expiry. */
function ContextBar({ consent, left }: { consent: DoctorConsent; left: number }) {
  const { t, lang } = useI18n();
  return (
    <div className={`context-bar${left ? "" : " expired"}`} role="region" aria-label={t("ws.record")}>
      <span><UserRound size={18} aria-hidden="true" /> {t("bar.patient")} <strong className="mono" lang="en">{consent.health_id}</strong></span>
      <span><ShieldCheck size={18} aria-hidden="true" /> {t("bar.allowed", { what: consent.allowed_categories.map((c) => t(`cat.${c}` as Key)).join(", ") })}</span>
      <span aria-live="off"><Clock size={18} aria-hidden="true" /> {left ? t("bar.expires", { time: clock(left, lang) }) : t("bar.expired")}</span>
    </div>
  );
}

/** One patient's record, only under an active consent this doctor confirmed in this session. Sections the consent does not cover
 * are not offered (and the server refuses them anyway). */
export function Workspace() {
  const { pid = "" } = useParams();
  const { t } = useI18n();
  const consent = useOpenPatients().open.find((c) => c.patient_id === pid);
  const left = useSecondsLeft(consent?.expires_at ?? null);
  if (!consent) return <><h1>{t("ws.record")}</h1><p className="notice">{t("ws.unknown")}</p></>;
  const base = `/doctor/patients/${pid}`;
  const tabs: Array<[string, Key, boolean]> = [
    [base, "ws.summary", allows(consent, "timeline")], [`${base}/timeline`, "tl.title", allows(consent, "timeline")],
    [`${base}/search`, "ws.search", allows(consent, "timeline")], [`${base}/alerts`, "nav.alerts", allows(consent, "safety")],
    [`${base}/thresholds`, "ws.thresholds", allows(consent, "safety")],
  ];
  return (
    <>
      <ContextBar consent={consent} left={left} />
      <h1>{t("ws.record")}</h1>
      {left ? (
        <>
          <nav aria-label={t("ws.sections")} className="tabs-nav">
            {tabs.filter(([, , ok]) => ok).map(([to, label]) => <NavLink key={to} to={to} end>{t(label)}</NavLink>)}
          </nav>
          <Outlet context={{ consent, base } satisfies Ctx} />
        </>
      ) : <p className="notice">{t("bar.expired")}</p>}
    </>
  );
}

const useCtx = () => useOutletContext<Ctx>();

function Cite({ ids, base }: { ids: string[]; base: string }) {
  const { t, lang } = useI18n();
  return <>{ids.map((id, i) => (
    <Link key={id} className="cite" to={`${base}/timeline#event-${id}`} aria-label={t("sum.cite", { n: formatNumber(i + 1, lang) })}>
      [{formatNumber(i + 1, lang)}]
    </Link>
  ))}</>;
}

/** M5: structured sections, each sentence with clickable citations to its events; the template mode is said plainly; home vitals
 * sit in their own "reported by patient, not verified" section and never mix with verified facts. */
export function SummaryPage() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const { consent, base } = useCtx();
  const summary = useLoad(() => api.request<SummaryData>("GET", `/patients/${consent.patient_id}/summary`), [consent.patient_id]);
  if (summary.loading) return <Loading />;
  if (!summary.data) return <ErrorNote error={summary.error} />;
  const s = summary.data;
  return (
    <>
      <p className={`mode-badge ${s.mode}`}>{t(s.mode === "template" ? "sum.template" : "sum.llm")} · {t("sum.generated", { date: formatDate(s.generated_at, lang) })}</p>
      {s.fallback_reason && <p className="notice">{t("sum.fallback")}</p>}
      <p className="muted">{t("sum.asWritten")}</p>
      <div className="summary-grid">
        {s.sections.map((section) => (
          <Section key={section.id} id={`sum-${section.id}`} title={t(`sum.s.${section.id}` as Key)}>
            {section.note === "not_recorded" ? <p className="muted">{t("sum.notRecorded")}</p>
              : section.sentences.length === 0 ? <p className="muted">{t("sum.none")}</p> : (
              // values as written keep their own digits (owner decision 2026-11-17)
              <ul className="cited">{section.sentences.map((x, i) => <li key={i}><bdi>{x.text}</bdi> <Cite ids={x.citations} base={base} /></li>)}</ul>
            )}
            {section.truncated > 0 && <p className="muted">{t("sum.truncated", { n: formatNumber(section.truncated, lang) })}</p>}
          </Section>
        ))}
      </div>
      <section className="card reported-section" aria-labelledby="sum-reported">
        <h2 id="sum-reported"><UserRound size={20} aria-hidden="true" />{t("sum.reported")}</h2>
        <p className="muted">{t("sum.reportedNote")}</p>
        {s.patient_reported.length === 0 ? <p className="muted">{t("sum.none")}</p> : (
          <ul className="cited">{s.patient_reported.map((x, i) => <li key={i}><bdi>{x.text}</bdi> <Cite ids={x.citations} base={base} /></li>)}</ul>
        )}
      </section>
    </>
  );
}

export function DoctorTimeline() {
  const { consent } = useCtx();
  return <TimelineView patientId={consent.patient_id} docBase={allows(consent, "documents") ? `/doctor/patients/${consent.patient_id}/documents` : null} />;
}

/** M5 search: keyword, inside the consent only (the server filters by patient and categories); results are events, not answers. */
export function SearchPage() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const { consent, base } = useCtx();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const search = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      setHits(await api.request<SearchHit[]>("GET", `/patients/${consent.patient_id}/search?q=${encodeURIComponent(q.trim())}`));
    } catch (err) {
      setError(err);
    }
  };
  return (
    <>
      <form onSubmit={search} role="search" className="card" noValidate>
        <div className="field">
          <label htmlFor="q">{t("srch.label")}</label>
          <input id="q" type="search" value={q} onChange={(e) => setQ(e.target.value)} aria-describedby="q-hint" />
          <span id="q-hint" className="hint">{t("srch.hint")}</span>
        </div>
        <button type="submit" className="btn-primary" disabled={!q.trim()}><SearchIcon size={18} aria-hidden="true" />{t("ws.search")}</button>
      </form>
      <ErrorNote error={error} />
      {hits && (hits.length === 0 ? <p className="muted section">{t("srch.none")}</p> : (
        <ul className="list section">
          {hits.map((h) => (
            <li key={h.event_id} className="card">
              <p><strong>{t(`tl.${h.event_type}` as Key)}</strong> · {formatDate(h.date, lang)}</p>
              <p><bdi>{h.snippet}</bdi></p>
              <Link to={`${base}/timeline#event-${h.event_id}`}>{t("srch.event")}</Link>
            </li>
          ))}
        </ul>
      ))}
    </>
  );
}

export function SeverityChip({ severity }: { severity: SafetyAlert["severity"] }) {
  const { t } = useI18n();
  return <span className={`chip sev-${severity}`}><AlertOctagon size={14} aria-hidden="true" />{t(`al.sev.${severity}` as Key)}</span>;
}

/** M6: alerts raised when a prescription was verified. Only the treating doctor, under an active consent with the safety category,
 * acknowledges or overrides; an override needs a reason, here and on the server. */
export function AlertsList({ patientId, base, canOpenDocs }: { patientId: string; base: string; canOpenDocs: boolean }) {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const alerts = useLoad(() => api.request<SafetyAlert[]>("GET", `/patients/${patientId}/safety-alerts`), [patientId]);
  const [overriding, setOverriding] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function ack(alert: SafetyAlert, action: "acknowledge" | "override") {
    if (action === "override" && !reason.trim()) {
      setMissing(true);
      return;
    }
    setError(null);
    try {
      await api.request("POST", `/safety/alerts/${alert.id}/ack`, { body: { action, reason: action === "override" ? reason.trim() : undefined } });
      setOverriding(null);
      setReason("");
      setMissing(false);
      alerts.reload();
    } catch (e) {
      setError(e);
    }
  }

  if (alerts.loading && !alerts.data) return <Loading />;
  if (!alerts.data) return <ErrorNote error={alerts.error} />;
  return (
    <>
      <p className="notice">{t("al.notDiagnosis")}</p>
      <ErrorNote error={error} />
      {alerts.data.length === 0 && <p className="muted">{t("al.none")}</p>}
      <ul className="list">
        {alerts.data.map((a) => (
          <li key={a.id} className={`card alert-item sev-${a.severity}`}>
            <div className="row"><SeverityChip severity={a.severity} /><span className="muted">{t("al.rule")} <span className="mono" lang="en">{a.rule_id}</span></span></div>
            <Reviewed text={a.explanation} />
            <p className="muted">{t("al.evidence")}: <Cite ids={a.evidence_event_ids} base={base} /> · {formatDate(a.created_at, lang)}</p>
            {canOpenDocs && <Link to={`${base}/documents/${a.source_document_id}`}>{t("al.source")}</Link>}
            {a.status === "open" ? (
              overriding === a.id ? (
                <form className="stack section" onSubmit={(e) => { e.preventDefault(); ack(a, "override"); }} noValidate>
                  <div className="field">
                    <label htmlFor={`reason-${a.id}`}>{t("al.reason")}</label>
                    <textarea id={`reason-${a.id}`} rows={3} required value={reason} aria-invalid={missing}
                              aria-describedby={missing ? `reason-err-${a.id}` : undefined}
                              onChange={(e) => { setReason(e.target.value); setMissing(false); }} />
                    {missing && <span id={`reason-err-${a.id}`} className="error-note" role="alert">{t("al.reasonRequired")}</span>}
                  </div>
                  <div className="actions">
                    <button type="submit" className="btn-danger">{t("al.submitOverride")}</button>
                    <button type="button" onClick={() => { setOverriding(null); setReason(""); setMissing(false); }}>{t("req.cancel")}</button>
                  </div>
                </form>
              ) : (
                <div className="actions">
                  <button type="button" className="btn-primary" onClick={() => ack(a, "acknowledge")}>{t("al.ack")}</button>
                  <button type="button" onClick={() => { setOverriding(a.id); setReason(""); }}>{t("al.override")}</button>
                </div>
              )
            ) : (
              <p className="ok-note">{a.status === "overridden" ? t("al.overridden", { reason: a.reason ?? "" }) : t("al.acknowledged")}</p>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

/** P3 (D6): each verified prescription's M6 check, next to the alerts. A block or a technical failure is said plainly and never
 * looks like a clean result; unrecognised medications are listed because they were not checked. */
export function ChecksList({ patientId }: { patientId: string }) {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const checks = useLoad(() => api.request<SafetyCheck[]>("GET", `/patients/${patientId}/safety-checks`), [patientId]);
  if (checks.loading && !checks.data) return <Loading />;
  if (!checks.data) return <ErrorNote error={checks.error} />;
  return (
    <section className="card section" aria-labelledby="chk-title">
      <h2 id="chk-title">{t("chk.title")}</h2>
      {checks.data.length === 0 ? <p className="muted">{t("chk.none")}</p> : (
        <ul className="list">
          {checks.data.map((c) => (
            <li key={c.document_id} className={`check-item check-${c.status}`}>
              <p className={c.status === "completed" ? "" : "notice"}>
                <strong>{t(`chk.status.${c.status}` as Key, { n: formatNumber(c.alert_count, lang) })}</strong>
                {c.reason && <> · {t(`chk.reason.${c.reason}` as Key)}</>}
                {c.checked_at && <span className="muted"> · {formatDateTime(c.checked_at, lang)}</span>}
              </p>
              {c.unrecognised.length > 0 && (
                <>
                  <p>{t("chk.unrecognised")}</p>
                  <ul>
                    {c.unrecognised.map((u) => (
                      <li key={u.event_id}>{u.name_as_written ? <bdi>{u.name_as_written}</bdi> : t("chk.unnamed")} · {t(`chk.why.${u.reason}` as Key)}</li>
                    ))}
                  </ul>
                </>
              )}
              {c.not_run.length > 0 && (
                <p className="muted">{t("chk.notRun", { list: c.not_run.map((n) => t(`chk.check.${n.check}` as Key)).join(", ") })}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AlertsPage() {
  const { consent, base } = useCtx();
  return (
    <>
      <AlertsList patientId={consent.patient_id} base={base} canOpenDocs={allows(consent, "documents")} />
      <ChecksList patientId={consent.patient_id} />
    </>
  );
}

/** M13 per-patient threshold overrides (GAP, F6), only under a consent covering `safety`. The server lists the fields a doctor may
 * set; the defaults are the reviewer's approved rules (or REVIEWER-PENDING). The UI holds no number of its own and checks only that
 * a value is a number: the allowed range is the server's. Empty means "use the default". */
export function ThresholdsPage() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const { consent } = useCtx();
  const path = `/patients/${consent.patient_id}/vital-thresholds`;
  const data = useLoad(() => api.request<VitalThresholds>("GET", path), [path]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [bad, setBad] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (data.data) setDraft(Object.fromEntries(data.data.fields.map((f) => [f.key, f.override_value === null ? "" : formatNumber(f.override_value, lang)])));
  }, [data.data, lang]);

  async function save(e: FormEvent) {
    e.preventDefault();
    const current = data.data!;
    const values = Object.fromEntries(current.fields.map((f) => {
      const raw = toAsciiDigits(draft[f.key] ?? "").trim();
      return [f.key, raw === "" ? null : Number(raw)];
    }));
    const wrong = Object.keys(values).filter((k) => values[k] !== null && !(Number.isFinite(values[k]) && (values[k] as number) > 0));
    setBad(wrong);
    setSaved(null);
    setError(null);
    if (wrong.length) return;
    setBusy(true);
    try {
      const next = await api.request<VitalThresholds>("PUT", path, { body: { version: current.version, overrides: values } });
      setSaved(next.version);
      data.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (data.loading && !data.data) return <Loading />;
  if (!data.data) return <ErrorNote error={data.error} />;
  const th = data.data;
  return (
    <form className="stack" onSubmit={save} noValidate>
      <p className="notice">{t("th.note")}</p>
      <p className="muted">
        {t("th.version", { v: formatNumber(th.version, lang) })} · {th.updated_at && th.updated_by_name
          ? t("th.changed", { name: th.updated_by_name, date: formatDateTime(th.updated_at, lang) }) : t("th.unchanged")}
      </p>
      {th.fields.length === 0 && <p className="reviewer-pending">{t("th.noRules")}</p>}
      <ul className="list">
        {th.fields.map((f) => (
          <li key={f.key} className="card stack">
            <Reviewed text={f.label} as="strong" />
            <p className={f.default_value === null ? "reviewer-pending" : "muted"}>
              {f.default_value === null ? t("th.defaultPending") : t("th.default", { value: `${formatNumber(f.default_value, lang)} ${f.unit}` })}
            </p>
            <div className="field">
              <label htmlFor={`th-${f.key}`}>{t("th.override", { unit: f.unit })}</label>
              <input id={`th-${f.key}`} inputMode="decimal" autoComplete="off" value={draft[f.key] ?? ""}
                     aria-invalid={bad.includes(f.key)} aria-describedby={`th-${f.key}-hint${bad.includes(f.key) ? ` th-${f.key}-err` : ""}`}
                     onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))} />
              <span id={`th-${f.key}-hint`} className="hint">{t("th.hint")}</span>
              {bad.includes(f.key) && <span id={`th-${f.key}-err`} className="error-note" role="alert">{t("th.bad")}</span>}
            </div>
          </li>
        ))}
      </ul>
      <ErrorNote error={error} />
      {saved !== null && <p className="ok-note" role="status">{t("th.saved", { v: formatNumber(saved, lang) })}</p>}
      <div className="actions">
        {th.fields.length > 0 && <button type="submit" className="btn-primary" disabled={busy}>{t("th.save")}</button>}
        {error instanceof ApiError && error.code === "version_conflict" && (
          <button type="button" onClick={() => { setError(null); data.reload(); }}>{t("th.reload")}</button>
        )}
      </div>
    </form>
  );
}

function DocImage({ api, id, n }: { api: Client; id: string; n: number }) {
  const { t, lang } = useI18n();
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    api.request<Blob>("GET", `/documents/${id}/images/${n}`, { binary: true })
      .then((b) => { if (typeof URL.createObjectURL === "function") setSrc((url = URL.createObjectURL(b))); }, () => setSrc(null));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [api, id, n]);
  return src ? <img loading="lazy" decoding="async" src={src} alt={t("verify.imageAlt", { n: formatNumber(n, lang) })} /> : <Loading />;
}

/** A source document, view only: the photos, never the unverified extraction (that is the patient's alone). */
export function DoctorDocument() {
  const { docId = "" } = useParams();
  const { t } = useI18n();
  const { api } = useSession();
  const doc = useLoad(() => api.request<DocumentView>("GET", `/documents/${docId}`), [docId]);
  if (!doc.data) return doc.loading ? <Loading /> : <ErrorNote error={doc.error} />;
  return (
    <section className="paper" aria-labelledby="dview">
      <h2 id="dview">{t("dview.title")} · {t(`doc.${doc.data.doc_type}` as Key)}</h2>
      {doc.data.images.map((img) => <DocImage key={img.n} api={api} id={doc.data!.id} n={img.n} />)}
    </section>
  );
}
