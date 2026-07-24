import { useState } from "react";
import { api } from "../api/client";

// Resource inventory, a 14-day timeline, the org-wide conflict feed, and a per-event
// packing list — all against the real /api/resources endpoints. Money arrives as
// strings on the wire; parsed with Number() only for rendering, never for math.
//
// There's no auth/org-selection UI anywhere in this app yet (single-tenant demo auth,
// no login flow), so org_id and event_id are plain text inputs rather than pulled from
// a session — matching how the bot resolves org via a lookup, not a stored context.

interface ResourceRow {
  id: string;
  name: string;
  category: string | null;
  quantity_total: number;
  exclusive: boolean;
  condition: string | null;
  replacement_cost: string | null;
}

interface AvailabilitySnapshot {
  total: number;
  reserved: number;
  available: number;
}

interface ReservationRow {
  id: string;
  resource_id: string;
  event_id: string | null;
  quantity: number;
  start_utc: string;
  end_utc: string;
  exclusive: boolean;
  status: string;
}

interface ConflictRow {
  resource_name: string;
  event_id: string | null;
  requested: number;
  available: number;
  shortfall: number;
  blocking_event_title: string | null;
  suggested_alternative: string | null;
}

interface PackingListItemRow {
  id: string;
  resource_id: string | null;
  item_name: string;
  quantity: number;
  org_owned: boolean;
  source: string;
  est_cost: string | null;
}

const TIMELINE_DAYS = 14;

function isoRange(days: number): { from: string; to: string } {
  const from = new Date();
  const to = new Date(from.getTime() + days * 24 * 60 * 60 * 1000);
  return { from: from.toISOString(), to: to.toISOString() };
}

