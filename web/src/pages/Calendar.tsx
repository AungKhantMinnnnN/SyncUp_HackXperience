// Scheduling planner: describe a meeting -> ranked conflict-free slots -> confirm.
import { useEffect, useState } from "react";
import {
  confirmProposal,
  createRequest,
  getOrg,
  getRequest,
  type EventPlan,
  type Proposal,
  type RequestStatus,
} from "../api/scheduling";

const fmt = (iso: string, tz: string) =>
  new Date(iso).toLocaleString("en-SG", {
    timeZone: tz,
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

const card: React.CSSProperties = {
  border: "1px solid #ddd",
  borderRadius: 8,
  padding: 14,
  marginBottom: 10,
};

export function Calendar() {
  const [prompt, setPrompt] = useState("2 hour exec meeting next week, before Friday evening");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [req, setReq] = useState<RequestStatus | null>(null);
  const [confirmed, setConfirmed] = useState<EventPlan | null>(null);
  // Org timezone from the API; browser tz until it loads.
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone);

  useEffect(() => {
    getOrg()
      .then((o) => setTz(o.timezone))
      .catch(() => {});
  }, []);

  async function submit() {
    setBusy(true);
    setError(null);
    setReq(null);
    setConfirmed(null);
    try {
      const { request_id } = await createRequest(prompt);
      setReq(await getRequest(request_id)); // proposals are ready by the time this returns
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(p: Proposal) {
    setBusy(true);
    setError(null);
    try {
      setConfirmed(await confirmProposal(p.id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Plan a meeting</h2>
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={2}
        style={{ width: "100%", padding: 8, fontFamily: "inherit", fontSize: 14 }}
      />
      <button onClick={submit} disabled={busy || !prompt.trim()} style={{ marginTop: 8, padding: "8px 16px" }}>
        {busy ? "Working…" : "Find times"}
      </button>

      {error && <p style={{ color: "#b00" }}>Error: {error}</p>}

      {confirmed && (
        <div style={{ ...card, borderColor: "#2E7D4F", background: "#f2fbf5", marginTop: 16 }}>
          <strong>✅ Confirmed — {confirmed.event.title || "Event"}</strong>
          <div>{fmt(confirmed.event.start_utc, tz)} – {fmt(confirmed.event.end_utc, tz)}</div>
          <div style={{ color: "#555", fontSize: 13 }}>
            Budget: {confirmed.budget.verdict} · Reservations: {confirmed.reservations.reservation_ids.length}
          </div>
        </div>
      )}

      {req && !confirmed && (
        <div style={{ marginTop: 16 }}>
          {req.parsed_constraints && (
            <details style={{ marginBottom: 12, color: "#555" }}>
              <summary>What we understood</summary>
              <pre style={{ fontSize: 12, overflowX: "auto" }}>
                {JSON.stringify(req.parsed_constraints, null, 2)}
              </pre>
            </details>
          )}
          {req.proposals.length === 0 ? (
            <p>No conflict-free slots in that window — try widening it.</p>
          ) : (
            req.proposals.map((p) => (
              <div key={p.id} style={card}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <strong>#{p.rank} · {fmt(p.start_utc, tz)}</strong>
                    <div style={{ color: "#555", fontSize: 13 }}>
                      {p.attendance_pct?.toFixed(0)}% weighted attendance
                      {p.conflicts.length > 0 && ` · ${p.conflicts.join(", ")}`}
                    </div>
                    {p.available_members.length > 0 && (
                      <div style={{ color: "#2E7D4F", fontSize: 13 }}>
                        ✅ Available: {p.available_members.join(", ")}
                      </div>
                    )}
                  </div>
                  <button onClick={() => confirm(p)} disabled={busy} style={{ padding: "6px 14px" }}>
                    Confirm
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </section>
  );
}
