import { AlertTriangle, Clock, ShieldCheck, UserRound } from "lucide-react";
import { createContext, useContext, useState, type FormEvent, type ReactNode } from "react";
import { Link, Outlet } from "react-router";
import { apiMode } from "../../api";
import { MOCK_CODE } from "../../api/mockConstants";
import type { AssistSession } from "../../api/types";
import { ErrorNote } from "../../components/ui";
import { localDigits, toAsciiDigits, useI18n } from "../../i18n/i18n";
import { useLeaveWarning } from "../../leave";
import { useSession } from "../../session";
import { clock, useMe, useSecondsLeft } from "../doctor/doctor";
import { Capture, DocList } from "../patient/Capture";
import { DocumentPage } from "../patient/Document";

/** The one assisted session, in memory only (like the token): a reload forgets it here, and the server's expiry ends it everywhere.
 * The server stays the judge of every request; this only remembers which patient is in front of the verifier. */
const Assist = createContext<{ session: AssistSession | null; set: (s: AssistSession | null) => void } | null>(null);

function useAssist() {
  const value = useContext(Assist);
  if (!value) throw new Error("useAssist needs the verifier app");
  return value;
}

/** Around every verifier page: a banner while the verifier's own account is not verified, and the session. */
export function VerifierFrame() {
  const { t } = useI18n();
  const me = useMe();
  const [session, set] = useState<AssistSession | null>(null);
  useLeaveWarning("assist", session !== null);
  const status = me.data?.status;
  return (
    <Assist.Provider value={{ session, set }}>
      {status && status !== "verified" && (
        <div className={`status-banner ${status}`} role="status">
          <AlertTriangle size={20} aria-hidden="true" /><span>{t(status === "suspended" ? "dstatus.suspended" : "vf.notVerified")}</span>
        </div>
      )}
      <Outlet />
    </Assist.Provider>
  );
}

/** The session bar (whose record, the patient's code, the time left) above `children`; without a live session, the way back to
 * the start. When the time runs out the page content goes away. */
function WithSession({ children }: { children: ReactNode }) {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const { session, set } = useAssist();
  const left = useSecondsLeft(session?.expires_at ?? null);
  if (!session) {
    return <><h1>{t("portal.verifier")}</h1><p className="notice">{t("vf.noSession")}</p><Link to="/verifier">{t("vf.start")}</Link></>;
  }
  // ending fails closed: the session is forgotten here whatever the server answers (it also expires there)
  const end = () => api.request("POST", `/verifier/sessions/${session.id}/end`).catch(() => undefined).finally(() => set(null));
  return (
    <>
      <div className={`context-bar${left ? "" : " expired"}`} role="region" aria-label={t("vf.session")}>
        <span><UserRound size={18} aria-hidden="true" /> {t("bar.patient")} <strong className="mono" lang="en">{session.health_id}</strong></span>
        <span><ShieldCheck size={18} aria-hidden="true" /> {t("vf.present")}</span>
        <span><Clock size={18} aria-hidden="true" /> {left ? t("vf.left", { time: clock(left, lang) }) : t("vf.ended")}</span>
        <button type="button" onClick={end}>{t("vf.end")}</button>
      </div>
      <p className="muted reviewer-pending">{t("vf.timePending")}</p>
      {left ? children : <button type="button" className="btn-primary" onClick={() => set(null)}>{t("vf.start")}</button>}
    </>
  );
}

/** M2/M3 assisted capture, step one: the patient's Health ID, then the one-time code sent to the patient's own phone, which the
 * present patient reads out. No tick-box stands in for it: no code, no access. */
function StartForm() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const { set } = useAssist();
  const [healthId, setHealthId] = useState("");
  const [pending, setPending] = useState<AssistSession | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  const ask = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      setPending(await api.request<AssistSession>("POST", "/verifier/sessions", { body: { health_id: toAsciiDigits(healthId.trim()).toUpperCase() } }));
    });
  };
  const confirm = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      set(await api.request<AssistSession>("POST", `/verifier/sessions/${pending!.id}/confirm`, { body: { code: toAsciiDigits(code.trim()) } }));
    });
  };

  return (
    <>
      <h1>{t("vf.title")}</h1>
      <p>{t("vf.intro")}</p>
      {!pending ? (
        <form onSubmit={ask} className="card" noValidate>
          <div className="field">
            <label htmlFor="vf-hid">{t("req.healthId")}</label>
            <input id="vf-hid" autoComplete="off" spellCheck={false} value={healthId} aria-describedby="vf-hid-hint" onChange={(e) => setHealthId(e.target.value)} />
            <span id="vf-hid-hint" className="hint">{t("req.healthIdHint")}</span>
          </div>
          <ErrorNote error={error} />
          <button type="submit" className="btn-primary" disabled={busy || !healthId.trim()}>{t("vf.sendCode")}</button>
        </form>
      ) : (
        <form onSubmit={confirm} className="card" noValidate>
          <p className="notice" role="status">{t("vf.codeNote")}</p>
          {apiMode === "mock" && <p className="notice">{t("common.mockMode", { code: localDigits(MOCK_CODE, lang) })}</p>}
          <div className="field">
            <label htmlFor="vf-code">{t("req.code")}</label>
            {/* the code is the patient's, read out; not this device's SMS, so no one-time-code autofill */}
            <input id="vf-code" inputMode="numeric" autoComplete="off" value={code} autoFocus onChange={(e) => setCode(e.target.value)} />
          </div>
          <ErrorNote error={error} />
          <div className="actions">
            <button type="submit" className="btn-primary" disabled={busy || !code.trim()}>{t("vf.confirm")}</button>
            <button type="button" onClick={() => { setPending(null); setCode(""); setError(null); }}>{t("req.cancel")}</button>
          </div>
        </form>
      )}
    </>
  );
}

/** Start: the code step; with a live session, capture for that patient. */
export function AssistStart() {
  const { session } = useAssist();
  if (!session) return <StartForm />;
  return <WithSession><Capture patientId={session.patient_id ?? ""} docBase="/verifier/documents" listTitle="vf.toCheck" /></WithSession>;
}

/** The patient's documents still waiting for a human check (the server lists nothing verified to a verifier). */
export function AssistQueue() {
  const { t } = useI18n();
  const { session } = useAssist();
  return (
    <WithSession>
      <h1>{t("nav.queue")}</h1>
      <DocList patientId={session?.patient_id ?? ""} base="/verifier/documents" title="vf.toCheck" />
    </WithSession>
  );
}

/** M3 side-by-side check with the patient: the same screen the patient uses, with no way to the timeline. */
export function AssistDocument() {
  return <WithSession><DocumentPage toTimeline={null} /></WithSession>;
}