export function Resources() {
  const [orgId, setOrgId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [resources, setResources] = useState<ResourceRow[]>([]);
  const [availability, setAvailability] = useState<Record<string, AvailabilitySnapshot>>({});
  const [conflicts, setConflicts] = useState<ConflictRow[]>([]);

  const [selectedResource, setSelectedResource] = useState<string>("");
  const [timeline, setTimeline] = useState<ReservationRow[]>([]);

  const [eventId, setEventId] = useState("");
  const [packingList, setPackingList] = useState<PackingListItemRow[] | null>(null);

  async function loadAll() {
    if (!orgId) return;
    setLoading(true);
    setError(null);
    try {
      const [resourceRows, conflictRows] = await Promise.all([
        api<ResourceRow[]>(`/api/resources/?org_id=${orgId}`),
        api<ConflictRow[]>(`/api/resources/conflicts?org_id=${orgId}`),
      ]);
      setResources(resourceRows);
      setConflicts(conflictRows);

      const { from, to } = isoRange(TIMELINE_DAYS);
      const snapshots = await Promise.all(
        resourceRows.map((r) =>
          api<AvailabilitySnapshot>(
            `/api/resources/${r.id}/availability?org_id=${orgId}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
          ).catch(() => null),
        ),
      );
      const byId: Record<string, AvailabilitySnapshot> = {};
      resourceRows.forEach((r, i) => {
        const snap = snapshots[i];
        if (snap) byId[r.id] = snap;
      });
      setAvailability(byId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load resources");
    } finally {
      setLoading(false);
    }
  }

  async function loadTimeline(resourceId: string) {
    setSelectedResource(resourceId);
    if (!resourceId || !orgId) {
      setTimeline([]);
      return;
    }
    try {
      const rows = await api<ReservationRow[]>(
        `/api/resources/${resourceId}/reservations?org_id=${orgId}`,
      );
      setTimeline(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load timeline");
    }
  }

  async function loadPackingList() {
    if (!eventId || !orgId) return;
    try {
      const rows = await api<PackingListItemRow[]>(
        `/api/resources/events/${eventId}/packing-list?org_id=${orgId}`,
      );
      setPackingList(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load packing list");
    }
  }

  const cellStyle: React.CSSProperties = { padding: "6px 10px", borderBottom: "1px solid #eee" };
  const thStyle: React.CSSProperties = { ...cellStyle, textAlign: "left", color: "#555" };

  return (
    <section>
      <h2>Resources</h2>
      <p>Inventory, a 14-day reservation timeline, org-wide conflicts, and per-event packing lists.</p>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16 }}>
        <input
          placeholder="org_id"
          value={orgId}
          onChange={(e) => setOrgId(e.target.value)}
          style={{ padding: 6, minWidth: 280 }}
        />
        <button onClick={loadAll} disabled={!orgId || loading}>
          {loading ? "Loading…" : "Load"}
        </button>
      </div>

      {error && <p style={{ color: "#b00020" }}>{error}</p>}

      <h3>Inventory</h3>
      {resources.length === 0 ? (
        <p style={{ color: "#777" }}>No resources loaded yet.</p>
      ) : (
        <table style={{ borderCollapse: "collapse", width: "100%", marginBottom: 24 }}>
          <thead>
            <tr>
              <th style={thStyle}>Item</th>
              <th style={thStyle}>Category</th>
              <th style={thStyle}>Total</th>
              <th style={thStyle}>Reserved</th>
              <th style={thStyle}>Available</th>
              <th style={thStyle}>Condition</th>
            </tr>
          </thead>
          <tbody>
            {resources.map((r) => {
              const snap = availability[r.id];
              return (
                <tr
                  key={r.id}
                  onClick={() => loadTimeline(r.id)}
                  style={{ cursor: "pointer", background: selectedResource === r.id ? "#f5f5f5" : undefined }}
                >
                  <td style={cellStyle}>{r.name}{r.exclusive ? " (exclusive)" : ""}</td>
                  <td style={cellStyle}>{r.category ?? "—"}</td>
                  <td style={cellStyle}>{r.quantity_total}</td>
                  <td style={cellStyle}>{snap ? snap.reserved : "—"}</td>
                  <td style={cellStyle}>
                    {snap ? (
                      <span style={{ color: snap.available === 0 ? "#b00020" : undefined }}>{snap.available}</span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td style={cellStyle}>{r.condition ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <h3>Timeline {selectedResource && `— ${resources.find((r) => r.id === selectedResource)?.name ?? ""}`}</h3>
      {!selectedResource ? (
        <p style={{ color: "#777" }}>Click a resource above to see its next {TIMELINE_DAYS} days.</p>
      ) : timeline.length === 0 ? (
        <p style={{ color: "#777" }}>No active reservations in this window.</p>
      ) : (
        <div style={{ marginBottom: 24 }}>
          {timeline.map((res) => {
            const { from } = isoRange(0);
            const windowStart = new Date(from).getTime();
            const windowMs = TIMELINE_DAYS * 24 * 60 * 60 * 1000;
            const left = Math.max(0, ((new Date(res.start_utc).getTime() - windowStart) / windowMs) * 100);
            const width = Math.min(
              100 - left,
              ((new Date(res.end_utc).getTime() - new Date(res.start_utc).getTime()) / windowMs) * 100,
            );
            return (
              <div key={res.id} style={{ marginBottom: 6 }}>
                <div style={{ fontSize: 12, color: "#555", marginBottom: 2 }}>
                  {new Date(res.start_utc).toLocaleString()} – {new Date(res.end_utc).toLocaleString()} · qty {res.quantity} · {res.status}
                </div>
                <div style={{ background: "#eee", height: 10, borderRadius: 4, position: "relative" }}>
                  <div
                    style={{
                      position: "absolute",
                      left: `${left}%`,
                      width: `${Math.max(width, 1)}%`,
                      height: "100%",
                      borderRadius: 4,
                      background: res.exclusive ? "#b00020" : "#1a6e8e",
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      <h3>Conflicts</h3>
      {conflicts.length === 0 ? (
        <p style={{ color: "#777" }}>No conflicts.</p>
      ) : (
        <table style={{ borderCollapse: "collapse", width: "100%", marginBottom: 24 }}>
          <thead>
            <tr>
              <th style={thStyle}>Resource</th>
              <th style={thStyle}>Requested</th>
              <th style={thStyle}>Available</th>
              <th style={thStyle}>Shortfall</th>
              <th style={thStyle}>Blocking event</th>
              <th style={thStyle}>Suggested alternative</th>
            </tr>
          </thead>
          <tbody>
            {conflicts.map((c, i) => (
              <tr key={i}>
                <td style={cellStyle}>{c.resource_name}</td>
                <td style={cellStyle}>{c.requested}</td>
                <td style={cellStyle}>{c.available}</td>
                <td style={{ ...cellStyle, color: "#b00020" }}>{c.shortfall}</td>
                <td style={cellStyle}>{c.blocking_event_title ?? "—"}</td>
                <td style={cellStyle}>{c.suggested_alternative ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Event packing list</h3>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
        <input
          placeholder="event_id"
          value={eventId}
          onChange={(e) => setEventId(e.target.value)}
          style={{ padding: 6, minWidth: 280 }}
        />
        <button onClick={loadPackingList} disabled={!eventId || !orgId}>
          Load
        </button>
      </div>
      {packingList === null ? (
        <p style={{ color: "#777" }}>Enter an event ID above to see its packing list.</p>
      ) : packingList.length === 0 ? (
        <p style={{ color: "#777" }}>No packing-list items for this event yet.</p>
      ) : (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th style={thStyle}>Item</th>
              <th style={thStyle}>Quantity</th>
              <th style={thStyle}>Owned</th>
              <th style={thStyle}>Source</th>
              <th style={thStyle}>Est. cost</th>
            </tr>
          </thead>
          <tbody>
            {packingList.map((item) => (
              <tr key={item.id}>
                <td style={cellStyle}>{item.item_name}</td>
                <td style={cellStyle}>{item.quantity}</td>
                <td style={cellStyle}>{item.org_owned ? "Owned" : "Unowned"}</td>
                <td style={cellStyle}>
                  {item.source === "ai" ? <span title="AI-suggested">✨ AI</span> : "Manual"}
                </td>
                <td style={cellStyle}>{item.est_cost ? `$${Number(item.est_cost).toFixed(2)}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
