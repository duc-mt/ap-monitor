export type Protocol = "icmp" | "tcp";
export type Quality = "excellent" | "good" | "fair" | "poor" | "offline" | "unknown";
export type Theme = "light" | "dark" | "system";
export type RangeName = "1h" | "24h" | "7d" | "30d" | "custom";

export type InterfaceState =
  | "connected" | "disconnected" | "connecting" | "scanning" | "disabled" | "unavailable" | "unknown";

export interface WifiInterfaceInfo {
  name: string;
  state: InterfaceState;
  is_active: boolean;
}

export interface WifiMetrics {
  timestamp: string;
  interface: string;
  interface_state: InterfaceState;
  ssid: string | null;
  bssid: string | null;
  frequency_mhz: number | null;
  channel: number | null;
  band: string | null;
  rssi_dbm: number | null;
  signal_pct: number | null;
  noise_floor_dbm: number | null;
  snr_db: number | null;
  phy_mode: string | null;
  channel_width_mhz: number | null;
  mcs_index: number | null;
  tx_bitrate_mbps: number | null;
  rx_bitrate_mbps: number | null;
  phy_rate_mbps: number | null;
  ipv4_addresses: string[] | null;
  ipv6_addresses: string[] | null;
  gateway: string | null;
  dns_servers: string[] | null;
}

export interface NeighborNetwork {
  ssid: string | null;
  bssid: string | null;
  phy_mode: string | null;
  channel: number | null;
  channel_width_mhz: number | null;
  band: string | null;
  security: string | null;
  rssi_dbm: number | null;
  is_co_channel: boolean;
}

export interface EnvironmentScanResult {
  timestamp: string;
  interface: string;
  connected_channel: number | null;
  connected_band: string | null;
  neighbors: NeighborNetwork[];
}

export type RoamClassification = "excellent" | "good" | "fair" | "poor" | "failed";
export type RoamConfidence = "high" | "medium" | "low" | "unknown";

export interface RoamEvent {
  id: number;
  timestamp: string;
  interface: string;
  ssid: string | null;
  previous_bssid: string | null;
  new_bssid: string | null;
  previous_frequency_mhz: number | null;
  new_frequency_mhz: number | null;
  previous_channel: number | null;
  new_channel: number | null;
  previous_band: string | null;
  new_band: string | null;
  previous_phy_mode: string | null;
  new_phy_mode: string | null;
  previous_channel_width_mhz: number | null;
  new_channel_width_mhz: number | null;
  previous_mcs_index: number | null;
  new_mcs_index: number | null;
  previous_rssi_dbm: number | null;
  new_rssi_dbm: number | null;
  ip_changed: boolean;
  previous_ipv4: string[] | null;
  new_ipv4: string[] | null;
  gateway_interruption_ms: number | null;
  internet_interruption_ms: number | null;
  packet_loss_during_pct: number | null;
  peak_latency_ms: number | null;
  success: boolean | null;
  classification: RoamClassification | null;
  confidence: RoamConfidence | null;
}

export type WalkTestStatus = "recording" | "stopped";

export interface WalkTest {
  id: number;
  name: string;
  site: string | null;
  area: string | null;
  interface: string;
  target_ids: number[];
  status: WalkTestStatus;
  started_at: string;
  ended_at: string | null;
  sample_count: number;
}

export type WalkTestCreateInput = {
  name: string;
  site?: string | null;
  area?: string | null;
  interface: string;
  target_ids: number[];
};

export interface WalkTestSample {
  id: number;
  walk_test_id: number;
  timestamp: string;
  interface_state: InterfaceState | null;
  ssid: string | null;
  bssid: string | null;
  frequency_mhz: number | null;
  channel: number | null;
  band: string | null;
  rssi_dbm: number | null;
  signal_pct: number | null;
  noise_floor_dbm: number | null;
  snr_db: number | null;
  phy_mode: string | null;
  channel_width_mhz: number | null;
  mcs_index: number | null;
  tx_bitrate_mbps: number | null;
  rx_bitrate_mbps: number | null;
  phy_rate_mbps: number | null;
  latency_ms: number | null;
  packet_loss_pct: number | null;
  reachable: boolean | null;
}

export interface Target {
  id: number;
  name: string;
  host: string;
  protocol: Protocol;
  port: number | null;
  is_gateway: boolean;
  enabled: boolean;
  interval_seconds: number;
  created_at: string;
}

export type TargetInput = Omit<Target, "id" | "created_at">;

export interface Measurement {
  id: number;
  target_id: number;
  target_name?: string | null;
  timestamp: string;
  latency_ms: number | null;
  packet_loss: number;
  jitter_ms: number | null;
  success: boolean;
  error: string | null;
}

export interface TargetStatus {
  target_id: number;
  name: string;
  host: string;
  reachable: boolean;
  latency_ms: number | null;
  packet_loss: number | null;
  last_checked: string | null;
}

export type ConnectivityState =
  | "unknown" | "wifi_disconnected" | "wifi_connected"
  | "gateway_unavailable" | "gateway_available"
  | "internet_unavailable" | "degraded" | "internet_available";

