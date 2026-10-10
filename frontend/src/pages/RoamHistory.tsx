import { useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import { usePolling } from "../hooks/usePolling";
import { useStatus } from "../hooks/useStatus";
import { api } from "../services/api";
import { LoadingState, ErrorState } from "../components/States";
import { IssueBanner } from "../components/IssueBanner";
import { ApChangesList, ApUsageTable, RouteStrip } from "../components/ApTables";
import { buildApColors } from "../services/signal";
import { explainNoRoams } from "../services/roamExplain";
import { RoamClassificationBadge, RoamConfidenceLabel } from "../components/RoamBadges";
import { formatTimestamp, formatLatency, formatPct } from "../services/format";

export function RoamHistory() {
  const fetcher = useCallback(() => api.listRoamEvents({ limit: 100 }), []);
  const { data: events, error, loading, refetch } = usePolling(fetcher, 15000);
  const { data: status } = useStatus();
  const analysisFetcher = useCallback(() => api.getWifiAnalysis({ minutes: 1440 }), []);
  const { data: analysis } = usePolling(analysisFetcher, 15000);
  const colors = useMemo(() => (analysis ? buildApColors(analysis) : new Map<string | null, string>()), [analysis]);

  if (loading && !events) return <LoadingState label="Loading roam history…" />;
  if (error && !events) return <ErrorState message={error} onRetry={refetch} />;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-lg font-semibold">Roaming</h1>
        <p className="text-sm text-muted mt-0.5">
          Confirmed BSSID transitions on the same network, with an estimated connectivity interruption for each.
        </p>
      </header>

      {status?.wifi_issue && <IssueBanner issue={status.wifi_issue} />}

      <div className="rounded-card border border-border bg-panel">
        {!events || events.length === 0 ? (
          <NoRoams explanation={explainNoRoams(status ?? null, analysis ?? null)} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted uppercase tracking-wide border-b border-border">
                  <th className="py-2.5 px-4 font-medium">Time</th>
                  <th className="py-2.5 px-4 font-medium">SSID</th>
                  <th className="py-2.5 px-4 font-medium">BSSID change</th>
                  <th className="py-2.5 px-4 font-medium">RSSI change</th>
                  <th className="py-2.5 px-4 font-medium">Interruption</th>
                  <th className="py-2.5 px-4 font-medium">Classification</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => {
                  const interruption = e.internet_interruption_ms ?? e.gateway_interruption_ms;
                  return (
                    <tr key={e.id} className="border-b border-border last:border-0 align-top">
                      <td className="py-2.5 px-4 text-xs text-muted font-mono whitespace-nowrap">
                        {formatTimestamp(e.timestamp)}
                      </td>
                      <td className="py-2.5 px-4">{e.ssid ?? "—"}</td>
                      <td className="py-2.5 px-4 font-mono text-xs">
                        {e.previous_bssid ?? "—"} <span className="text-muted">→</span> {e.new_bssid ?? "—"}
                        {e.new_channel !== null && (
                          <div className="text-muted mt-0.5">
                            ch {e.previous_channel ?? "—"} → {e.new_channel} ({e.new_band ?? "—"})
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 px-4 font-mono font-tabular">
                        {e.previous_rssi_dbm ?? "—"} → {e.new_rssi_dbm ?? "—"} dBm
                      </td>
                      <td className="py-2.5 px-4">
                        {e.success === false ? (
                          <span className="text-offline">Never recovered</span>
                        ) : (
                          <span className="font-mono font-tabular">
                            {interruption !== null ? formatLatency(interruption) : "—"}
                          </span>
                        )}
                        {e.packet_loss_during_pct !== null && (
                          <div className="text-xs text-muted mt-0.5">{formatPct(e.packet_loss_during_pct)} loss</div>
                        )}
                      </td>
                      <td className="py-2.5 px-4">
                        <div className="flex flex-col gap-1 items-start">
                          <RoamClassificationBadge classification={e.classification} />
                          <RoamConfidenceLabel confidence={e.confidence} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {analysis && analysis.summary.bssid_available && analysis.aps.length > 0 && (
        <section className="rounded-card border border-border bg-panel p-4" aria-label="Access point history">
          <h3 className="text-sm font-medium">Access points over the last 24 hours</h3>
          <p className="text-xs text-muted mt-0.5 mb-3">
            Which access points this device used, even when no roam was logged.
          </p>
          <RouteStrip segments={analysis.segments} colors={colors} />
          <div className="mt-3">
            <ApUsageTable aps={analysis.aps} colors={colors} />
          </div>
          {analysis.ap_changes.length > 0 && (
            <div className="mt-4">
              <h4 className="text-xs font-medium text-muted uppercase tracking-wide">Access point changes</h4>
              <ApChangesList changes={[...analysis.ap_changes].reverse().slice(0, 20)} colors={colors} />
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function NoRoams({ explanation }: { explanation: { title: string; body: string } }) {
  return (
    <div className="flex flex-col items-center gap-1.5 py-10 px-6 text-center" data-testid="no-roams">
      <p className="text-sm text-text font-medium">{explanation.title}</p>
      <p className="text-xs text-muted max-w-xl">{explanation.body}</p>
      <Link to="/walk-test" className="mt-2 text-xs text-accent hover:underline">
        Start a Walk Test →
      </Link>
    </div>
  );
}
