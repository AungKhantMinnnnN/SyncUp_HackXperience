import { useCallback, useEffect, useMemo, useState } from "react";
import { MemberCalendar } from "../components/MemberCalendar";
import { MemberConflictCard, type ConflictGroup } from "../components/MemberConflictCard";
import { MemberList } from "../components/MemberName";
import {
  confirmProposal,
  createRequest,
  getEvents,
  getMemberConflicts,
  getMembers,
  getRequest,
  type EventItem,
  type EventPlan,
  type MemberConflict,
  type MemberInfo,
  type Proposal,
  type RequestStatus,
} from "../api/scheduling";
import { DAY, fmtTime } from "../util";

const hhmm = (iso: string, tz: string) =>
  new Date(iso).toLocaleTimeString("en-SG", { timeZone: tz, hour: "2-digit", minute: "2-digit" });

export function Calendar({ tz }: { tz: string }) {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [conflicts, setConflicts] = useState<MemberConflict[]>([]);
  const [roster, setRoster] = useState<MemberInfo[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const loadConflicts = useCallback(() => {
    getMemberConflicts().then(setConflicts).catch(() => {});
  }, []);
  const loadEvents = useCallback(() => {
    const now = new Date();
    getEvents(now.toISOString(), new Date(now.getTime() + 14 * DAY).toISOString())
      .then(setEvents)
      .catch(() => {});
  }, []);
  const loadRoster = useCallback(() => {
    getMembers().then(setRoster).catch(() => {});
  }, []);
  const reloadAfterResolve = useCallback(() => {
    loadConflicts();
    loadEvents();
    loadRoster();
    setRefreshKey((k) => k + 1); // force the member calendars to refetch too
  }, [loadConflicts, loadEvents, loadRoster]);
  const roleByName = useMemo(
    () => Object.fromEntries(roster.map((m) => [m.full_name, m.role])),
    [roster],
  );
  const [prompt, setPrompt] = useState("2 hour exec meeting next week, before Friday evening");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [req, setReq] = useState<RequestStatus | null>(null);
  const [confirmed, setConfirmed] = useState<EventPlan | null>(null);

  useEffect(() => {
    loadEvents();
    loadRoster();
    loadConflicts();
  }, [loadEvents, loadRoster, loadConflicts]);

  // A member in two overlapping events, grouped by the clashing event pair.
  const conflictGroups = useMemo<ConflictGroup[]>(() => {
    const map: Record<string, ConflictGroup> = {};
    for (const c of conflicts) {
      const key = `${c.event_a_id}|${c.event_b_id}`;
      (map[key] ??= { a: c.event_a, aId: c.event_a_id, b: c.event_b, bId: c.event_b_id, members: [] })
        .members.push({ id: c.member_id, name: c.member });
    }
    return Object.values(map);
  }, [conflicts]);

  async function findTimes() {
    setBusy(true);
    setErr(null);
    setReq(null);
    setConfirmed(null);
    try {
      const { request_id } = await createRequest(prompt);
      setReq(await getRequest(request_id));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(p: Proposal) {
    setBusy(true);
    setErr(null);
    try {
      setConfirmed(await confirmProposal(p.id));
      reloadAfterResolve(); // show the new event (and any new conflict) immediately
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {conflictGroups.map((g) => (
        <MemberConflictCard
          key={`${g.aId}|${g.bId}`}
          group={g}
          roleByName={roleByName}
          onResolved={reloadAfterResolve}
        />
      ))}

      <div className="panel">
        <div className="panel-head">
          <h2>Team availability</h2>
          <span className="tag">by member · monthly</span>
        </div>
        <p className="sub">
          Each member's commitments — class, exam, work, club, personal. Every block is a claim on
          someone's time; the scheduler only proposes windows with no overlap.
        </p>
        <MemberCalendar tz={tz} refreshKey={refreshKey} />
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Plan a meeting</h2>
          <span className="tag">plain english → ranked slots</span>
        </div>
        <textarea
          className="prompt"
          rows={2}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
        <div style={{ marginTop: 10 }}>
          <button className="btn primary" onClick={findTimes} disabled={busy || !prompt.trim()}>
            {busy ? "Working…" : "Find times"}
          </button>
        </div>

        {err && <p className="err">Error: {err}</p>}

        {confirmed && (
          <div className="callout" style={{ borderColor: "var(--ok)", background: "#f0faf6", marginTop: 16 }}>
            <div className="tag" style={{ color: "var(--ok)" }}>Confirmed</div>
            <h3>{confirmed.event.title || "Event"}</h3>
            <p>
              {fmtTime(confirmed.event.start_utc, tz)} · budget {confirmed.budget.verdict} ·{" "}
              {confirmed.reservations.reservation_ids.length} resources held
            </p>
          </div>
        )}

        {req && !confirmed && (
          <div className="row-cards" style={{ marginTop: 16 }}>
            {req.proposals.length === 0 ? (
              <p className="muted">No conflict-free slots in that window — try widening it.</p>
            ) : (
              req.proposals.map((p) => (
                <div className="pcard" key={p.id}>
                  <div>
                    <div className="when">
                      #{p.rank} · {fmtTime(p.start_utc, tz)}
                    </div>
                    <div className="meta">
                      {p.attendance_pct?.toFixed(0)}% weighted attendance
                      {p.conflicts.length > 0 && ` · ${p.conflicts.join(", ")}`}
                    </div>
                    {p.available_members.length > 0 && (
                      <div className="free">
                        ✓ <MemberList names={p.available_members} roleByName={roleByName} />
                      </div>
                    )}
                  </div>
                  <button className="btn" onClick={() => confirm(p)} disabled={busy}>
                    Confirm
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Upcoming events</h2>
          <span className="tag">next 14 days · {events.length}</span>
        </div>
        {events.length === 0 ? (
          <p className="muted">No events in the next 14 days.</p>
        ) : (
          <div className="row-cards">
            {events.map((e) => (
              <div className="ecard" key={e.id}>
                <div className="ecard-head">
                  <div className="when">{e.title}</div>
                  <span className={`badge ${e.status === "confirmed" ? "ok" : "ink"}`}>
                    {e.status}
                  </span>
                </div>
                <div className="meta">
                  {fmtTime(e.start_utc, tz)} – {hhmm(e.end_utc, tz)}
                </div>
                {e.members.length > 0 && (
                  <div className="ecard-row">
                    <span className="k">Members</span>
                    <span>
                      {e.members.length} · <MemberList names={e.members} roleByName={roleByName} />
                    </span>
                  </div>
                )}
                {e.items.length > 0 && (
                  <div className="ecard-row">
                    <span className="k">Items</span>
                    <span>
                      {e.items.map((it, i) => (
                        <span key={i} className={it.org_owned ? "" : "buy"}>
                          {i > 0 && " · "}
                          {it.item_name} ×{it.quantity}
                          {!it.org_owned && " (buy)"}
                        </span>
                      ))}
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
