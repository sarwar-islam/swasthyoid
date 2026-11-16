import { BriefcaseMedical, RotateCcw } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { apiMode } from "../../api";
import { MOCK_RED_FLAG } from "../../api/mock";
import type { TriageState } from "../../api/types";
import { EmergencyCard, Reviewed } from "../../components/ui";
import { FIRST_AID_CARDS } from "../../content/reviewerPending";
import { useI18n } from "../../i18n/i18n";
import { useSession } from "../../session";

/** M7: the server checks red flags on the first message and on every answer; a match shows the emergency card and stops the
 * questions. If the triage service fails in any way, the emergency card and general advice show (FRD M7 fail-safe), never an
 * empty screen. Free text is not kept after the session. */
export function Triage() {
  const { t } = useI18n();
  const { api } = useSession();
  const [message, setMessage] = useState("");
  const [state, setState] = useState<TriageState | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  async function step(call: () => Promise<TriageState>) {
    setBusy(true);
    try {
      setState(await call());
    } catch {
      setFailed(true); // fail safe: any error shows the emergency card
    } finally {
      setBusy(false);
    }
  }

  const start = (e: FormEvent) => {
    e.preventDefault();
    if (message.trim()) step(() => api.request<TriageState>("POST", "/triage/sessions", { body: { message: message.trim() } }));
  };
  const answer = (option: string) => step(() => api.request<TriageState>("POST", `/triage/sessions/${state!.session_id}/answer`, { body: { answer: option } }));
  const restart = () => { setState(null); setFailed(false); setMessage(""); };

  const emergency = failed || state?.state === "emergency";
  return (
    <>
      <h1>{t("triage.title")}</h1>
      <p className="notice">{t("triage.notice")}</p>
      {emergency ? (
        <>
          <EmergencyCard advice={failed} />
          <div className="actions"><Link className="btn" to="/patient/first-aid"><BriefcaseMedical size={18} aria-hidden="true" />{t("emergency.firstAid")}</Link>
            <button type="button" onClick={restart}><RotateCcw size={18} aria-hidden="true" />{t("triage.again")}</button></div>
        </>
      ) : !state ? (
        <form onSubmit={start} className="card section" noValidate>
          {apiMode === "mock" && <p className="muted">{t("triage.demo", { flag: MOCK_RED_FLAG })}</p>}
          <div className="field">
            <label htmlFor="symptom">{t("triage.describe")}</label>
            <textarea id="symptom" rows={3} value={message} onChange={(e) => setMessage(e.target.value)} />
          </div>
          <button type="submit" className="btn-primary" disabled={busy || !message.trim()}>{t("triage.start")}</button>
        </form>
      ) : state.state === "question" && state.question ? (
        <section className="card section" aria-labelledby="question">
          <h2 id="question"><Reviewed text={state.question.text} as="span" /></h2>
          <div className="actions">
            {state.question.options.map((o) => (
              <button key={o.id} type="button" disabled={busy} onClick={() => answer(o.id)}><Reviewed text={o.text} as="span" /></button>
            ))}
          </div>
        </section>
      ) : state.suggestion && (
        <section className="card section" aria-labelledby="suggestion">
          <h2 id="suggestion">{t("triage.suggestion")}</h2>
          <Reviewed text={state.suggestion.department} as="strong" />
          <Reviewed text={state.suggestion.reason} />
          <p className="notice">{t("triage.notice")}</p>
          <button type="button" onClick={restart}><RotateCcw size={18} aria-hidden="true" />{t("triage.again")}</button>
        </section>
      )}
    </>
  );
}

export function EmergencyPage() {
  const { t } = useI18n();
  return (
    <>
      <h1>{t("more.emergency")}</h1>
      <EmergencyCard />
      <div className="actions"><Link className="btn" to="/patient/first-aid"><BriefcaseMedical size={18} aria-hidden="true" />{t("emergency.firstAid")}</Link></div>
    </>
  );
}

/** Static first-aid cards (M7): reviewer content only, from content/reviewerPending.ts. */
export function FirstAid() {
  const { t } = useI18n();
  return (
    <>
      <h1>{t("firstAid.title")}</h1>
      <p className="muted">{t("reviewer.pending")}</p>
      <div className="list">
        {FIRST_AID_CARDS.map((card) => (
          <article key={card.id} className="card" aria-labelledby={card.id}>
            <h2 id={card.id}><Reviewed text={card.title} as="span" /></h2>
            <ol>{card.steps.map((s, i) => <li key={i}><Reviewed text={s} as="span" /></li>)}</ol>
          </article>
        ))}
      </div>
    </>
  );
}
