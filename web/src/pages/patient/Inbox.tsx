import { Bell, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { PatientNotification } from "../../api/types";
import { ErrorNote, Loading } from "../../components/ui";
import { formatDateTime, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";

/** C3 in-app inbox (GAP, F6). Notices only: nothing here grants access. Consent and emergency-access notices are security notices
 * (FRD C3): there is no setting to switch them off, only "mark as read". */
export function Inbox() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const list = useLoad(() => api.request<PatientNotification[]>("GET", "/notifications"), []);
  const [error, setError] = useState<unknown>(null);

  async function markRead(n: PatientNotification) {
    setError(null);
    try {
      await api.request("POST", `/notifications/${n.id}/read`);
      list.reload();
    } catch (e) {
      setError(e);
    }
  }

  const what = (n: PatientNotification) => n.categories.map((k) => t(`cat.${k}` as Key)).join(", ");
  const someone = (n: PatientNotification) => n.actor_name ?? t("history.someone");
  const TEXT: Record<Exclude<PatientNotification["kind"], "emergency_access">, Key> = {
    consent_request: "inbox.consent", consent_granted: "inbox.consentGranted",
    caregiver_request: "inbox.caregiver", caregiver_granted: "inbox.caregiverGranted",
  };
  const text = (n: PatientNotification) => n.kind === "emergency_access"
    ? t("inbox.emergency", { name: someone(n), facility: n.facility ?? "" })
    : t(TEXT[n.kind], { name: someone(n), what: what(n) });

  return (
    <>
      <h1>{t("nav.inbox")}</h1>
      <ErrorNote error={error ?? list.error} />
      {list.loading && !list.data && <Loading />}
      {list.data?.length === 0 && <p className="muted">{t("inbox.empty")}</p>}
      <ul className="list">
        {list.data?.map((n) => (
          <li key={n.id} className={`card stack${n.kind === "emergency_access" ? " notice" : ""}`}>
            <div className="row">
              <span className="muted">{formatDateTime(n.created_at, lang)}</span>
              {!n.read_at && <span className="chip chip-needs_review">{t("inbox.new")}</span>}
            </div>
            <p id={`note-${n.id}`}>{n.kind === "emergency_access" ? <ShieldAlert size={18} aria-hidden="true" /> : <Bell size={18} aria-hidden="true" />} {text(n)}</p>
            {n.kind !== "caregiver_request" && <p className="muted">{t("inbox.security")}</p>}
            <div className="actions">
              {n.kind === "emergency_access"
                ? <Link to="/patient/consent#history">{t("inbox.history")}</Link>
                : <Link to="/patient/consent">{t(n.kind === "caregiver_request" ? "inbox.answer" : "pqr.toConsent")}</Link>}
              {!n.read_at && <button type="button" aria-describedby={`note-${n.id}`} onClick={() => markRead(n)}>{t("inbox.read")}</button>}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
