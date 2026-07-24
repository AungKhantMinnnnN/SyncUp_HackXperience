import { useEffect, useState } from "react";
import {
  DASHBOARD_ACTOR_ID,
  approveBudget,
  getEventBudget,
  patchLine,
  regenerateBudget,
  type EventBudgetOut,
  type LineItemOut,
} from "../api/finance";
import { money } from "../util";

type Draft = { unit_cost: string; quantity: string };
const draftsFrom = (lines: LineItemOut[]): Record<string, Draft> =>
  Object.fromEntries(lines.map((l) => [l.id, { unit_cost: l.unit_cost, quantity: String(l.quantity) }]));

export function BudgetDetail({ eventId }: { eventId: string }) {
  const [budget, setBudget] = useState<EventBudgetOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [verdict, setVerdict] = useState<string | null>(null);
  const [suggestedCuts, setSuggestedCuts] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const eb = await getEventBudget(eventId);
        if (cancelled) return;
        setBudget(eb);
        setDrafts(draftsFrom(eb.lines ?? []));
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [eventId]);

  // Client-side live recalculation only, for instant feedback while typing.
  // The saved total always comes back from PATCH's response, never from this.
  function liveTotal(lineId: string, fallback: string): string {
    const d = drafts[lineId];
    if (!d) return fallback;
    const unit = Number(d.unit_cost);
    const qty = Number(d.quantity);
    if (!Number.isFinite(unit) || !Number.isFinite(qty)) return fallback;
    return (unit * qty).toFixed(2);
  }

  async function saveLine(line: LineItemOut) {
    if (!budget) return;
    const d = drafts[line.id];
    if (!d) return;
    setSavingId(line.id);
    setErr(null);
    try {
      const updated = await patchLine(budget.id, line.id, {
        unit_cost: d.unit_cost,
        quantity: Number(d.quantity),
      });
      // Server's recomputed line is the source of truth — replace, don't merge.
      setBudget((prev) =>
        prev ? { ...prev, lines: (prev.lines ?? []).map((l) => (l.id === line.id ? updated : l)) } : prev,
      );
      setDrafts((prev) => ({
        ...prev,
        [line.id]: { unit_cost: updated.unit_cost, quantity: String(updated.quantity) },
      }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSavingId(null);
    }
  }

  async function approve() {
    if (!budget) return;
    setApproving(true);
    setErr(null);
    try {
      setBudget(await approveBudget(budget.id, DASHBOARD_ACTOR_ID));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setApproving(false);
    }
  }

  async function regenerate() {
    setRegenerating(true);
    setErr(null);
    setSuggestedCuts(null);
    try {
      const draft = await regenerateBudget(eventId);
      setBudget(draft.event_budget);
      setVerdict(draft.verdict);
      setSuggestedCuts(draft.suggested_cuts ?? null);
      setDrafts(draftsFrom(draft.event_budget.lines ?? []));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRegenerating(false);
    }
  }

  if (loading) return <p className="muted">Loading budget…</p>;
  if (err && !budget) return <p className="err">Error: {err}</p>;
  if (!budget) return <p className="muted">No budget drafted for this event yet.</p>;

  const lines = budget.lines ?? [];

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Budget</h2>
        <span className={`badge ${budget.status === "approved" ? "ok" : "ink"}`}>{budget.status}</span>
      </div>
      {err && <p className="err">Error: {err}</p>}

      {lines.length === 0 ? (
        <p className="muted">No line items yet — try Regenerate.</p>
      ) : (
        <table className="ledger">
          <thead>
            <tr>
              <th>Category</th>
              <th>Description</th>
              <th style={{ textAlign: "right" }}>Unit cost</th>
              <th style={{ textAlign: "right" }}>Qty</th>
              <th style={{ textAlign: "right" }}>Total</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => {
              const d = drafts[l.id] ?? { unit_cost: l.unit_cost, quantity: String(l.quantity) };
              const dirty = d.unit_cost !== l.unit_cost || d.quantity !== String(l.quantity);
              return (
                <tr key={l.id}>
                  <td>
                    {l.category}
                    {l.source === "ai" && (
                      <span className="badge ink" style={{ marginLeft: 6 }}>
                        AI
                      </span>
                    )}
                  </td>
                  <td>{l.description ?? "—"}</td>
                  <td className="num">
                    <input
                      style={{ width: 80, textAlign: "right" }}
                      value={d.unit_cost}
                      onChange={(e) => setDrafts((prev) => ({ ...prev, [l.id]: { ...d, unit_cost: e.target.value } }))}
                    />
                  </td>
                  <td className="num">
                    <input
                      style={{ width: 50, textAlign: "right" }}
                      value={d.quantity}
                      onChange={(e) => setDrafts((prev) => ({ ...prev, [l.id]: { ...d, quantity: e.target.value } }))}
                    />
                  </td>
                  <td className="num">{money(liveTotal(l.id, l.line_total))}</td>
                  <td>
                    <button className="btn" disabled={!dirty || savingId === l.id} onClick={() => saveLine(l)}>
                      {savingId === l.id ? "Saving…" : "Save"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 14 }}>
        <div>
          <strong>{money(budget.estimated_total)}</strong> estimated
          {budget.stated_cap && <span className="muted"> · cap {money(budget.stated_cap)}</span>}
          {verdict && (
            <span
              className={`badge ${verdict === "OK" ? "ok" : verdict === "TIGHT" ? "hold" : "signal"}`}
              style={{ marginLeft: 8 }}
            >
              {verdict}
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={regenerate} disabled={regenerating}>
            {regenerating ? "Regenerating…" : "Regenerate"}
          </button>
          <button className="btn primary" onClick={approve} disabled={approving || budget.status === "approved"}>
            {approving ? "Approving…" : budget.status === "approved" ? "Approved" : "Approve"}
          </button>
        </div>
      </div>

      {suggestedCuts && suggestedCuts.length > 0 && (
        <div className="callout" style={{ marginTop: 14 }}>
          <div className="tag">Suggested cuts</div>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {suggestedCuts.map((c, i) => (
              <li key={i} style={{ fontSize: 13.5 }}>
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}