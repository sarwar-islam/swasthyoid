import { AlertOctagon, PenLine } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { ApiError } from "../../api/client";
import type { VitalContext, VitalEntry, VitalReading, VitalSaved, VitalType, VitalUnit } from "../../api/types";
import { ErrorNote, Loading, ProvenanceBadge, Reviewed, Section } from "../../components/ui";
import { formatDate, localDigits, toAsciiDigits, useI18n } from "../../i18n/i18n";
import { useLoad, useSession } from "../../session";

const CONTEXTS: Record<VitalType, VitalContext[]> = { bp: ["home", "resting"], glucose: ["fasting", "post_meal", "random"] };
const UNITS: Record<VitalType, VitalUnit[]> = { bp: ["mmHg"], glucose: ["mmol/L", "mg/dL"] };
const INTEGER = /^\d{1,3}$/;
const DECIMAL = /^\d{1,4}(\.\d{1,2})?$/;

function localNow(): string {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

/** The server's verdict on a saved reading. The client never judges a value: no threshold lives in the frontend (FRD M13). A
 * reading is never called safe; a critical one always shows the escalation message and the way to the emergency card. */
function Result({ saved }: { saved: VitalSaved }) {
  const { t } = useI18n();
  const { level, message } = saved.evaluation;
  if (level === "critical") {
    return (
      <section className="card alert-critical" role="alert" aria-labelledby="critical-title">
        <h2 id="critical-title"><AlertOctagon size={24} aria-hidden="true" />{t("vitals.critical")}</h2>
        {message && <Reviewed text={message} />}
        <div className="actions">
          <a className="btn btn-emergency" href="tel:999">{t("emergency.call")}</a>
          <Link className="btn" to="/patient/emergency">{t("emergency.open")}</Link>
        </div>
      </section>
    );
  }
  return (
    <div className="card result" role="status">
      <p><strong>{t("vitals.saved")}</strong> <ProvenanceBadge value="patient_reported" /></p>
      {level === "flagged" && <><p>{t("vitals.flagged")}</p>{message && <Reviewed text={message} />}</>}
      {level === "within_range" && <p>{t("vitals.within")}</p>}
      {level === "not_evaluated" && <><p>{t("vitals.notEvaluated")}</p><Link to="/patient/emergency">{t("emergency.open")}</Link></>}
    </div>
  );
}

/** M13 home vitals: manual BP and glucose, saved as patient_reported; plausibility confirmation; corrections keep the original. */
export function Vitals() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const readings = useLoad(() => api.request<VitalReading[]>("GET", "/vitals"), []);
  const [type, setType] = useState<VitalType>("bp");
  const [sys, setSys] = useState("");
  const [dia, setDia] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState<VitalUnit>("mmHg");
  const [context, setContext] = useState<VitalContext>("home");
  const [when, setWhen] = useState(localNow);
  const [reason, setReason] = useState("");
  const [reasonMissing, setReasonMissing] = useState(false);
  // P6 safeguard 4: one id per reading, kept across retries until it is saved, so a resend never makes a second reading
  const [readingId, setReadingId] = useState(() => crypto.randomUUID());
  const [correcting, setCorrecting] = useState<VitalReading | null>(null);
  const [confirmFor, setConfirmFor] = useState<VitalEntry | null>(null);
  const [saved, setSaved] = useState<VitalSaved | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [invalid, setInvalid] = useState(false);
  const form = useRef<HTMLFormElement>(null);

  const choose = (next: VitalType) => {
    setType(next);
    setUnit(UNITS[next][0]);
    setContext(CONTEXTS[next][0]);
  };

  async function send(entry: VitalEntry) {
    setError(null);
    setSaved(null);
    try {
      const path = correcting ? `/vitals/${correcting.id}/correct` : "/vitals";
      const result = await api.request<VitalSaved>("POST", path, { body: entry });
      setConfirmFor(null);
      setCorrecting(null);
      setSys(""); setDia(""); setValue(""); setReason("");
      setReadingId(crypto.randomUUID());
      setSaved(result);
      readings.reload();
    } catch (e) {
      if (e instanceof ApiError && e.code === "confirmation_required") setConfirmFor(entry);
      else setError(e);
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const [s, d, v] = [sys, dia, value].map((x) => toAsciiDigits(x.trim()));
    const ok = type === "bp" ? INTEGER.test(s) && INTEGER.test(d) : DECIMAL.test(v); // the data type only; no clinical range
    const missing = !!correcting && !reason.trim();
    setInvalid(!ok);
    setReasonMissing(missing);
    if (!ok || missing) return;
    send({ id: readingId, vital_type: type, value: type === "bp" ? `${s}/${d}` : v, unit, context,
           measured_at: new Date(when).toISOString(), ...(correcting ? { reason: reason.trim() } : {}) });
  };

  const startCorrection = (r: VitalReading) => {
    setCorrecting(r);
    setReason(""); setReasonMissing(false);
    choose(r.vital_type);
    setUnit(r.unit);
    setContext(r.context);
    if (r.vital_type === "bp") {
      const [s, d] = r.value.split("/");
      setSys(s); setDia(d);
    } else setValue(r.value);
    setSaved(null);
    form.current?.scrollIntoView?.({ block: "start" });
  };

  const all = readings.data ?? [];
  const replaced = new Set(all.map((r) => r.supersedes_reading_id).filter(Boolean));
  const older = (r: VitalReading) => {
    const chain: VitalReading[] = [];
    for (let p = all.find((x) => x.id === r.supersedes_reading_id); p; p = all.find((x) => x.id === p!.supersedes_reading_id)) chain.push(p);
    return chain;
  };
  // the value as entered keeps its own digits in the Bangla UI (owner digits decision); the label is translated
  const show = (r: VitalReading) => <><bdi>{r.value} {r.unit}</bdi> · {t(`vitals.ctx.${r.context}`)}</>;

  return (
    <>
      <h1>{t("vitals.title")}</h1>
      <p className="notice">{t("vitals.intro")}</p>
      {saved && <Result saved={saved} />}

      <form ref={form} onSubmit={onSubmit} className="card section" noValidate aria-describedby={invalid ? "vital-invalid" : undefined}>
        {correcting && (
          <div className="row"><p className="notice">{t("vitals.correcting")}</p>
            <button type="button" onClick={() => setCorrecting(null)}>{t("vitals.cancelCorrect")}</button></div>
        )}
        <fieldset className="segmented">
          <legend>{t("vitals.type")}</legend>
          {(["bp", "glucose"] as const).map((v) => (
            <label key={v}><input type="radio" name="vital-type" value={v} checked={type === v} disabled={!!correcting}
                                  onChange={() => choose(v)} />{t(v === "bp" ? "vitals.bp" : "vitals.glucose")}</label>
          ))}
        </fieldset>
        {type === "bp" ? (
          <div className="bp-pair">
            <div className="field"><label htmlFor="sys">{t("vitals.systolic")}</label>
              <input id="sys" inputMode="numeric" value={sys} onChange={(e) => setSys(e.target.value)} aria-invalid={invalid} /></div>
            <div className="field"><label htmlFor="dia">{t("vitals.diastolic")}</label>
              <input id="dia" inputMode="numeric" value={dia} onChange={(e) => setDia(e.target.value)} aria-invalid={invalid} /></div>
          </div>
        ) : (
          <div className="field"><label htmlFor="value">{t("vitals.value")}</label>
            <input id="value" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} aria-invalid={invalid} /></div>
        )}
        {invalid && <p id="vital-invalid" className="error-note" role="alert">{t("vitals.numbersOnly")}</p>}
        <div className="field">
          <label htmlFor="unit">{t("vitals.unit")}</label>
          <select id="unit" value={unit} onChange={(e) => setUnit(e.target.value as VitalUnit)}>
            {UNITS[type].map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="context">{t("vitals.context")}</label>
          <select id="context" value={context} onChange={(e) => setContext(e.target.value as VitalContext)}>
            {CONTEXTS[type].map((c) => <option key={c} value={c}>{t(`vitals.ctx.${c}`)}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="when">{t("vitals.when")}</label>
          <input id="when" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
        </div>
        {correcting && (
          <div className="field">
            <label htmlFor="reason">{t("vitals.reason")}</label>
            <input id="reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} aria-invalid={reasonMissing}
                   aria-describedby={reasonMissing ? "reason-missing" : undefined} />
            {reasonMissing && <p id="reason-missing" className="error-note" role="alert">{t("err.reason_required")}</p>}
          </div>
        )}
        <ErrorNote error={error} />
        {confirmFor ? (
          <div className="stack" role="alert">
            <p className="error-note">{t("vitals.confirmAsk")}</p>
            <div className="actions">
              <button type="button" onClick={() => setConfirmFor(null)}>{t("vitals.confirmFix")}</button>
              <button type="button" className="btn-primary" onClick={() => send({ ...confirmFor, confirmed: true })}>{t("vitals.confirmYes")}</button>
            </div>
          </div>
        ) : <button type="submit" className="btn-primary">{t("vitals.save")}</button>}
      </form>

      <Section id="readings" title={t("vitals.history")}>
        {readings.loading ? <Loading /> : <ErrorNote error={readings.error} />}
        {!readings.loading && all.length === 0 && <p className="muted">{t("vitals.none")}</p>}
        <ul className="list">
          {all.filter((r) => !replaced.has(r.id)).sort((a, b) => b.measured_at.localeCompare(a.measured_at)).map((r) => (
            <li key={r.id} className="card event patient_reported">
              <div className="row">
                <strong>{t(r.vital_type === "bp" ? "vitals.bp" : "vitals.glucose")} · {formatDate(r.measured_at, lang)}</strong>
                <ProvenanceBadge value="patient_reported" />
              </div>
              <p>{show(r)}</p>
              {r.version > 1 && <p className="muted">{t("tl.corrected", { n: localDigits(String(r.version), lang) })}</p>}
              {r.correction_reason && <p className="muted">{t("vitals.correctedBecause", { reason: r.correction_reason })}</p>}
              {older(r).length > 0 && (
                <details><summary>{t("vitals.older")}</summary>
                  <ul>{older(r).map((o) => <li key={o.id} className="muted">{show(o)}</li>)}</ul></details>
              )}
              <button type="button" onClick={() => startCorrection(r)}><PenLine size={18} aria-hidden="true" />{t("vitals.correct")}</button>
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}
