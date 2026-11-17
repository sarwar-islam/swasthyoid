import { FileCheck2, UserRound } from "lucide-react";
import { Link } from "react-router";
import type { EventType, TimelineEvent } from "../../api/types";
import { ErrorNote, Loading } from "../../components/ui";
import { formatDate, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";

// the values shown per type: summary/build.py FIELDS (plus diagnosis_text); other payload keys (source, correction reason, ...)
// are internal and stay on the timeline
const FIELDS: Partial<Record<EventType, string[]>> = {
  medication: ["name_as_written", "strength", "form", "dose_instruction", "duration"],
  diagnosis: ["diagnosis_text"],
  lab_result: ["test_name", "result", "unit", "reference_range"],
  follow_up: ["follow_up_date"],
  vital_reading: ["value", "unit", "context"],
};
const RECENT = 5;

/** UX-2: the patient's own record at a glance, read only, built from their own timeline (no new data, no interpretation, no
 * safety alerts: those are for the doctor). Every row carries its provenance in words; an empty section says only that
 * nothing is recorded. */
export function HealthSummary() {
  const { t, lang } = useI18n();
  const { api, claims } = useSession();
  const events = useLoad(() => api.request<TimelineEvent[]>("GET", `/patients/${claims?.sub}/timeline`), [claims?.sub]);
  const all = events.data ?? [];
  const current = all.filter((e) => !all.some((x) => x.supersedes === e.event_id)).sort((a, b) => b.date.localeCompare(a.date));
  const verified = (type: EventType) => current.filter((e) => e.event_type === type && e.verification_status === "document_verified");
  const today = new Date().toISOString().slice(0, 10);
  const sections: Array<{ id: string; title: Key; rows: TimelineEvent[] }> = [
    { id: "hs-meds", title: "hs.meds", rows: verified("medication") },
    { id: "hs-dx", title: "hs.dx", rows: verified("diagnosis") },
    { id: "hs-labs", title: "hs.labs", rows: verified("lab_result").slice(0, RECENT) },
    { id: "hs-vitals", title: "hs.vitals",
      rows: current.filter((e) => e.event_type === "vital_reading" && e.verification_status === "patient_reported").slice(0, RECENT) },
    { id: "hs-follow", title: "hs.follow",
      rows: verified("follow_up").filter((e) => (e.payload.follow_up_date ?? e.date) >= today).reverse() },
  ];
  return (
    <>
      <h1>{t("hs.title")}</h1>
      <p className="muted">{t("hs.intro")}</p>
      {events.loading ? <Loading lines={3} /> : <ErrorNote error={events.error} onRetry={events.reload} />}
      {!events.loading && !events.error && sections.map(({ id, title, rows }) => (
        <section key={id} className="card section" aria-labelledby={id}>
          <h2 id={id}>{t(title)}</h2>
          {rows.length === 0 ? <p className="muted">{t("hs.none")}</p> : (
            <ul className="list">
              {rows.map((e) => (
                <li key={e.event_id} className="hs-row">
                  <Link to={`/patient/timeline#event-${e.event_id}`}>
                    <bdi>{(FIELDS[e.event_type] ?? []).map((k) => e.payload[k]).filter(Boolean).join(" · ")}</bdi>
                  </Link>
                  <span className="muted"> · {formatDate(e.date, lang)}</span>
                  <br />
                  {e.verification_status === "document_verified"
                    ? <span className="badge badge-document_verified"><FileCheck2 size={16} aria-hidden="true" />{t("hs.verified")}</span>
                    : <span className="badge badge-patient_reported"><UserRound size={16} aria-hidden="true" />{t("hs.reported")}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </>
  );
}
