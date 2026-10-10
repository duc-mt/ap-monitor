import type { ApChange, ApSegment, ApUsage, SignalAnalysis, SignalPoint, StatusResponse } from "../src/types";

export const A = "aa:bb:cc:dd:ee:01";
export const B = "aa:bb:cc:dd:ee:02";

export function point(sec: number, bssid: string | null, rssi: number | null, extra: Partial<SignalPoint> = {}): SignalPoint {
  return {
    t: `2026-01-01T00:00:${String(sec).padStart(2, "0")}+00:00`,
    rssi, snr: 30, bssid, channel: 36, rate: 300, connected: true, ...extra,
  };
}

const usage = (bssid: string, share: number, secs: number, avg: number): ApUsage => ({
  bssid, ssid: "Net", band: "5GHz", channel: 36, visits: 1, total_seconds: secs, sample_count: 5,
  share_pct: share, rssi_min: avg - 5, rssi_avg: avg, rssi_max: avg + 5,
});

const segment = (bssid: string, start: number, end: number): ApSegment => ({
  bssid, ssid: "Net", band: "5GHz", channel: 36,
  start: `2026-01-01T00:00:${String(start).padStart(2, "0")}+00:00`,
  end: `2026-01-01T00:00:${String(end).padStart(2, "0")}+00:00`,
  duration_seconds: end - start, sample_count: end - start + 1, rssi_min: -75, rssi_avg: -62, rssi_max: -50,
});

const change: ApChange = {
  timestamp: "2026-01-01T00:00:05+00:00", ssid: "Net", from_bssid: A, to_bssid: B,
  same_ssid: true, via_disconnect: false, rssi_before: -74, rssi_after: -60,
};

/** A walk that starts on AP A, goes weak, then roams to AP B. */
export function twoApAnalysis(overrides: Partial<SignalAnalysis> = {}): SignalAnalysis {
  return {
    summary: {
      start: "2026-01-01T00:00:00+00:00", end: "2026-01-01T00:00:06+00:00", duration_seconds: 6, sample_count: 7,
      connected_sample_count: 7, rssi_min: -75, rssi_avg: -63.4, rssi_max: -50, snr_avg: 30, tx_rate_avg: 300,
      weak_threshold_dbm: -70, pct_samples_weak: 42.9, distinct_aps: 2, ap_change_count: 1, bssid_available: true,
    },
    aps: [usage(A, 71.4, 4, -63), usage(B, 28.6, 1, -59)],
    segments: [segment(A, 0, 4), segment(B, 5, 6)],
    ap_changes: [change],
    weak_stretches: [{
      start: "2026-01-01T00:00:02+00:00", end: "2026-01-01T00:00:04+00:00", duration_seconds: 2,
      sample_count: 3, min_rssi_dbm: -75, bssid: A,
    }],
    points: [
      point(0, A, -50), point(1, A, -55), point(2, A, -72), point(3, A, -75), point(4, A, -74),
      point(5, B, -60), point(6, B, -58),
    ],
    ...overrides,
  };
}

export const emptyAnalysis = (): SignalAnalysis => ({
  summary: {
    start: null, end: null, duration_seconds: 0, sample_count: 0, connected_sample_count: 0, rssi_min: null,
    rssi_avg: null, rssi_max: null, snr_avg: null, tx_rate_avg: null, weak_threshold_dbm: -70,
    pct_samples_weak: null, distinct_aps: 0, ap_change_count: 0, bssid_available: true,
  },
  aps: [], segments: [], ap_changes: [], weak_stretches: [], points: [],
});

export const baseStatus: StatusResponse = {
  online: true, quality: "good", latency_ms: 24.5, packet_loss: 0, jitter_ms: 1.2,
  monitoring_uptime_seconds: 3661, targets_reachable: 3, targets_total: 3,
  targets: [
    { target_id: 1, name: "Gateway", host: "192.168.1.1", reachable: true, latency_ms: 1.1, packet_loss: 0, last_checked: new Date().toISOString() },
  ],
  monitoring_running: true, wifi_interface: "wlan0", ssid: "HomeNet", bssid: "AA:BB:CC:DD:EE:FF",
  rssi_dbm: -52, channel: 36, band: "5GHz", phy_mode: "802.11ac",
  channel_width_mhz: 80, snr_db: 38, noise_floor_dbm: -90, tx_bitrate_mbps: 866, wifi_issue: null, platform: "linux",
  connectivity: { wifi_connected: true, gateway_reachable: true, internet_state: "available", overall: "internet_available" },
  wireless_quality_score: 91,
};
