import { Check, Clock, Pause, Play, SkipForward, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { Reminder, ReminderLogAction, ReminderStatus } from "../../api/types";
import { ConfirmDialog, ErrorNote, Loading, Section } from "../../components/ui";
import { formatDate, localDigits, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";

const LOG: Array<[ReminderLogAction, typeof Check]> = [["taken", Check], ["skipped", SkipForward], ["snoozed", Clock]];

/** M8: reminders proposed from verified events never run until the patient switches them on; they repeat what was written and
 * never suggest a dose. The patient pauses, resumes or stops them, and logs taken, skipped or snoozed. */
export function Reminders() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const list = useLoad(() => api.request<Reminder[]>("GET", "/reminders"), []);
  const [error, setError] = useState<unknown>(null);
  const [stopping, setStopping] = useState<Reminder | null>(null);

  async function call(method: "PATCH" | "POST", path: string, body: object) {
    setError(null);
    try {
      await api.request(method, path, { body });
      list.reload();
    } catch (e) {
      setError(e);
    }
  }
  const setStatus = (r: Reminder, status: ReminderStatus) => call("PATCH", `/reminders/${r.id}`, { status });

  const card = (r: Reminder) => (
    <li key={r.id} className="card">
      <p><strong>{t(`rem.kind.${r.kind}` as Key)}</strong> · {r.as_written}</p>
      <p className="muted">{t("rem.times", { times: localDigits(r.times.join(", "), lang) })}</p>
      {r.log[0] && <p className="muted">{t("rem.last", { action: t(`rem.${r.log[0].action}` as Key), when: formatDate(r.log[0].at, lang) })}</p>}
      <Link to="/patient/timeline">{t("rem.source")}</Link>
      <div className="actions">
        {r.status === "proposed" && <>
          <button type="button" className="btn-primary" onClick={() => setStatus(r, "active")}><Play size={18} aria-hidden="true" />{t("rem.confirm")}</button>
          <button type="button" onClick={() => setStatus(r, "ended")}><X size={18} aria-hidden="true" />{t("rem.dismiss")}</button>
        </>}
        {r.status === "active" && <>
          {LOG.map(([action, Icon]) => (
            <button key={action} type="button" onClick={() => call("POST", `/reminders/${r.id}/log`, { action, at: new Date().toISOString() })}>
              <Icon size={18} aria-hidden="true" />{t(`rem.${action}` as Key)}
            </button>
          ))}
          <button type="button" onClick={() => setStatus(r, "paused")}><Pause size={18} aria-hidden="true" />{t("rem.pause")}</button>
        </>}
        {r.status === "paused" && <button type="button" onClick={() => setStatus(r, "active")}><Play size={18} aria-hidden="true" />{t("rem.resume")}</button>}
        {(r.status === "active" || r.status === "paused") && <button type="button" onClick={() => setStopping(r)}>{t("rem.stop")}</button>}
      </div>
    </li>
  );

  const group = (status: ReminderStatus, title: Key) => {
    const items = (list.data ?? []).filter((r) => r.status === status);
    return (
      <Section id={`rem-${status}`} title={t(title)}>
        {items.length ? <ul className="list">{items.map(card)}</ul> : <p className="muted">{t("rem.none")}</p>}
      </Section>
    );
  };

  return (
    <>
      <h1>{t("rem.title")}</h1>
      <p className="notice">{t("rem.intro")}</p>
      <ErrorNote error={error ?? list.error} />
      {list.loading && !list.data ? <Loading /> : <>{group("proposed", "rem.proposed")}{group("active", "rem.active")}{group("paused", "rem.paused")}</>}
      <ConfirmDialog open={!!stopping} title={t("rem.stopAsk")} confirmLabel={t("rem.stopYes")} onCancel={() => setStopping(null)}
                     onConfirm={() => { const r = stopping!; setStopping(null); setStatus(r, "ended"); }} />
    </>
  );
}
