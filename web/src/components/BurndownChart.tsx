import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getBurndown, getFinanceSummary, type BurndownOut } from "../api/finance";
import { ORG_ID } from "../api/resources";

const fmtMoney = (n: number) =>
  Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);

export function BurndownChart({ semester }: { semester?: string }) {
  const [data, setData] = useState<BurndownOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const sem = semester ?? (await getFinanceSummary()).semester;
        if (!sem) {
          if (!cancelled) setData(null);
          return;
        }
        const bd = await getBurndown(ORG_ID, sem);
        if (!cancelled) setData(bd);
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [semester]);

  // Numeric values exist only long enough to hand to recharts — derived per
  // render, never persisted as parsed floats in state.
  const chartData = useMemo(
    () =>
      (data?.points ?? []).map((p) => ({
        date: p.date,
        committed: Number(p.cumulative_committed),
        actual: Number(p.cumulative_actual),
      })),
    [data],
  );
  const allocated = data ? Number(data.allocated) : 0;

  if (loading) return <p className="muted">Loading burn-down…</p>;
  if (err) return <p className="err">Error: {err}</p>;
  if (!data) return <p className="muted">No semester budget yet.</p>;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Semester burn-down</h2>
        <span className="tag">{data.semester}</span>
      </div>
      {chartData.length === 0 ? (
        <p className="muted">No committed or spent amounts yet this semester.</p>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
            <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => fmtMoney(v)} width={70} />
            <Tooltip formatter={(v: number) => fmtMoney(v)} />
            <Legend />
            <ReferenceLine
              y={allocated}
              stroke="var(--signal)"
              strokeDasharray="6 4"
              label={{ value: `Allocated ${fmtMoney(allocated)}`, position: "insideTopRight", fontSize: 11 }}
            />
            <Line type="monotone" dataKey="committed" name="Committed" stroke="var(--hold)" dot={false} strokeWidth={2} />
            <Line type="monotone" dataKey="actual" name="Actual" stroke="var(--ink)" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}