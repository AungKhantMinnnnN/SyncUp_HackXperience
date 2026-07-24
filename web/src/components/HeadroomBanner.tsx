import { useEffect, useState } from "react";
import { getFinanceSummary, getHeadroom, type HeadroomOut } from "../api/finance";
import { ORG_ID } from "../api/resources";

const VERDICT_BADGE: Record<string, string> = { OK: "ok", TIGHT: "hold", OVER: "signal" };

// Number() only ever happens right here, right before formatting — the raw
// string from the API is what lives in state.
const fmtMoney = (raw: string) =>
  Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(
    Number(raw),
  );

/** Persistent top strip. Mount once near the top of App.tsx, above the tab nav. */
export function HeadroomBanner({ semester }: { semester?: string }) {
  const [data, setData] = useState<HeadroomOut | null>(null);
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
        const hr = await getHeadroom(ORG_ID, sem);
        if (!cancelled) setData(hr);
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

  if (loading) return <div className="headroom-banner muted">Loading budget headroom…</div>;
  if (err) return <div className="headroom-banner err">Headroom unavailable: {err}</div>;
  if (!data) return null; // no semester budget set up yet — nothing to show, not an error

  return (
    <div className="headroom-banner">
      <span className={`badge ${VERDICT_BADGE[data.verdict] ?? "ink"}`}>{data.verdict}</span>
      <span className="headroom-text">
        <strong>{fmtMoney(data.remaining)}</strong> remaining of {fmtMoney(data.allocated)} — {data.semester}
      </span>
    </div>
  );
}