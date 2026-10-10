import type { ConnectivityState } from "../types";

export const CONNECTIVITY_COLOR: Record<ConnectivityState, string> = {
  unknown: "var(--color-unknown)",
  wifi_disconnected: "var(--color-offline)",
  wifi_connected: "var(--color-degraded)",
  gateway_unavailable: "var(--color-offline)",
  gateway_available: "var(--color-degraded)",
  internet_unavailable: "var(--color-offline)",
  degraded: "var(--color-degraded)",
  internet_available: "var(--color-healthy)",
};

export const CONNECTIVITY_LABEL: Record<ConnectivityState, string> = {
  unknown: "Unknown",
  wifi_disconnected: "WiFi disconnected",
  wifi_connected: "WiFi connected",
  gateway_unavailable: "Gateway unavailable",
  gateway_available: "Gateway available",
  internet_unavailable: "Internet unavailable",
  degraded: "Degraded",
  internet_available: "Internet available",
};

export function ConnectivityStateBadge({ state }: { state: ConnectivityState }) {
  const color = CONNECTIVITY_COLOR[state];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium"
      style={{ borderColor: color, color }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
      {CONNECTIVITY_LABEL[state]}
    </span>
  );
}
