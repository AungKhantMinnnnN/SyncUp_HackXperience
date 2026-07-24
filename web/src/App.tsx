import { useEffect, useState } from "react";
import { getOrg } from "./api/scheduling";
import { listConflicts } from "./api/resources";
import { getFinanceSummary } from "./api/finance";
import { Calendar } from "./pages/Calendar";
import { Resources } from "./pages/Resources";
import { Budget } from "./pages/Budget";

const TABS = ["Schedule", "Resources", "Budget"] as const;
type Tab = (typeof TABS)[number];

export function App() {
  const [tab, setTab] = useState<Tab>("Schedule");
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone);
  const [org, setOrg] = useState<string>("");
  const [caught, setCaught] = useState<number | null>(null);

  useEffect(() => {
    getOrg()
      .then((o) => {
        setTz(o.timezone);
        setOrg(o.name);
      })
      .catch(() => {});
    // The headline: how many claims-over-a-limit SyncUp is holding back right now.
    Promise.all([listConflicts().catch(() => []), getFinanceSummary().catch(() => null)])
      .then(([conflicts, fin]) => {
        const overCap = fin ? fin.events.filter((e) => e.over_cap).length : 0;
        setCaught(conflicts.length + overCap);
      })
      .catch(() => {});
  }, []);

  return (
    <div className="wrap">
      <header className="topbar">
        <div className="topline">
          <div>
            <div className="eyebrow">SyncUp · Operations Console</div>
            <h1 className="thesis">{org || "SyncUp"}</h1>
            <p className="tagline">
              One <span className="accent">conflict</span> primitive · three domains
            </p>
          </div>
          <div className="caught">
            <b>{caught ?? "—"}</b>
            conflicts held back
            <br />
            before anyone committed
          </div>
        </div>

        <nav className="nav" role="tablist" aria-label="Modules">
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </nav>
      </header>

      {tab === "Schedule" && <Calendar tz={tz} />}
      {tab === "Resources" && <Resources tz={tz} />}
      {tab === "Budget" && <Budget />}
    </div>
  );
}
