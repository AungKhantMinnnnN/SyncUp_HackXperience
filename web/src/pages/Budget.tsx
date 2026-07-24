import { useEffect, useState } from "react";
import { IntervalLane, type LaneRow } from "../components/IntervalLane";
import { getFinanceSummary, type EventBudget, type FinanceSummary } from "../api/finance";
import { money } from "../util";

const num = (s: string | null) => (s == null ? 0 : Number(s));

export function Budget() {
  const [fin, setFin] = useState<FinanceSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getFinanceSummary()
      .then(setFin)
      .catch((e) => setErr((e as Error).message));
  }, []);

  if (err) return <p className="err">Error: {err}</p>;
  if (!fin) return <p className="muted">Loading budget…</p>;

  const allocated = num(fin.total_allocated);
  const committed = num(fin.committed);
  const spent = num(fin.spent);
  const remaining = allocated - committed;

  // Semester burn: spend + pending commitments against the allocation ceiling.
  const burnRow: LaneRow[] = [
    {
      label: "Committed",
      sub: money(committed),
      bars: [
        { start: 0, end: spent, tone: "ink", label: `spent ${money(spent)}` },
        { start: spent, end: committed, tone: "hold", label: "pending" },
      ],
    },
  ];

  return (
    <>
      <div className="metrics">
        <div className="metric">
          <div className="v">{money(allocated)}</div>
          <div className="k">Allocated · {fin.semester}</div>
        </div>
        <div className="metric">
          <div className="v">{money(committed)}</div>
          <div className="k">Committed</div>
        </div>
        <div className="metric">
          <div className="v">{money(spent)}</div>
          <div className="k">Spent</div>
        </div>
        <div className="metric">
          <div className={`v ${remaining < 0 ? "signal" : ""}`}>{money(remaining)}</div>
          <div className="k">Remaining</div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Semester burn-down</h2>
          <span className="tag">{fin.semester}</span>
        </div>
        <p className="sub">Spent and pending, against the {money(allocated)} allocation ceiling.</p>
        <IntervalLane
          rows={burnRow}
          start={0}
          end={Math.max(allocated, committed)}
          markers={[{ at: allocated, label: `ceiling ${money(allocated)}` }]}
          ticks={[money(0), money(allocated / 2), money(allocated)]}
        />
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Per-event budgets</h2>
          <span className="tag">spend vs. stated cap</span>
        </div>
        <p className="sub">
          A budget that spills past its cap is the same picture as a projector double-booked past
          its capacity — a claim exceeding a limit, caught before approval.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          {fin.events.map((ev) => (
            <EventBar key={ev.event_title} ev={ev} />
          ))}
        </div>
      </div>
    </>
  );
}

function EventBar({ ev }: { ev: EventBudget }) {
  const est = num(ev.estimated_total);
  const cap = ev.stated_cap ? num(ev.stated_cap) : null;
  const axisEnd = Math.max(est, cap ?? 0) * 1.08 || 1;

  // The spend bar fills to the cap in green, then spills over in crimson.
  const bars =
    cap != null && est > cap
      ? [
          { start: 0, end: cap, tone: "ok" as const, label: money(cap) },
          { start: cap, end: est, tone: "signal" as const, label: `+${money(est - cap)}` },
        ]
      : [{ start: 0, end: est, tone: "ok" as const, label: money(est) }];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <strong style={{ fontSize: 14 }}>{ev.event_title}</strong>
        <span className={`badge ${ev.over_cap ? "signal" : "ok"}`}>
          {ev.over_cap ? "over cap" : ev.status}
        </span>
      </div>
      <IntervalLane
        rows={[{ label: "Spend", sub: money(est), bars }]}
        start={0}
        end={axisEnd}
        markers={cap != null ? [{ at: cap, label: `cap ${money(cap)}` }] : []}
      />
      <table className="ledger" style={{ marginTop: 10 }}>
        <tbody>
          {ev.line_items.map((li, i) => (
            <tr key={i}>
              <td className="muted" style={{ width: 130 }}>{li.category}</td>
              <td>{li.description ?? "—"}</td>
              <td className="num">{money(li.line_total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
