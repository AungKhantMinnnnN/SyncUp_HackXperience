// Per-member month calendar. Each member's busy blocks (class, exam, work, club,
// personal) rendered on a standard month grid, in the org's timezone.
import { useEffect, useMemo, useState } from "react";
import { getCalendar, type CalendarData } from "../api/scheduling";
import { DAY } from "../util";

const KIND_COLOR: Record<string, string> = {
  class: "var(--ink)",
  exam: "var(--signal)",
  work: "var(--hold)",
  club: "var(--ok)",
  personal: "var(--muted)",
};
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const pad = (n: number) => String(n).padStart(2, "0");

// Calendar-date of an instant, in the org tz. "en-CA" formats as YYYY-MM-DD.
const dayKey = (iso: string, tz: string) => new Date(iso).toLocaleDateString("en-CA", { timeZone: tz });
const hhmm = (iso: string, tz: string) =>
  new Date(iso).toLocaleTimeString("en-SG", { timeZone: tz, hour: "2-digit", minute: "2-digit" });

function monthCells(y: number, m: number) {
  const daysInMonth = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const firstDow = (new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 6) % 7; // Mon = 0
  const cells: { key: string | null; day: number | null }[] = [];
  for (let i = 0; i < firstDow; i++) cells.push({ key: null, day: null });
  for (let d = 1; d <= daysInMonth; d++) cells.push({ key: `${y}-${pad(m)}-${pad(d)}`, day: d });
  while (cells.length % 7 !== 0) cells.push({ key: null, day: null });
  return cells;
}

export function MemberCalendar({ tz }: { tz: string }) {
  const todayKey = new Date().toLocaleDateString("en-CA", { timeZone: tz });
  const [ty, tm] = todayKey.split("-").map(Number);
  const [anchor, setAnchor] = useState({ y: ty, m: tm });
  const [data, setData] = useState<CalendarData | null>(null);
  const [selected, setSelected] = useState("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const from = new Date(Date.UTC(anchor.y, anchor.m - 1, 1) - 2 * DAY).toISOString();
    const to = new Date(Date.UTC(anchor.y, anchor.m, 1) + 2 * DAY).toISOString();
    getCalendar(from, to)
      .then(setData)
      .catch((e) => setErr((e as Error).message));
  }, [anchor]);

  const memberId = selected || data?.members[0]?.id || "";

  const byDay = useMemo(() => {
    const map: Record<string, { kind: string; start: string; end: string }[]> = {};
    for (const b of data?.busy ?? []) {
      if (b.member_id !== memberId) continue;
      const k = dayKey(b.start_utc, tz);
      (map[k] ??= []).push({ kind: b.kind, start: b.start_utc, end: b.end_utc });
    }
    for (const k of Object.keys(map)) map[k].sort((a, b) => a.start.localeCompare(b.start));
    return map;
  }, [data, memberId, tz]);

  const cells = monthCells(anchor.y, anchor.m);
  const shift = (d: number) => {
    let m = anchor.m + d;
    let y = anchor.y;
    if (m < 1) { m = 12; y--; }
    if (m > 12) { m = 1; y++; }
    setAnchor({ y, m });
  };
  const busyCount = Object.values(byDay).reduce((n, list) => n + list.length, 0);

  return (
    <div>
      <div className="cal-toolbar">
        <div className="cal-nav">
          <button className="btn" onClick={() => shift(-1)} aria-label="Previous month">‹</button>
          <span className="cal-month">{MONTHS[anchor.m - 1]} {anchor.y}</span>
          <button className="btn" onClick={() => shift(1)} aria-label="Next month">›</button>
        </div>
        <span className="tag">{busyCount} busy blocks this month</span>
      </div>

      <div className="member-pills">
        {(data?.members ?? []).map((mem) => (
          <button
            key={mem.id}
            aria-pressed={mem.id === memberId}
            onClick={() => setSelected(mem.id)}
          >
            {mem.full_name}
          </button>
        ))}
      </div>

      {err && <p className="err">Error: {err}</p>}

      <div className="cal-grid">
        {WEEKDAYS.map((w) => (
          <div className="cal-weekday" key={w}>{w}</div>
        ))}
        {cells.map((c, i) => {
          if (c.key === null) return <div className="cal-cell empty" key={i} />;
          const blocks = byDay[c.key] ?? [];
          return (
            <div className={`cal-cell${c.key === todayKey ? " today" : ""}`} key={i}>
              <div className="cal-date">{c.day}</div>
              {blocks.slice(0, 3).map((b, j) => (
                <span
                  className="cal-chip"
                  key={j}
                  style={{ background: KIND_COLOR[b.kind] ?? "var(--muted)" }}
                  title={`${b.kind} · ${hhmm(b.start, tz)}–${hhmm(b.end, tz)}`}
                >
                  {hhmm(b.start, tz)} {b.kind}
                </span>
              ))}
              {blocks.length > 3 && <div className="cal-more">+{blocks.length - 3} more</div>}
            </div>
          );
        })}
      </div>

      <div className="legend">
        {Object.entries(KIND_COLOR).map(([kind, color]) => (
          <span key={kind}>
            <span className="dot" style={{ background: color }} />
            {kind}
          </span>
        ))}
      </div>
    </div>
  );
}
