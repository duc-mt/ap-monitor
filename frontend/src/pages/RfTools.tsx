import { useCallback, useState } from "react";
import { RadioTower, RefreshCw } from "lucide-react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError } from "../services/api";
import { EmptyState } from "../components/States";
import type { EnvironmentScanResult } from "../types";

const inputClass =
  "w-full rounded-control border border-border bg-panel-alt px-3 py-2 text-sm text-text placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent";

export function RfTools() {
  const interfacesFetcher = useCallback(() => api.listWifiInterfaces(), []);
  const { data: interfaces } = usePolling(interfacesFetcher, 30000);

  const [selectedInterface, setSelectedInterface] = useState<string>("");
  const [result, setResult] = useState<EnvironmentScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runScan = async () => {
    setScanning(true);
    setError(null);
    try {
      const scan = await api.scanEnvironment(selectedInterface || undefined);
      setResult(scan);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Scan failed.");
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-lg font-semibold">RF Tools</h1>
        <p className="text-sm text-muted mt-0.5">
          On-demand scan for neighboring networks. Never run automatically - this actively probes the radio, which
          the background monitoring loop deliberately avoids.
        </p>
      </header>

      <div className="rounded-card border border-border bg-panel p-4 flex flex-wrap items-end gap-3">
        <div className="min-w-[200px]">
          <label className="block text-xs font-medium text-muted mb-1">Interface</label>
          <select className={inputClass} value={selectedInterface} onChange={(e) => setSelectedInterface(e.target.value)}>
            <option value="">Auto (currently active)</option>
            {(interfaces ?? []).map((i) => (
              <option key={i.name} value={i.name}>
                {i.name} {i.is_active ? "(active)" : ""}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={runScan}
          disabled={scanning}
          className="flex items-center gap-1.5 rounded-control bg-accent text-bg text-sm font-medium px-3 py-2 hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {scanning ? <RefreshCw size={15} className="animate-spin" /> : <RadioTower size={15} />}
          {scanning ? "Scanning…" : "Scan environment"}
        </button>
      </div>

      {error && (
        <div className="rounded-card border border-offline/40 bg-panel p-4 text-sm text-offline">{error}</div>
      )}

      {result && (
        <div className="rounded-card border border-border bg-panel">
          <div className="px-4 py-3 border-b border-border text-sm text-muted">
            {result.neighbors.length} network{result.neighbors.length === 1 ? "" : "s"} found on {result.interface}
            {result.connected_channel !== null && (
              <> · you're on channel {result.connected_channel} ({result.connected_band})</>
            )}
          </div>
          {result.neighbors.length === 0 ? (
            <EmptyState title="No neighboring networks found" description="Try scanning again, or check adapter permissions." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted uppercase tracking-wide border-b border-border">
                    <th className="py-2.5 px-4 font-medium">SSID</th>
                    <th className="py-2.5 px-4 font-medium">Channel</th>
                    <th className="py-2.5 px-4 font-medium">PHY mode</th>
                    <th className="py-2.5 px-4 font-medium">Security</th>
                    <th className="py-2.5 px-4 font-medium">Signal</th>
                  </tr>
                </thead>
                <tbody>
                  {result.neighbors
                    .slice()
                    .sort((a, b) => (b.rssi_dbm ?? -999) - (a.rssi_dbm ?? -999))
                    .map((n, idx) => (
                      <tr key={`${n.bssid ?? n.ssid}-${idx}`} className="border-b border-border last:border-0">
                        <td className="py-2.5 px-4">
                          <div className="font-medium">{n.ssid ?? "(hidden)"}</div>
                          {n.bssid && <div className="text-xs text-muted font-mono">{n.bssid}</div>}
                        </td>
                        <td className="py-2.5 px-4">
                          <span className={n.is_co_channel ? "text-degraded font-medium" : ""}>
                            {n.channel ?? "—"}
                            {n.channel_width_mhz ? ` (${n.channel_width_mhz}MHz)` : ""}
                          </span>
                          {n.is_co_channel && (
                            <div className="text-[10px] uppercase tracking-wide text-degraded">co-channel</div>
                          )}
                        </td>
                        <td className="py-2.5 px-4 text-muted">{n.phy_mode ?? "—"}</td>
                        <td className="py-2.5 px-4 text-muted">{n.security ?? "—"}</td>
                        <td className="py-2.5 px-4 font-mono font-tabular">
                          {n.rssi_dbm !== null ? `${n.rssi_dbm} dBm` : "—"}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
