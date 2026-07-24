import { useEffect, useState } from "react";
import { BudgetDetail } from "../components/BudgetDetail";
import { BurndownChart } from "../components/BurndownChart";
import { HeadroomBanner } from "../components/HeadroomBanner";
import { VarianceReport } from "../components/VarianceReport";
import { getEvents, type EventItem } from "../api/scheduling";
import { DAY } from "../util";

export function Budget() {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [selected, setSelected] = useState("");

  useEffect(() => {
    const now = new Date();
    getEvents(now.toISOString(), new Date(now.getTime() + 21 * DAY).toISOString())
      .then(setEvents)
      .catch(() => {});
  }, []);

  const eventId = selected || events[0]?.id || "";

  return (
    <>
      <HeadroomBanner />
      <BurndownChart />

      <div className="panel">
        <div className="panel-head">
          <h2>Event budgets</h2>
          <span className="tag">select an event</span>
        </div>
        <p className="sub">
          A budget that spills past its cap is the same picture as a projector double-booked — a
          claim exceeding a limit, caught before approval.
        </p>
        {events.length === 0 ? (
          <p className="muted">No upcoming events. Confirm one from the Schedule tab.</p>
        ) : (
          <div className="member-pills">
            {events.map((e) => (
              <button key={e.id} aria-pressed={e.id === eventId} onClick={() => setSelected(e.id)}>
                {e.title}
              </button>
            ))}
          </div>
        )}
      </div>

      {eventId && <BudgetDetail eventId={eventId} />}

      <VarianceReport />
    </>
  );
}
