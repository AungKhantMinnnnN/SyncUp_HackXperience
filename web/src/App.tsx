import { useEffect, useState } from "react";
import { getOrg } from "./api/scheduling";
import { Calendar } from "./pages/Calendar";
import { Resources } from "./pages/Resources";
import { Budget } from "./pages/Budget";

const TABS = ["Schedule", "Resources", "Budget"] as const;
type Tab = (typeof TABS)[number];

export function App() {
  const [tab, setTab] = useState<Tab>("Schedule");
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone);
  const [org, setOrg] = useState<string>("");

  useEffect(() => {
    getOrg()
      .then((o) => {
        setTz(o.timezone);
        setOrg(o.name);
      })
      .catch(() => {});
  }, []);

  return (
    <div className="wrap">
      <header className="topbar">
        <div className="topline">
          <div>
              <h1 className="thesis">{org ? `SyncUp • ${org}` : "SyncUp"}</h1>
              <p className="tagline">
                Organization Console
              </p>
          </div>
          {/* <div className="caught">
            <b>{caught ?? "—"}</b>
            conflicts held back
            <br />
            before anyone committed
          </div> */}
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
