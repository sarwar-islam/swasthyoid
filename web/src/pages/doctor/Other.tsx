import { Siren } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { EmergencySession } from "../../api/types";
import { ErrorNote, Loading, Section } from "../../components/ui";
import { localDigits, toAsciiDigits, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useSession } from "../../session";
import { clock, StatusChipStaff, useMe, useOpenPatients, useSecondsLeft } from "./doctor";
import { AlertsList } from "./Workspace";

/** M6 alerts for every patient opened in this session whose consent covers safety information. */
export function AllAlerts() {
  const { t } = useI18n();
  const { open } = useOpenPatients();
  const covered = open.filter((c) => c.allowed_categories.includes("safety") && c.expires_at && Date.parse(c.expires_at) > Date.now());
  return (
    <>
      <h1>{t("nav.alerts")}</h1>
      <p className="muted">{t("al.allPatients")}</p>
      {covered.length === 0 && <p className="muted">{t("open.none")}</p>}
      {covered.map((c) => (
        <Section key={c.id} id={`alerts-${c.patient_id}`} title={c.health_id}>
          <AlertsList patientId={c.patient_id} base={`/doctor/patients/${c.patient_id}`} canOpenDocs={c.allowed_categories.includes("documents")} />
        </Section>
      ))}
    </>
  );
}

/** M1: the BMDC credential and its status (pending -> verified -> suspended; an admin decides). */
export function Credentials() {
  const { t } = useI18n();
  const { api } = useSession();
  const me = useMe();
  const [number, setNumber] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.request("POST", "/credentials", { body: { type: "BMDC", number: number.trim() } });
      setDone(true);
      me.reload();
    } catch (err) {
      setError(err);
    }
  };
  if (!me.data) return me.loading ? <Loading /> : <ErrorNote error={me.error} />;
  const cred = me.data.credential;
  return (
    <>
      <h1>{t("cred.title")}</h1>
      <div className="card stack">
        <p><strong>{me.data.name}</strong> <StatusChipStaff status={me.data.status} /></p>
        {cred && <p>{t("cred.current")}: <span className="mono" lang="en">{cred.number}</span> · {t("cred.status")}: <StatusChipStaff status={cred.status} /></p>}
      </div>
      {done && <p className="ok-note section" role="status">{t("cred.submitted")}</p>}
      {!cred && (
        <form onSubmit={submit} className="card section" noValidate>
          <div className="field">
            <label htmlFor="bmdc">{t("cred.number")}</label>
            <input id="bmdc" className="mono" lang="en" autoComplete="off" value={number} onChange={(e) => setNumber(e.target.value)} />
          </div>
          <ErrorNote error={error} />
          <button type="submit" className="btn-primary" disabled={!number.trim()}>{t("cred.submit")}</button>
        </form>
      )}
    </>
  );
}

function Card({ session, onEnd }: { session: EmergencySession; onEnd: () => void }) {
  const { t, lang } = useI18n();
  const left = useSecondsLeft(session.expires_at);
  if (!left) return <p className="notice">{t("bg.expired")}</p>;
  const c = session.card;
  const rows: Array<[Key, string | undefined]> = c ? [
    ["profile.f.blood_group", c.blood_group], ["profile.f.allergies", c.allergies?.join(", ")],
    ["profile.f.active_medications", c.active_medications?.join(", ")], ["profile.f.conditions", c.conditions?.join(", ")],
    ["profile.f.emergency_contacts", c.emergency_contacts?.map((x) => `${x.name} · ${localDigits(x.phone, lang)}`).join(", ")],
  ] : [];
  return (
    <section className="card emergency-card" aria-labelledby="bg-card">
      <h2 id="bg-card"><Siren size={22} aria-hidden="true" />{t("bg.cardTitle")}</h2>
      <p className="muted">{t("bg.expires", { time: clock(left, lang) })}</p>
      {!c ? <p>{t("bg.noProfile")}</p> : (
        <dl className="event">{rows.filter(([, v]) => v !== undefined).map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}><dt>{t(k)}</dt><dd>{v || "—"}</dd></div>
        ))}</dl>
      )}
      <button type="button" onClick={onEnd}>{t("bg.end")}</button>
    </section>
  );
}

/** M10 break-glass (only with VITE_FEATURE_EMERGENCY_ACCESS=1): a reason and a facility are required before the card shows; the
 * card holds only the patient's chosen fields, for a time-boxed session. */
export function BreakGlass() {
  const { t } = useI18n();
  const { api } = useSession();
  const [healthId, setHealthId] = useState("");
  const [reason, setReason] = useState("");
  const [facility, setFacility] = useState("");
  const [missing, setMissing] = useState(false);
  const [session, setSession] = useState<EmergencySession | null>(null);
  const [error, setError] = useState<unknown>(null);
  const open = async (e: FormEvent) => {
    e.preventDefault();
    if (!reason.trim() || !facility.trim()) {
      setMissing(true);
      return;
    }
    setError(null);
    try {
      setSession(await api.request<EmergencySession>("POST", "/emergency/access",
        { body: { health_id: toAsciiDigits(healthId.trim().toUpperCase()), reason: reason.trim(), facility: facility.trim() } }));
    } catch (err) {
      setError(err);
    }
  };
  return (
    <>
      <h1>{t("bg.title")}</h1>
      <p className="notice">{t("bg.intro")}</p>
      {session ? <Card session={session} onEnd={() => setSession(null)} /> : (
        <form onSubmit={open} className="card section" noValidate>
          <div className="field"><label htmlFor="bg-id">{t("req.healthId")}</label>
            <input id="bg-id" className="mono" lang="en" autoComplete="off" value={healthId} onChange={(e) => setHealthId(e.target.value)} /></div>
          <div className="field"><label htmlFor="bg-reason">{t("bg.reason")}</label>
            <textarea id="bg-reason" rows={3} required value={reason} aria-invalid={missing && !reason.trim()} onChange={(e) => setReason(e.target.value)} /></div>
          <div className="field"><label htmlFor="bg-facility">{t("bg.facility")}</label>
            <input id="bg-facility" required value={facility} aria-invalid={missing && !facility.trim()} onChange={(e) => setFacility(e.target.value)} /></div>
          {missing && <p className="error-note" role="alert">{t("bg.required")}</p>}
          <ErrorNote error={error} />
          <button type="submit" className="btn-danger">{t("bg.open")}</button>
        </form>
      )}
    </>
  );
}
