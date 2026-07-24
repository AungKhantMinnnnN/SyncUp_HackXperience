import { useState } from "react";
import { Calendar } from "./pages/Calendar";
import { Resources } from "./pages/Resources";
import { Budget } from "./pages/Budget";

// ponytail: state-based tabs, not react-router — 3 views, one URL. Add the router
// when a view needs a deep-linkable URL (e.g. sharing a single event).
const TABS = {
  Calendar: <Calendar />,
  Resources: <Resources />,
  Budget: <Budget />,
} as const;

export function App() {
  const [tab, setTab] = useState<keyof typeof TABS>("Calendar");
  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <h1>SyncUp</h1>
      <nav style={{ display: "flex", gap: 8, marginBottom: 24 }}>
        {(Object.keys(TABS) as (keyof typeof TABS)[]).map((name) => (
          <button
            key={name}
            onClick={() => setTab(name)}
            style={{
              padding: "6px 14px",
              border: "1px solid #ccc",
              borderRadius: 6,
              background: tab === name ? "#111" : "#fff",
              color: tab === name ? "#fff" : "#111",
              cursor: "pointer",
            }}
          >
            {name}
          </button>
        ))}
      </nav>
      {TABS[tab]}
    </div>
  );
}
