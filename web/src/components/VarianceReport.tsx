import { useEffect, useMemo, useState } from "react";
import { getVariance, type VarianceOut } from "../api/finance";
import { ORG_ID } from "../api/resources";
import { money } from "../util";

export function VarianceReport() {
  const [data, setData] = useState<VarianceOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getVariance(ORG_ID)
      .then((v) => {
        if (!cancelled) setData(v);
      })
      .catch((e) => {
        if (!cancelled) setErr((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Sorted for display only, per render — largest overrun first.
  const rows = useMemo(() => {
    const lines = data?.lines ?? [];
    return [...lines].sort((a, b) => Number(b.variance) - Number(a.variance));
  }, [data]);

  if (loading) return <p className="muted">Loading variance report…</p>;
  if (err) return <p className="err">Error: {err}</p>;
  if (rows.length === 0) return <p className="muted">No matched expenses yet — nothing to compare.</p>;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Estimate vs. actual</h2>
        <span className="tag">{rows.length} line(s) · largest overrun first</span>
      </div>
      <table className="ledger">
        <thead>
          <tr>
            <th>Event</th>
            <th>Category</th>
            <th>Description</th>
            <th style={{ textAlign: "right" }}>Estimated</th>
            <th style={{ textAlign: "right" }}>Actual</th>
            <th style={{ textAlign: "right" }}>Variance</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const v = Number(r.variance);
            return (
              <tr key={i}>
                <td>{r.event_title}</td>
                <td className="muted">{r.category}</td>
                <td>{r.description ?? "—"}</td>
                <td className="num">{money(r.estimated)}</td>
                <td className="num">{money(r.actual)}</td>
                <td className="num">
                  <span className={v > 0 ? "badge signal" : "badge ok"}>
                    {v > 0 ? "+" : ""}
                    {money(r.variance)}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
} 