import { Bell, Camera, ClipboardCheck, ShieldQuestion } from "lucide-react";
import { Link } from "react-router";
import type { Consent, DocumentView, Me, PatientNotification } from "../../api/types";
import { CopyButton, ErrorNote, Loading, Section } from "../../components/ui";
import { formatNumber, useI18n } from "../../i18n/i18n";
import { useLoad, useSession } from "../../session";

export function Home() {
  const { t, lang } = useI18n();
  const { api, claims } = useSession();
  const me = useLoad(() => api.request<Me>("GET", "/me"), []);
  const docs = useLoad(() => api.request<DocumentView[]>("GET", `/patients/${claims?.sub}/documents`), [claims?.sub]);
  const consents = useLoad(() => api.request<Consent[]>("GET", "/consents"), []);
  const notes = useLoad(() => api.request<PatientNotification[]>("GET", "/notifications"), []);

  const toVerify = docs.data?.filter((d) => d.status === "needs_review").length ?? 0;
  const waiting = consents.data?.filter((c) => c.status === "pending").length ?? 0;
  const unread = notes.data?.filter((n) => !n.read_at).length ?? 0;

  return (
    <>
      <h1>{me.data ? t("home.welcome", { name: me.data.name }) : t("nav.home")}</h1>
      <section className="card" aria-labelledby="hid">
        <h2 id="hid">{t("home.healthId")}</h2>
        {me.loading ? <Loading /> : me.data ? (
          <>
            {/* the ID is shown in ASCII digits: it is typed on a doctor's keyboard */}
            <p className="health-id" lang="en">{me.data.health_id}</p>
            <p className="muted">{t("home.healthIdNote")}</p>
            <CopyButton value={me.data.health_id} label="home.copy" />
          </>
        ) : <p className="muted">{t("home.healthIdMissing")}</p>}
      </section>

      <Section id="todo" title={t("home.todo")}>
        <ErrorNote error={docs.error ?? consents.error} />
        <ul className="list">
          {unread > 0 && (
            <li><Link className="card row" to="/patient/inbox"><span><Bell size={20} aria-hidden="true" /> {t("home.inbox", { n: formatNumber(unread, lang) })}</span></Link></li>
          )}
          {toVerify > 0 && (
            <li><Link className="card row" to="/patient/capture"><span><ClipboardCheck size={20} aria-hidden="true" /> {t("home.toVerify", { n: formatNumber(toVerify, lang) })}</span></Link></li>
          )}
          {waiting > 0 && (
            <li><Link className="card row" to="/patient/consent"><span><ShieldQuestion size={20} aria-hidden="true" /> {t("home.toConsent", { n: formatNumber(waiting, lang) })}</span></Link></li>
          )}
          {!docs.loading && !consents.loading && toVerify === 0 && waiting === 0 && unread === 0 && <li className="muted">{t("home.nothing")}</li>}
        </ul>
        <div className="actions">
          <Link className="btn btn-primary" to="/patient/capture"><Camera size={20} aria-hidden="true" />{t("home.capture")}</Link>
        </div>
      </Section>
    </>
  );
}
