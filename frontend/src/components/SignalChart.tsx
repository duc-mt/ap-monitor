import { useMemo, useState } from "react";
import type { ApChange, SignalPoint } from "../types";
import { UNKNOWN_AP_COLOR, formatDbm, shortBssid } from "../services/signal";

const W = 900;
const PAD = { l: 46, r: 14, t: 14, b: 26 };
const Y_MIN = -100;
const Y_MAX = -30;
const Y_TICKS = [-30, -40, -50, -60, -70, -80, -90, -100];

interface Props {
  points: SignalPoint[];
  colors: Map<string | null, string>;
  weakThreshold: number;
  apChanges?: ApChange[];
  /** viewBox height; the chart scales to its container's width. */
  height?: number;
}

interface Run {
  color: string;
  bssid: string | null;
  pts: Array<[number, number]>;
}

function timeLabel(ms: number, spanMs: number): string {
  const d = new Date(ms);
  return spanMs > 10 * 60_000
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** RSSI over time as an SVG line that changes colour with the access point,
 *  so a roam is visible as a colour change. Disconnected stretches are shaded,
 *  the "weak" threshold is drawn, and AP changes get a labelled marker. */
export function SignalChart({ points, colors, weakThreshold, apChanges = [], height = 260 }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const H = height;
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;

  const model = useMemo(() => {
    const times = points.map((p) => new Date(p.t).getTime());
    const tMin = times.length ? Math.min(...times) : 0;
    let tMax = times.length ? Math.max(...times) : 1;
    if (tMax <= tMin) tMax = tMin + 1000;
    const x = (ms: number) => PAD.l + ((ms - tMin) / (tMax - tMin)) * innerW;
    const y = (rssi: number) => PAD.t + ((Y_MAX - Math.max(Y_MIN, Math.min(Y_MAX, rssi))) / (Y_MAX - Y_MIN)) * innerH;

    const runs: Run[] = [];
    let cur: Run | null = null;
    points.forEach((p, i) => {
      if (!p.connected || p.rssi === null) {
        cur = null;
        return;
      }
      const color = colors.get(p.bssid) ?? UNKNOWN_AP_COLOR;
      const pt: [number, number] = [x(times[i]), y(p.rssi)];
      if (cur && cur.color === color) {
        cur.pts.push(pt);
      } else {
        const next: Run = { color, bssid: p.bssid, pts: [] };
        if (cur) next.pts.push(cur.pts[cur.pts.length - 1]); // keep the line continuous across an AP change
        next.pts.push(pt);
        runs.push(next);
        cur = next;
      }
    });

    const gaps: Array<[number, number]> = [];
    points.forEach((p, i) => {
      if (p.connected) return;
      const x0 = x(times[i]);
      const x1 = i + 1 < points.length ? x(times[i + 1]) : x0 + 3;
      const last = gaps[gaps.length - 1];
      if (last && Math.abs(last[1] - x0) < 0.5) last[1] = x1;
      else gaps.push([x0, Math.max(x1, x0 + 2)]);
    });

    return { times, tMin, tMax, x, y, runs, gaps };
  }, [points, colors, innerW, innerH]);

  const hasData = model.runs.length > 0;
  if (!hasData) {
    return (
      <div className="flex items-center justify-center text-sm text-muted" style={{ height: 160 }}>
        No signal readings in this period.
      </div>
    );
  }

  const span = model.tMax - model.tMin;
  const xTicks = Array.from({ length: 5 }, (_, i) => model.tMin + (span * i) / 4);
  const hp = hover !== null ? points[hover] : null;

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const sx = ((e.clientX - rect.left) / rect.width) * W;
    let best = -1;
    let bestD = Infinity;
    points.forEach((p, i) => {
      if (!p.connected || p.rssi === null) return;
      const d = Math.abs(model.x(model.times[i]) - sx);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    setHover(best >= 0 ? best : null);
  };

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto select-none"
        role="img"
        aria-label="Signal strength over time, coloured by access point"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {/* weak-signal zone */}
        <rect
          x={PAD.l} y={model.y(weakThreshold)} width={innerW} height={PAD.t + innerH - model.y(weakThreshold)}
          style={{ fill: "var(--color-offline)", opacity: 0.07 }}
        />
        {Y_TICKS.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={model.y(t)} y2={model.y(t)} style={{ stroke: "var(--color-border)" }} strokeWidth={1} />
            <text x={PAD.l - 6} y={model.y(t) + 3} textAnchor="end" fontSize={10} style={{ fill: "var(--color-muted)" }}>
              {t}
            </text>
          </g>
        ))}
        <line
          x1={PAD.l} x2={W - PAD.r} y1={model.y(weakThreshold)} y2={model.y(weakThreshold)}
          strokeDasharray="5 4" strokeWidth={1.2} style={{ stroke: "var(--color-offline)" }} data-testid="weak-threshold"
        />
        <text x={W - PAD.r - 2} y={model.y(weakThreshold) - 4} textAnchor="end" fontSize={10} style={{ fill: "var(--color-offline)" }}>
          weak &lt; {weakThreshold} dBm
        </text>

        {model.gaps.map(([a, b], i) => (
          <rect key={i} x={a} y={PAD.t} width={b - a} height={innerH} style={{ fill: "var(--color-offline)", opacity: 0.18 }} data-testid="disconnected-band" />
        ))}

        {xTicks.map((t, i) => (
          <text key={i} x={model.x(t)} y={H - 8} textAnchor={i === 0 ? "start" : i === 4 ? "end" : "middle"} fontSize={10} style={{ fill: "var(--color-muted)" }}>
            {timeLabel(t, span)}
          </text>
        ))}

        {apChanges.map((c, i) => {
          const cx = model.x(new Date(c.timestamp).getTime());
          if (cx < PAD.l || cx > W - PAD.r) return null;
          const nearRight = cx > W - 120;
          return (
            <g key={i} data-testid="ap-change-marker">
              <line x1={cx} x2={cx} y1={PAD.t} y2={PAD.t + innerH} strokeDasharray="3 3" strokeWidth={1} style={{ stroke: "var(--color-text)", opacity: 0.55 }} />
              <text x={nearRight ? cx - 4 : cx + 4} y={PAD.t + 10} textAnchor={nearRight ? "end" : "start"} fontSize={10} style={{ fill: "var(--color-text)" }}>
                → {shortBssid(c.to_bssid)}
              </text>
            </g>
          );
        })}

        {model.runs.map((r, i) =>
          r.pts.length > 1 ? (
            <polyline
              key={i} points={r.pts.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(" ")}
              fill="none" stroke={r.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
              data-testid="signal-line" data-bssid={r.bssid ?? ""}
            />
          ) : (
            <circle key={i} cx={r.pts[0][0]} cy={r.pts[0][1]} r={2.5} fill={r.color} data-testid="signal-line" data-bssid={r.bssid ?? ""} />
          ),
        )}

        {hp && hp.rssi !== null && (
          <g pointerEvents="none">
            <line x1={model.x(model.times[hover!])} x2={model.x(model.times[hover!])} y1={PAD.t} y2={PAD.t + innerH} style={{ stroke: "var(--color-muted)" }} strokeWidth={1} />
            <circle cx={model.x(model.times[hover!])} cy={model.y(hp.rssi)} r={4} fill={colors.get(hp.bssid) ?? UNKNOWN_AP_COLOR} stroke="var(--color-bg)" strokeWidth={1.5} />
          </g>
        )}
      </svg>

      {hp && hp.rssi !== null && (
        <div
          className="absolute top-1 pointer-events-none rounded-control border border-border bg-panel px-2.5 py-1.5 text-xs shadow-none"
          style={{
            left: `${(model.x(model.times[hover!]) / W) * 100}%`,
            transform: model.x(model.times[hover!]) > W * 0.6 ? "translateX(-105%)" : "translateX(8px)",
          }}
          data-testid="signal-tooltip"
        >
          <div className="font-mono font-tabular">{formatDbm(hp.rssi)}{hp.snr !== null ? ` · SNR ${hp.snr} dB` : ""}</div>
          <div className="text-muted">
            {hp.bssid ?? "AP unknown"}{hp.channel !== null ? ` · ch ${hp.channel}` : ""}
          </div>
          <div className="text-muted">{new Date(hp.t).toLocaleTimeString()}</div>
        </div>
      )}
    </div>
  );
}
