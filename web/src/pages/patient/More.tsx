import { AlarmClock, Bell, BriefcaseMedical, ClipboardList, FileText, HeartHandshake, HeartPulse, IdCard, LifeBuoy, Siren, UserRound, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Sessions } from "../../components/Sessions";
import { ErrorNote } from "../../components/ui";
import { flags } from "../../flags";
import { useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useSession } from "../../session";

const TILES: Array<{ to: string; title: Key; desc: Key; icon: LucideIcon; flag?: keyof typeof flags }> = [
  { to: "/patient/summary", title: "hs.title", desc: "hs.desc", icon: ClipboardList },
  { to: "/patient/profile", title: "me.title", desc: "me.desc", icon: UserRound },
  { to: "/patient/records", title: "records.title", desc: "records.desc", icon: FileText },
  { to: "/patient/inbox", title: "nav.inbox", desc: "more.inbox.desc", icon: Bell },
  { to: "/patient/vitals", title: "more.vitals", desc: "more.vitals.desc", icon: HeartPulse },
  { to: "/patient/reminders", title: "more.reminders", desc: "more.reminders.desc", icon: AlarmClock },
  { to: "/patient/help", title: "more.help", desc: "more.help.desc", icon: LifeBuoy },
  { to: "/patient/first-aid", title: "more.firstAid", desc: "more.firstAid.desc", icon: BriefcaseMedical },
  { to: "/patient/emergency", title: "more.emergency", desc: "more.emergency.desc", icon: Siren },
  { to: "/patient/caregiving", title: "more.care", desc: "more.care.desc", icon: HeartHandshake },
  { to: "/patient/emergency-profile", title: "more.profile", desc: "more.profile.desc", icon: IdCard, flag: "emergencyAccess" },
];

/** F2: the patient's health tools (M13, M8, M7, M10 when its flag is on); F4: caregiver mode. */
export function More() {
  const { t } = useI18n();
  const { api, signOutEverywhere } = useSession();
  const [exported, setExported] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // W2: the server builds the file; the browser saves it (nothing is kept in browser storage)
  const download = async () => {
    setError(null);
    setExported(false);
    try {
      const data = await api.request<unknown>("GET", "/me/export");
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = Object.assign(document.createElement("a"), { href: url, download: "swasthyoid-export.json" });
      link.click();
      URL.revokeObjectURL(url);
      setExported(true);
    } catch (e) {
      setError(e);
    }
  };
  return (
    <>
      <h1>{t("more.title")}</h1>
      <ul className="tiles">
        {TILES.filter((tile) => !tile.flag || flags[tile.flag]).map(({ to, title, desc, icon: Icon }) => (
          <li key={to}>
            <Link to={to} className="card"><Icon size={28} aria-hidden="true" /><span><strong>{t(title)}</strong><br /><span className="muted">{t(desc)}</span></span></Link>
          </li>
        ))}
      </ul>
      <section className="card section" aria-labelledby="account-title">
        <h2 id="account-title">{t("more.account")}</h2>
        <p className="muted">{t("more.export.desc")}</p>
        <button type="button" onClick={download}>{t("more.export")}</button>
        {exported && <p className="ok-note" role="status">{t("more.export.done")}</p>}
        <ErrorNote error={error} />
        <p className="muted">{t("more.signOutAll.desc")}</p>
        <button type="button" onClick={signOutEverywhere}>{t("more.signOutAll")}</button>
      </section>
      <Sessions />
    </>
  );
}