export interface ConnectivityStatus {
  wifi_connected: boolean | null;
  gateway_reachable: boolean | null;
  internet_state: "unavailable" | "degraded" | "available" | null;
  overall: ConnectivityState;
}

export interface WifiIssue {
  code: string;
  title: string;
  detail: string;
}

export interface StatusResponse {
  online: boolean;
  quality: Quality;
  latency_ms: number | null;
  packet_loss: number | null;
  jitter_ms: number | null;
  monitoring_uptime_seconds: number;
  targets_reachable: number;
  targets_total: number;
  targets: TargetStatus[];
  monitoring_running: boolean;
  wifi_interface: string | null;
  ssid: string | null;
  bssid: string | null;
  rssi_dbm: number | null;
  channel: number | null;
  band: string | null;
  phy_mode: string | null;
  channel_width_mhz: number | null;
  snr_db: number | null;
  noise_floor_dbm: number | null;
  tx_bitrate_mbps: number | null;
  wifi_issue: WifiIssue | null;
  platform: string;
  connectivity: ConnectivityStatus;
  wireless_quality_score: number | null;
}

export interface StatisticsResponse {
  range_start: string;
  range_end: string;
  target_id: number | null;
  sample_count: number;
  avg_latency_ms: number | null;
  min_latency_ms: number | null;
  max_latency_ms: number | null;
  median_latency_ms: number | null;
  p95_latency_ms: number | null;
  packet_loss_pct: number | null;
  avg_jitter_ms: number | null;
  monitoring_duration_seconds: number;
}

export interface ClassificationThresholds {
  excellent_latency_ms: number;
  excellent_packet_loss_pct: number;
  good_latency_ms: number;
  good_packet_loss_pct: number;
  fair_latency_ms: number;
  fair_packet_loss_pct: number;
}

export interface NotificationPreferences {
  on_offline: boolean;
  on_online: boolean;
  on_degraded: boolean;
  on_latency_threshold: boolean;
  on_packet_loss_threshold: boolean;
  on_poor_roam: boolean;
  cooldown_seconds: number;
}

export interface AppSettings {
  ping_timeout_seconds: number;
  pings_per_check: number;
  default_target_interval_seconds: number;
  latency_warning_threshold_ms: number;
  packet_loss_warning_threshold_pct: number;
  internet_quorum: "any" | "all";
  wifi_poll_interval_seconds: number;
  roam_watch_timeout_seconds: number;
  walk_test_sample_interval_ms: number;
  wireless_quality_window_minutes: number;
  notifications: NotificationPreferences;
  classification: ClassificationThresholds;
  data_retention_days: number;
  start_on_boot: boolean;
  theme: Theme;
  language: string;
}

export type AppSettingsUpdate = Partial<
  Omit<AppSettings, "notifications" | "classification"> & {
    notifications: Partial<NotificationPreferences>;
    classification: Partial<ClassificationThresholds>;
  }
>;

// --- Signal / AP analysis (GET /api/wifi/analysis, /api/walk-tests/{id}/analysis) ---

export interface SignalPoint {
  t: string;
  rssi: number | null;
  snr: number | null;
  bssid: string | null;
  channel: number | null;
  rate: number | null;
  connected: boolean;
}

export interface ApSegment {
  bssid: string | null;
  ssid: string | null;
  band: string | null;
  channel: number | null;
  start: string;
  end: string;
  duration_seconds: number;
  sample_count: number;
  rssi_min: number | null;
  rssi_avg: number | null;
  rssi_max: number | null;
}

export interface ApUsage {
  bssid: string | null;
  ssid: string | null;
  band: string | null;
  channel: number | null;
  visits: number;
  total_seconds: number;
  sample_count: number;
  share_pct: number;
  rssi_min: number | null;
  rssi_avg: number | null;
  rssi_max: number | null;
}

export interface ApChange {
  timestamp: string;
  ssid: string | null;
  from_bssid: string;
  to_bssid: string;
  same_ssid: boolean;
  via_disconnect: boolean;
  rssi_before: number | null;
  rssi_after: number | null;
}

export interface WeakStretch {
  start: string;
  end: string;
  duration_seconds: number;
  sample_count: number;
  min_rssi_dbm: number;
  bssid: string | null;
}

export interface SignalSummary {
  start: string | null;
  end: string | null;
  duration_seconds: number;
  sample_count: number;
  connected_sample_count: number;
  rssi_min: number | null;
  rssi_avg: number | null;
  rssi_max: number | null;
  snr_avg: number | null;
  tx_rate_avg: number | null;
  weak_threshold_dbm: number;
  pct_samples_weak: number | null;
  distinct_aps: number;
  ap_change_count: number;
  bssid_available: boolean;
}

export interface SignalAnalysis {
  summary: SignalSummary;
  aps: ApUsage[];
  segments: ApSegment[];
  ap_changes: ApChange[];
  weak_stretches: WeakStretch[];
  points: SignalPoint[];
}
