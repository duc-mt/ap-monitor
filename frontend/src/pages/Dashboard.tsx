import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useStatus } from "../hooks/useStatus";
import { usePolling } from "../hooks/usePolling";
import { useTargets } from "../hooks/useTargets";
import { api } from "../services/api";
import { ApCard } from "../components/ApCard";
import { IssueBanner } from "../components/IssueBanner";
import { SignalChart } from "../components/SignalChart";
import { ApChangesList, ApSwatch, ApUsageTable } from "../components/ApTables";
import { ConnectivityStateBadge } from "../components/ConnectivityStateBadge";
import { QualityBadge } from "../components/QualityBadge";
import { LatencyChart, type RangeMinutes } from "../components/LatencyChart";
import { TargetStatusTable } from "../components/TargetStatusTable";
import { LoadingState, ErrorState } from "../components/States";
import { buildApColors, formatDbm, shortBssid } from "../services/signal";
import { formatDuration, formatLatency, formatPct } from "../services/format";
import type { SignalAnalysis, StatusResponse } from "../types";

const WEAK_THRESHOLD_DBM = -70;
const WINDOWS = [
  { label: "5 min", minutes: 5 },
  { label: "15 min", minutes: 15 },
  { label: "1 hour", minutes: 60 },
  { label: "6 hours", minutes: 360 },
  { label: "24 hours", minutes: 1440 },
];

