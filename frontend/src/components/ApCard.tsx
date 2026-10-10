import { Router } from "lucide-react";
import type { StatusResponse } from "../types";
import { SIGNAL_COLOR, SIGNAL_LABEL, classifySignal, formatDbm, signalBarPct } from "../services/signal";

function formatBand(status: StatusResponse): string {
  const parts: string[] = [];
  if (status.band) parts.push(status.band);
  if (status.channel !== null) parts.push(`ch ${status.channel}`);
  if (status.channel_width_mhz !== null) parts.push(`${status.channel_width_mhz} MHz`);
  return parts.join(" · ") || "—";
}

/** The connected access point, front and centre: who it is and how good the link is. */
export function ApCard({ status }: { status: StatusResponse }) {
  const connected = status.connectivity.wifi_connected;
  const cls = classifySignal(status.rssi_dbm);
  const color = SIGNAL_COLOR[cls];
  const estimated = status.platform === "win32" && status.rssi_dbm !== null;

  const title = status.ssid ?? (connected === false ? "Not connected to WiFi" : connected === null ? "WiFi state unknown" : "Connected (network name hidden)");

  return (
    <div className="rounded-card border border-border bg-panel p-5" data-testid="ap-card">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <span className="mt-0.5 rounded-control bg-accent-soft p-2 text-accent">
            <Router size={18} />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-medium text-muted uppercase tracking-wide">Connected access point</p>
            <h2 className="text-xl font-semibold truncate">{title}</h2>
            <p className="font-mono text-sm text-muted mt-0.5" data-testid="ap-bssid">
              {status.bssid ?? (connected ? "BSSID not reported" : "—")}
            </p>
          </div>
        </div>
        <div className="text-right">
          <p className="font-mono text-[32px] font-semibold leading-none font-tabular" style={{ color }}>
            {formatDbm(status.rssi_dbm)}
          </p>
          <p className="text-xs mt-1" style={{ color }}>{SIGNAL_LABEL[cls]}</p>
        </div>
      </div>

      <div className="mt-4 h-1.5 w-full rounded-full bg-panel-alt overflow-hidden" aria-hidden>
        <div className="h-full rounded-full transition-all" style={{ width: `${signalBarPct(status.rssi_dbm)}%`, backgroundColor: color }} />
      </div>

      <dl className="mt-4 grid grid-cols-2 sm:grid-cols-5 gap-x-6 gap-y-3 text-sm">
        <Fact label="Band / channel" value={formatBand(status)} />
        <Fact label="Standard" value={status.phy_mode ?? "—"} />
        <Fact label="Link rate" value={status.tx_bitrate_mbps !== null ? `${Math.round(status.tx_bitrate_mbps)} Mbps` : "—"} />
        <Fact
          label="SNR"
          value={status.snr_db !== null ? `${status.snr_db} dB` : "—"}
          hint={status.snr_db === null ? "Noise floor not reported on this system" : undefined}
        />
        <Fact
          label="Link quality"
          value={status.wireless_quality_score !== null ? `${status.wireless_quality_score} / 100` : "—"}
        />
      </dl>
      {estimated && (
        <p className="mt-3 text-xs text-muted">
          Windows reports signal quality as a percentage; the dBm figure is derived from it (0% = −100 dBm, 100% = −50 dBm).
        </p>
      )}
    </div>
  );
}

function Fact({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div title={hint}>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-mono font-tabular mt-0.5">{value}</dd>
    </div>
  );
}
