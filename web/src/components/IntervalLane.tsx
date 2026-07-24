// The signature. A numeric track where claims are bars and overlaps/overflows flag
// crimson. Axis units are arbitrary numbers — epoch-ms for time, dollars for money —
// so the same visual carries scheduling, resources, and budget: one primitive, three
// domains.
export type Tone = "ink" | "ok" | "hold" | "signal" | "ghost";
export interface Bar {
  start: number;
  end: number;
  tone: Tone;
  label?: string;
}
export interface LaneRow {
  label: string;
  sub?: string;
  bars: Bar[];
}
export interface Marker {
  at: number;
  label: string;
}

interface Props {
  rows: LaneRow[];
  start: number;
  end: number;
  markers?: Marker[];
  ticks?: string[];
}

const pct = (v: number, start: number, end: number) =>
  Math.max(0, Math.min(100, ((v - start) / (end - start || 1)) * 100));

export function IntervalLane({ rows, start, end, markers = [], ticks = [] }: Props) {
  return (
    <div>
      <div className="lane">
        {rows.map((row, i) => (
          <div className="lane-row" key={i}>
            <div className="lane-label">
              {row.label}
              {row.sub && <small>{row.sub}</small>}
            </div>
            <div className="lane-track">
              {markers.map((m, j) => (
                <div className="lane-marker" key={j} style={{ left: `${pct(m.at, start, end)}%` }}>
                  {i === 0 && <span>{m.label}</span>}
                </div>
              ))}
              {row.bars.map((b, j) => {
                const left = pct(b.start, start, end);
                const width = Math.max(pct(b.end, start, end) - left, 1.2);
                return (
                  <div
                    className={`lane-bar ${b.tone}`}
                    key={j}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    title={b.label}
                  >
                    {b.label}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      {ticks.length > 0 && (
        <div className="lane-ticks">
          <div />
          <div className="row">
            {ticks.map((t, i) => (
              <span key={i}>{t}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