export function Dashboard() {
  const { data: status, error: statusError, loading: statusLoading, refetch: refetchStatus } = useStatus();
  const [windowMinutes, setWindowMinutes] = useState(15);

  const analysisFetcher = useCallback(
    () => api.getWifiAnalysis({ minutes: windowMinutes, weak_threshold_dbm: WEAK_THRESHOLD_DBM }),
    [windowMinutes],
  );
  const { data: analysis } = usePolling(analysisFetcher, 5000, [windowMinutes]);
  const colors = useMemo(() => (analysis ? buildApColors(analysis) : new Map<string | null, string>()), [analysis]);

  if (statusLoading && !status) return <LoadingState label="Connecting to AP Monitor…" />;
  if (statusError && !status) return <ErrorState message={statusError} onRetry={refetchStatus} />;
  if (!status) return null;

  const summary = analysis?.summary;

  return (
    <div className="space-y-6">
      <header className="sticky top-0 z-10 -mx-6 lg:-mx-8 -mt-6 lg:-mt-8 mb-6 px-6 lg:px-8 py-4 backdrop-blur-md bg-slate-50/80 dark:bg-slate-900/80 border-b border-border flex items-center justify-between transition-all-fast">
        <div>
          <h1 className="text-xl font-extrabold tracking-tight text-text">Dashboard</h1>
          <p className="text-xs text-muted font-medium mt-0.5">Which access point you are on, how strong it is, and when it changes.</p>
        </div>
        <ConnectivityStateBadge state={status.connectivity.overall} />
      </header>

      {status.wifi_issue && <IssueBanner issue={status.wifi_issue} />}

      <ApCard status={status} />

      <section className="rounded-card border border-border bg-panel p-4" aria-label="Signal timeline">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <div>
            <h3 className="text-sm font-medium">Signal over time</h3>
            <p className="text-xs text-muted mt-0.5">
              The line changes colour whenever the connection moves to a different access point.
            </p>
          </div>
          <div className="flex items-center rounded-control border border-border p-0.5 gap-0.5" role="group" aria-label="Time window">
            {WINDOWS.map((w) => (
              <button
                key={w.minutes}
                onClick={() => setWindowMinutes(w.minutes)}
                aria-pressed={windowMinutes === w.minutes}
                className={`px-2.5 py-1 text-xs rounded-[4px] transition-colors ${
                  windowMinutes === w.minutes ? "bg-accent-soft text-accent font-medium" : "text-muted hover:text-text"
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>

        {analysis ? (
          <>
            <SignalChart points={analysis.points} colors={colors} weakThreshold={WEAK_THRESHOLD_DBM} apChanges={analysis.ap_changes} />
            <ApLegend analysis={analysis} colors={colors} />
            {summary && summary.connected_sample_count > 0 && (
              <p className="mt-3 text-xs text-muted" data-testid="window-summary">
                Average {formatDbm(summary.rssi_avg)} · weakest {formatDbm(summary.rssi_min)} ·{" "}
                {summary.pct_samples_weak !== null
                  ? `${summary.pct_samples_weak.toFixed(0)}% of the time below ${WEAK_THRESHOLD_DBM} dBm · `
                  : ""}
                {summary.bssid_available
                  ? `${summary.distinct_aps} access point${summary.distinct_aps === 1 ? "" : "s"}, ${summary.ap_change_count} change${
                      summary.ap_change_count === 1 ? "" : "s"
                    }`
                  : "access point address not available"}
              </p>
            )}
          </>
        ) : (
          <LoadingState label="Loading signal history…" />
        )}
      </section>

      {analysis && analysis.summary.bssid_available && analysis.aps.length > 0 && (
        <section className="rounded-card border border-border bg-panel p-4" aria-label="Access points">
          <h3 className="text-sm font-medium mb-3">Access points in this period</h3>
          <ApUsageTable aps={analysis.aps} colors={colors} />
        </section>
      )}

      {analysis && analysis.ap_changes.length > 0 && (
        <section className="rounded-card border border-border bg-panel p-4" aria-label="Recent access point changes">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-sm font-medium">Access point changes</h3>
            <Link to="/roaming" className="text-xs text-accent hover:underline">
              Roaming details →
            </Link>
          </div>
          <ApChangesList changes={[...analysis.ap_changes].reverse().slice(0, 6)} colors={colors} />
        </section>
      )}

      <InternetSection status={status} />
    </div>
  );
}

function ApLegend({ analysis, colors }: { analysis: SignalAnalysis; colors: Map<string | null, string> }) {
  const aps = analysis.aps.filter((a) => a.bssid !== null);
  if (aps.length === 0) return null;
  return (
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5" aria-label="Access point legend">
      {aps.map((a) => (
        <li key={a.bssid} className="flex items-center gap-1.5 text-xs">
          <ApSwatch bssid={a.bssid} colors={colors} />
          <span className="font-mono">{shortBssid(a.bssid)}</span>
          <span className="text-muted">
            {[a.band, a.channel !== null ? `ch ${a.channel}` : null].filter(Boolean).join(" ")} · {a.share_pct.toFixed(0)}%
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Gateway / internet reachability: useful context ("is the problem the AP or
 *  upstream of it?") but deliberately secondary to the access point itself. */
function InternetSection({ status }: { status: StatusResponse }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="rounded-card border border-border bg-panel p-5 shadow-sm transition-all-fast" aria-label="Upstream reachability">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold tracking-tight text-text">Upstream reachability</h3>
          <p className="text-xs text-muted font-medium mt-0.5">
            Whether traffic gets past the access point: {status.targets_reachable} of {status.targets_total} targets reachable
          </p>
        </div>
        <QualityBadge quality={status.quality} />
      </div>

      <dl className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
        <Mini label="Internet" value={status.online ? "Online" : "Offline"} />
        <Mini label="Latency" value={formatLatency(status.latency_ms)} />
        <Mini label="Packet loss" value={formatPct(status.packet_loss)} />
        <Mini label="Jitter" value={formatLatency(status.jitter_ms)} />
      </dl>

      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="mt-3 flex items-center gap-1 text-xs text-muted hover:text-text"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {open ? "Hide" : "Show"} latency chart and targets
      </button>
      {open && <InternetDetails status={status} />}
      <p className="mt-2 text-[11px] text-muted">Monitoring for {formatDuration(status.monitoring_uptime_seconds)}</p>
    </section>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-mono font-tabular mt-0.5">{value}</dd>
    </div>
  );
}

function InternetDetails({ status }: { status: StatusResponse }) {
  const { targets } = useTargets();
  const [rangeMinutes, setRangeMinutes] = useState<RangeMinutes>(5);
  const measurementsFetcher = useCallback(() => {
    const start = new Date(Date.now() - rangeMinutes * 60_000).toISOString();
    return api.listMeasurements({ start, limit: 5000 });
  }, [rangeMinutes]);
  const { data: measurements } = usePolling(measurementsFetcher, 5000, [rangeMinutes]);

  return (
    <div className="mt-4 space-y-4">
      <LatencyChart
        measurements={measurements ?? []}
        targets={targets.filter((t) => t.enabled)}
        rangeMinutes={rangeMinutes}
        onRangeChange={setRangeMinutes}
      />
      <TargetStatusTable targets={status.targets} />
    </div>
  );
}
