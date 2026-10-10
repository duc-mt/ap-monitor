import { useCallback, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Download, Trash2 } from "lucide-react";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import { StatCard } from "../components/StatCard";
import { SignalChart } from "../components/SignalChart";
import { IssueBanner } from "../components/IssueBanner";
import { ApChangesList, ApSegmentsTable, ApUsageTable, RouteStrip, WeakStretchesTable, ApSwatch } from "../components/ApTables";
import { LoadingState, ErrorState, EmptyState } from "../components/States";
import { buildApColors, formatDbm, shortBssid } from "../services/signal";
import { formatDuration, formatTimestamp } from "../services/format";

const THRESHOLDS = [-65, -70, -75, -80];

/** The answer a walk test exists to give: where along the route was the
 *  signal good, where did it get weak, and which access point covered what. */
export function WalkTestResult() {
  const { id } = useParams();
  const walkTestId = Number(id);
  const navigate = useNavigate();
  const [threshold, setThreshold] = useState(-70);

  const sessionFetcher = useCallback(() => api.getWalkTest(walkTestId), [walkTestId]);
  const { data: session, error: sessionError, loading: sessionLoading } = usePolling(sessionFetcher, 3000, [walkTestId]);

  const recording = session?.status === "recording";
  const analysisFetcher = useCallback(
    () => api.getWalkTestAnalysis(walkTestId, { weak_threshold_dbm: threshold }),
    [walkTestId, threshold],
  );
  const { data: analysis, error: analysisError } = usePolling(analysisFetcher, recording ? 2000 : 0, [walkTestId, threshold, recording]);
  const colors = useMemo(() => (analysis ? buildApColors(analysis) : new Map<string | null, string>()), [analysis]);

  if (!Number.isFinite(walkTestId)) return <ErrorState message="That is not a valid walk test." />;
  if (sessionLoading && !session) return <LoadingState label="Loading walk test…" />;
  if (sessionError && !session) return <ErrorState message={sessionError} />;
  if (!session) return null;

  const remove = async () => {
    if (!window.confirm(`Delete "${session.name}" and its ${session.sample_count} samples?`)) return;
    await api.deleteWalkTest(session.id);
    navigate("/walk-test");
  };

  const s = analysis?.summary;
  const weakNote =
    s && s.pct_samples_weak !== null
      ? `${s.pct_samples_weak.toFixed(0)}% of samples`
      : "—";

  return (
    <div className="space-y-5">
      <Link to="/walk-test" className="inline-flex items-center gap-1 text-xs text-muted hover:text-text">
        <ArrowLeft size={13} /> All walk tests
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold truncate">{session.name}</h1>
          <p className="text-sm text-muted mt-0.5">
            {[session.site, session.area].filter(Boolean).join(" · ") || "No site"} · {session.interface} · started{" "}
            {formatTimestamp(session.started_at)}
            {recording ? " · still recording" : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <a
            href={api.walkTestExportUrl(session.id)}
            className="flex items-center gap-1.5 rounded-control border border-border text-sm px-3 py-2 text-muted hover:text-text hover:border-accent transition-colors"
          >
            <Download size={14} /> Export CSV
          </a>
          <button
            onClick={remove}
            className="flex items-center gap-1.5 rounded-control border border-border text-sm px-3 py-2 text-muted hover:text-offline hover:border-offline transition-colors"
          >
            <Trash2 size={14} /> Delete
          </button>
        </div>
      </header>

      {analysisError && !analysis && <ErrorState message={analysisError} />}
      {!analysis && !analysisError && <LoadingState label="Analysing samples…" />}

      {analysis && s && s.sample_count === 0 && (
        <div className="rounded-card border border-border bg-panel">
          <EmptyState title="No samples were recorded" description="The session ended before any WiFi readings were taken." />
        </div>
      )}

      {analysis && s && s.sample_count > 0 && (
        <>
          {!s.bssid_available && (
            <IssueBanner
              issue={{
                code: "bssid_unavailable",
                title: "Access point addresses were not available during this walk",
                detail:
                  "Signal strength was recorded, but the system did not report which access point you were on, so the per-AP breakdown below cannot be shown. See the banner on the Dashboard for how to enable it.",
              }}
            />
          )}

          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <StatCard label="Average signal" value={s.rssi_avg !== null ? String(Math.round(s.rssi_avg)) : "—"} unit={s.rssi_avg !== null ? "dBm" : undefined} />
            <StatCard
              label="Weakest point"
              value={s.rssi_min !== null ? String(s.rssi_min) : "—"}
              unit={s.rssi_min !== null ? "dBm" : undefined}
              accentColor={s.rssi_min !== null && s.rssi_min < threshold ? "var(--color-offline)" : undefined}
            />
            <StatCard
              label={`Below ${threshold} dBm`}
              value={weakNote}
              accentColor={s.pct_samples_weak !== null && s.pct_samples_weak > 10 ? "var(--color-degraded)" : undefined}
            />
            <StatCard label="Access points used" value={s.bssid_available ? String(s.distinct_aps) : "—"} />
            <StatCard label="AP changes" value={s.bssid_available ? String(s.ap_change_count) : "—"} sublabel={`${formatDuration(s.duration_seconds)} · ${s.sample_count} samples`} />
          </div>

          <section className="rounded-card border border-border bg-panel p-4" aria-label="Signal along the walk">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
              <div>
                <h3 className="text-sm font-medium">Signal along the walk</h3>
                <p className="text-xs text-muted mt-0.5">Colour = access point. Hover for exact readings.</p>
              </div>
              <label className="flex items-center gap-2 text-xs text-muted">
                Weak below
                <select
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                  className="rounded-control border border-border bg-panel-alt px-2 py-1 text-xs text-text"
                >
                  {THRESHOLDS.map((t) => (
                    <option key={t} value={t}>{t} dBm</option>
                  ))}
                </select>
              </label>
            </div>
            <SignalChart points={analysis.points} colors={colors} weakThreshold={threshold} apChanges={analysis.ap_changes} height={300} />
            {s.bssid_available && analysis.segments.length > 0 && (
              <div className="mt-4">
                <p className="text-xs text-muted mb-1.5">Route by access point (width = time spent)</p>
                <RouteStrip segments={analysis.segments} colors={colors} />
                <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                  {analysis.aps.filter((a) => a.bssid).map((a) => (
                    <li key={a.bssid} className="flex items-center gap-1.5 text-xs">
                      <ApSwatch bssid={a.bssid} colors={colors} />
                      <span className="font-mono">{shortBssid(a.bssid)}</span>
                      <span className="text-muted">{a.share_pct.toFixed(0)}% · avg {formatDbm(a.rssi_avg)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <section className="rounded-card border border-border bg-panel p-4" aria-label="Weak signal spots">
            <h3 className="text-sm font-medium mb-1">Weak-signal spots</h3>
            {analysis.weak_stretches.length === 0 ? (
              <p className="text-sm text-muted">
                No stretch of two or more consecutive readings fell below {threshold} dBm. Coverage along this route looks solid.
              </p>
            ) : (
              <>
                <p className="text-xs text-muted mb-2">
                  Stretches where the signal stayed below {threshold} dBm. Match the times to where you were standing.
                </p>
                <WeakStretchesTable stretches={analysis.weak_stretches} colors={colors} />
              </>
            )}
          </section>

          {s.bssid_available && analysis.aps.length > 0 && (
            <section className="rounded-card border border-border bg-panel p-4" aria-label="Access points used">
              <h3 className="text-sm font-medium mb-3">Access points used</h3>
              <ApUsageTable aps={analysis.aps} colors={colors} />
            </section>
          )}

          {s.bssid_available && analysis.ap_changes.length > 0 && (
            <section className="rounded-card border border-border bg-panel p-4" aria-label="Access point changes">
              <h3 className="text-sm font-medium mb-1">Access point changes</h3>
              <p className="text-xs text-muted mb-1">
                Where the connection moved to another access point. A late change at a low signal usually means the device held on to the old AP for too long.
              </p>
              <ApChangesList changes={analysis.ap_changes} colors={colors} />
            </section>
          )}

          {s.bssid_available && analysis.segments.length > 0 && (
            <section className="rounded-card border border-border bg-panel p-4" aria-label="Route timeline">
              <h3 className="text-sm font-medium mb-3">Route timeline</h3>
              <ApSegmentsTable segments={analysis.segments} colors={colors} />
            </section>
          )}
        </>
      )}
    </div>
  );
}
