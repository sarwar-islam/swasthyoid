import { AlarmClock, Bell, BriefcaseMedical, HeartHandshake, HeartPulse, IdCard, LifeBuoy, Siren, type LucideIcon } from "lucide-react";
import { Link } from "react-router";
import { flags } from "../../flags";
import { useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useSession } from "../../session";

const TILES: Array<{ to: string; title: Key; desc: Key; icon: LucideIcon; flag?: keyof typeof flags }> = [
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
  const { signOutEverywhere } = useSession();
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
        <p className="muted">{t("more.signOutAll.desc")}</p>
        <button type="button" onClick={signOutEverywhere}>{t("more.signOutAll")}</button>
      </section>
    </>
  );
}
