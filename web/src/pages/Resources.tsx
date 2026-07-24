import { useEffect, useState } from "react";
import {
  listConflicts,
  listReservations,
  listResources,
  type Conflict,
  type Reservation,
  type Resource,
} from "../api/resources";
import { getEvents, type EventItem } from "../api/scheduling";
import { DAY, fmtTime } from "../util";

const TIMELINE = ["Projector", "Wireless mic", "Folding chair", "Sign-in table"];
const hhmm = (iso: string, tz: string) =>
  new Date(iso).toLocaleTimeString("en-SG", { timeZone: tz, hour: "2-digit", minute: "2-digit" });

export function Resources({ tz }: { tz: string }) {
  const [resources, setResources] = useState<Resource[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [events, setEvents] = useState<Record<string, EventItem>>({});
  const [reservations, setReservations] = useState<Record<string, Reservation[]>>({});
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const now = new Date();
        const [res, con, evs] = await Promise.all([
          listResources(),
          listConflicts(),
          getEvents(now.toISOString(), new Date(now.getTime() + 14 * DAY).toISOString()).catch(
            () => [] as EventItem[],
          ),
        ]);
        setResources(res);
        setConflicts(con);
        setEvents(Object.fromEntries(evs.map((e) => [e.id, e])));
        const keys = res.filter((r) => TIMELINE.includes(r.name));
        const entries = await Promise.all(
          keys.map(async (r) => [r.id, await listReservations(r.id).catch(() => [])] as const),
        );
        setReservations(Object.fromEntries(entries));
      } catch (e) {
        setErr((e as Error).message);
      }
    })();
  }, []);

  const resById = Object.fromEntries(resources.map((r) => [r.id, r]));
  const allReservations = Object.values(reservations)
    .flat()
    .sort((a, b) => a.start_utc.localeCompare(b.start_utc));

  return (
    <>
      {err && <p className="err">Error: {err} (set API_KEY + VITE_API_KEY to read resources)</p>}

      {conflicts.map((c, i) => {
        const wanting = c.event_id ? events[c.event_id]?.title : null;
        return (
          <div className="callout" key={i}>
            <div className="tag">Conflict caught</div>
            <h3>
              {wanting ?? "An event"} can't get {c.resource_name}
            </h3>
            <p>
              Needs {c.requested}, only {c.available} free in its window — already held by{" "}
              <span className="vs">{c.blocking_event_title ?? "another reservation"}</span>.
              {c.suggested_alternative && ` ${c.suggested_alternative}`}
            </p>
          </div>
        );
      })}
      {conflicts.length === 0 && !err && (
        <div className="callout" style={{ borderColor: "var(--ok)", background: "#f0faf6" }}>
          <div className="tag" style={{ color: "var(--ok)" }}>Clear</div>
          <h3>No resource conflicts</h3>
          <p>Every packing-list item is fully reserved.</p>
        </div>
      )}

      <div className="panel">
        <div className="panel-head">
          <h2>Reservations</h2>
          <span className="tag">{allReservations.length} active</span>
        </div>
        {allReservations.length === 0 ? (
          <p className="muted">No active reservations.</p>
        ) : (
          <div className="row-cards">
            {allReservations.map((r) => {
              const resource = resById[r.resource_id];
              const holder = r.event_id ? events[r.event_id]?.title : null;
              return (
                <div className="ecard" key={r.id}>
                  <div className="ecard-head">
                    <div className="when">
                      {resource?.name ?? "Resource"}
                      {resource?.exclusive && <span className="badge signal" style={{ marginLeft: 8 }}>exclusive</span>}
                    </div>
                    <span className={`badge ${r.status === "confirmed" ? "ok" : "hold"}`}>
                      {r.status}
                    </span>
                  </div>
                  <div className="meta">
                    {fmtTime(r.start_utc, tz)} – {hhmm(r.end_utc, tz)} · qty ×{r.quantity}
                  </div>
                  {holder && (
                    <div className="ecard-row">
                      <span className="k">Held by</span>
                      <span>{holder}</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Inventory</h2>
          <span className="tag">{resources.length} items</span>
        </div>
        <table className="ledger">
          <thead>
            <tr>
              <th>Item</th>
              <th>Category</th>
              <th style={{ textAlign: "right" }}>Qty</th>
              <th>Type</th>
            </tr>
          </thead>
          <tbody>
            {resources.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td className="muted">{r.category ?? "—"}</td>
                <td className="num">{r.quantity_total}</td>
                <td>
                  <span className={`badge ${r.exclusive ? "signal" : "ink"}`}>
                    {r.exclusive ? "exclusive" : "pooled"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
