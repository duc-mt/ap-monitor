import type { SignalAnalysis } from "../types";

/** Distinct, colour-blind-considerate hues for telling access points apart.
 *  Chosen to stay legible on both the dark and light themes. */
export const AP_PALETTE = ["#14b8a6", "#f59e0b", "#6366f1", "#ec4899", "#a855f7", "#84cc16", "#0ea5e9", "#f97316"];
export const UNKNOWN_AP_COLOR = "#8b93a7";

export type SignalClass = "excellent" | "good" | "fair" | "weak" | "poor" | "none";

export function classifySignal(rssi: number | null | undefined): SignalClass {
  if (rssi === null || rssi === undefined) return "none";
  if (rssi >= -50) return "excellent";
  if (rssi >= -60) return "good";
  if (rssi >= -70) return "fair";
  if (rssi >= -80) return "weak";
  return "poor";
}

export const SIGNAL_LABEL: Record<SignalClass, string> = {
  excellent: "Excellent",
  good: "Good",
  fair: "Fair",
  weak: "Weak",
  poor: "Very weak",
  none: "No signal data",
};

export const SIGNAL_COLOR: Record<SignalClass, string> = {
  excellent: "var(--color-healthy)",
  good: "var(--color-healthy)",
  fair: "var(--color-degraded)",
  weak: "var(--color-offline)",
  poor: "var(--color-offline)",
  none: "var(--color-unknown)",
};

/** 0-100 for a signal-strength bar, mapping -90 dBm (empty) .. -40 dBm (full). */
export function signalBarPct(rssi: number | null | undefined): number {
  if (rssi === null || rssi === undefined) return 0;
  return Math.max(0, Math.min(100, Math.round(((rssi + 90) / 50) * 100)));
}

/** A stable colour for every BSSID in an analysis, in order of airtime, so the
 *  same AP is the same colour in the chart, legend, table and route strip. */
export function buildApColors(analysis: Pick<SignalAnalysis, "aps" | "points" | "segments">): Map<string | null, string> {
  const colors = new Map<string | null, string>();
  colors.set(null, UNKNOWN_AP_COLOR);
  let i = 0;
  const assign = (bssid: string | null) => {
    if (bssid !== null && !colors.has(bssid)) colors.set(bssid, AP_PALETTE[i++ % AP_PALETTE.length]);
  };
  analysis.aps.forEach((a) => assign(a.bssid));
  analysis.segments.forEach((s) => assign(s.bssid));
  analysis.points.forEach((p) => assign(p.bssid));
  return colors;
}

/** AA:BB:CC:DD:EE:FF -> "…DD:EE:FF" - the last three octets identify an AP on a
 *  site (the first three are the vendor), so this is the compact form for labels. */
export function shortBssid(bssid: string | null | undefined): string {
  if (!bssid) return "unknown AP";
  const parts = bssid.split(":");
  return parts.length === 6 ? `…${parts.slice(3).join(":")}` : bssid;
}

export function formatDbm(rssi: number | null | undefined): string {
  return rssi === null || rssi === undefined ? "—" : `${Math.round(rssi)} dBm`;
}
