import { MonitorSmartphone } from "lucide-react";
import { useState } from "react";
import { formatDateTime, useI18n } from "../i18n/i18n";
import { useLoad, useSession } from "../session";
import { ConfirmDialog, ErrorNote, Loading } from "./ui";

type ActiveSession = { id: string; device: string | null; started_at: string; last_seen_at: string; current: boolean };

/** UX-3c: where this account is signed in. The device is a family label only (the server never sends the user-agent);
 * this device is ended with Sign out, any other one here after a confirmation. */
export function Sessions() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const list = useLoad(() => api.request<{ items: ActiveSession[] }>("GET", "/auth/sessions"), []);
  const [ask, setAsk] = useState<ActiveSession | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const revoke = async (s: ActiveSession) => {
    setAsk(null);
    setError(null);
    setDone(false);
    try {
      await api.request("POST", `/auth/sessions/${s.id}/revoke`);
      setDone(true);
      list.reload();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <section className="card section" aria-labelledby="sessions-title">
      <h2 id="sessions-title">{t("sessions.title")}</h2>
      <p className="muted">{t("sessions.desc")}</p>
      <ErrorNote error={list.error} onRetry={list.reload} />
      {list.loading && !list.data && <Loading lines={2} />}
      {list.data && (
        <ul className="session-list">
          {list.data.items.map((s) => (
            <li key={s.id}>
              <MonitorSmartphone size={22} aria-hidden="true" />
              <span>
                <strong>{s.device ?? t("sessions.unknown")}</strong>
                {s.current && <> <span className="chip chip-verified">{t("sessions.this")}</span></>}
                <br /><span className="muted">{t("sessions.lastActive", { when: formatDateTime(s.last_seen_at, lang) })}</span>
              </span>
              {!s.current && <button type="button" onClick={() => setAsk(s)}>{t("sessions.end")}</button>}
            </li>
          ))}
        </ul>
      )}
      {done && <p className="ok-note" role="status">{t("sessions.ended")}</p>}
      <ErrorNote error={error} />
      <ConfirmDialog open={ask !== null} title={t("sessions.confirm")} confirmLabel={t("sessions.end")}
                     onCancel={() => setAsk(null)} onConfirm={() => ask && revoke(ask)}>
        <p>{ask?.device ?? t("sessions.unknown")}</p>
      </ConfirmDialog>
    </section>
  );
}

/** UX-3c: a staff member's account page (each staff portal): their sessions. */
export function StaffAccount() {
  const { t } = useI18n();
  return (<><h1>{t("nav.account")}</h1><Sessions /></>);
}
