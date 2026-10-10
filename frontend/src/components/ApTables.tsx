import type { ApChange, ApSegment, ApUsage, WeakStretch } from "../types";
import { UNKNOWN_AP_COLOR, formatDbm, shortBssid } from "../services/signal";
import { formatClock, formatDuration } from "../services/format";

type Colors = Map<string | null, string>;

export function ApSwatch({ bssid, colors }: { bssid: string | null; colors: Colors }) {
  return (
    <span
      className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
      style={{ backgroundColor: colors.get(bssid) ?? UNKNOWN_AP_COLOR }}
      aria-hidden
    />
  );
}

const th = "py-2 px-3 font-medium";
const td = "py-2 px-3";

function BandChannel({ band, channel }: { band: string | null; channel: number | null }) {
  const text = [band, channel !== null ? `ch ${channel}` : null].filter(Boolean).join(" · ");
  return <span className="text-muted">{text || "—"}</span>;
}

/** Every access point used, ranked by time on it. */
export function ApUsageTable({ aps, colors }: { aps: ApUsage[]; colors: Colors }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted uppercase tracking-wide border-b border-border">
            <th className={th}>Access point</th>
            <th className={th}>Band / channel</th>
            <th className={th}>Time on AP</th>
            <th className={th}>Share</th>
            <th className={th}>Avg signal</th>
            <th className={th}>Best / worst</th>
            <th className={th}>Visits</th>
          </tr>
        </thead>
        <tbody>
          {aps.map((a) => (
            <tr key={a.bssid ?? "unknown"} className="border-b border-border last:border-0">
              <td className={`${td} font-mono text-xs`}>
                <span className="flex items-center gap-2">
                  <ApSwatch bssid={a.bssid} colors={colors} />
                  <span>
                    {a.bssid ?? "AP unknown"}
                    {a.ssid && <span className="block font-sans text-muted">{a.ssid}</span>}
                  </span>
                </span>
              </td>
              <td className={td}><BandChannel band={a.band} channel={a.channel} /></td>
              <td className={`${td} font-mono font-tabular`}>{formatDuration(a.total_seconds)}</td>
              <td className={`${td} font-mono font-tabular`}>{a.share_pct.toFixed(0)}%</td>
              <td className={`${td} font-mono font-tabular`}>{formatDbm(a.rssi_avg)}</td>
              <td className={`${td} font-mono font-tabular text-muted`}>
                {a.rssi_max ?? "—"} / {a.rssi_min ?? "—"}
              </td>
              <td className={`${td} font-mono font-tabular`}>{a.visits}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The route as one coloured bar: segment widths are proportional to time, so
 *  "which AP covered how much of the walk" reads at a glance. */
export function RouteStrip({ segments, colors }: { segments: ApSegment[]; colors: Colors }) {
  const total = segments.reduce((sum, s) => sum + Math.max(s.duration_seconds, 0.5), 0);
  if (segments.length === 0 || total === 0) return null;
  return (
    <div>
      <div className="flex h-5 w-full overflow-hidden rounded-control border border-border" data-testid="route-strip">
        {segments.map((s, i) => (
          <div
            key={i}
            title={`${s.bssid ?? "AP unknown"} · ${formatDuration(s.duration_seconds)}${s.rssi_avg !== null ? ` · avg ${s.rssi_avg} dBm` : ""}`}
            style={{ width: `${(Math.max(s.duration_seconds, 0.5) / total) * 100}%`, backgroundColor: colors.get(s.bssid) ?? UNKNOWN_AP_COLOR }}
          />
        ))}
      </div>
    </div>
  );
}

/** Chronological visits: where the client was, in order. */
export function ApSegmentsTable({ segments, colors }: { segments: ApSegment[]; colors: Colors }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted uppercase tracking-wide border-b border-border">
            <th className={th}>From</th>
            <th className={th}>To</th>
            <th className={th}>Access point</th>
            <th className={th}>Duration</th>
            <th className={th}>Signal (min / avg / max)</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((s, i) => (
            <tr key={i} className="border-b border-border last:border-0">
              <td className={`${td} font-mono text-xs text-muted whitespace-nowrap`}>{formatClock(s.start)}</td>
              <td className={`${td} font-mono text-xs text-muted whitespace-nowrap`}>{formatClock(s.end)}</td>
              <td className={`${td} font-mono text-xs`}>
                <span className="flex items-center gap-2"><ApSwatch bssid={s.bssid} colors={colors} />{s.bssid ?? "AP unknown"}</span>
              </td>
              <td className={`${td} font-mono font-tabular`}>{formatDuration(s.duration_seconds)}</td>
              <td className={`${td} font-mono font-tabular text-muted`}>
                {s.rssi_min ?? "—"} / {s.rssi_avg ?? "—"} / {s.rssi_max ?? "—"} dBm
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ApChangesList({ changes, colors }: { changes: ApChange[]; colors: Colors }) {
  if (changes.length === 0) return null;
  return (
    <ul className="divide-y divide-border">
      {changes.map((c, i) => (
        <li key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm">
          <span className="font-mono text-xs text-muted w-20">{formatClock(c.timestamp)}</span>
          <span className="flex items-center gap-2 font-mono text-xs">
            <ApSwatch bssid={c.from_bssid} colors={colors} />{shortBssid(c.from_bssid)}
            <span className="text-muted">→</span>
            <ApSwatch bssid={c.to_bssid} colors={colors} />{shortBssid(c.to_bssid)}
          </span>
          <span className="font-mono text-xs text-muted font-tabular">
            {c.rssi_before ?? "—"} → {c.rssi_after ?? "—"} dBm
          </span>
          {!c.same_ssid && <span className="text-xs text-degraded">different network</span>}
          {c.via_disconnect && <span className="text-xs text-degraded">via a disconnect</span>}
        </li>
      ))}
    </ul>
  );
}

export function WeakStretchesTable({ stretches, colors }: { stretches: WeakStretch[]; colors: Colors }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted uppercase tracking-wide border-b border-border">
            <th className={th}>From</th>
            <th className={th}>To</th>
            <th className={th}>Duration</th>
            <th className={th}>Weakest</th>
            <th className={th}>On AP</th>
          </tr>
        </thead>
        <tbody>
          {stretches.map((w, i) => (
            <tr key={i} className="border-b border-border last:border-0">
              <td className={`${td} font-mono text-xs text-muted whitespace-nowrap`}>{formatClock(w.start)}</td>
              <td className={`${td} font-mono text-xs text-muted whitespace-nowrap`}>{formatClock(w.end)}</td>
              <td className={`${td} font-mono font-tabular`}>{formatDuration(w.duration_seconds)}</td>
              <td className={`${td} font-mono font-tabular text-offline`}>{w.min_rssi_dbm} dBm</td>
              <td className={`${td} font-mono text-xs`}>
                <span className="flex items-center gap-2"><ApSwatch bssid={w.bssid} colors={colors} />{w.bssid ?? "AP unknown"}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
