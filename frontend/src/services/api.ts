import type {
  AppSettings,
  AppSettingsUpdate,
  EnvironmentScanResult,
  Measurement,
  RangeName,
  RoamEvent,
  SignalAnalysis,
  StatisticsResponse,
  StatusResponse,
  Target,
  TargetInput,
  WalkTest,
  WalkTestCreateInput,
  WalkTestSample,
  WifiInterfaceInfo,
  WifiMetrics,
} from "../types";

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(0, "Could not reach the AP Monitor backend. Is the service running?");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ? JSON.stringify(body.detail) : detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  getStatus: () => request<StatusResponse>("/status"),

  listTargets: () => request<Target[]>("/targets"),
  createTarget: (data: TargetInput) =>
    request<Target>("/targets", { method: "POST", body: JSON.stringify(data) }),
  updateTarget: (id: number, data: Partial<TargetInput>) =>
    request<Target>(`/targets/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteTarget: (id: number) => request<void>(`/targets/${id}`, { method: "DELETE" }),

  listMeasurements: (params: { target_id?: number; start?: string; end?: string; limit?: number } = {}) =>
    request<Measurement[]>(`/measurements${toQuery(params)}`),

  getStatistics: (params: { range: RangeName; start?: string; end?: string; target_id?: number }) =>
    request<StatisticsResponse>(`/statistics${toQuery(params)}`),

  getSettings: () => request<AppSettings>("/settings"),
  updateSettings: (patch: AppSettingsUpdate) =>
    request<AppSettings>("/settings", { method: "PUT", body: JSON.stringify(patch) }),

  startMonitoring: () => request<{ running: boolean }>("/monitoring/start", { method: "POST" }),
  stopMonitoring: () => request<{ running: boolean }>("/monitoring/stop", { method: "POST" }),

  exportMeasurementsCsvUrl: (params: { target_id?: number; start?: string; end?: string } = {}) =>
    `${BASE}/export/measurements.csv${toQuery(params)}`,
  exportReportJsonUrl: (params: { range: RangeName; start?: string; end?: string; target_id?: number }) =>
    `${BASE}/export/report.json${toQuery(params)}`,

  listWifiInterfaces: () => request<WifiInterfaceInfo[]>("/wifi/interfaces"),
  listWifiSamples: (params: { interface?: string; start?: string; end?: string; limit?: number } = {}) =>
    request<WifiMetrics[]>(`/wifi/samples${toQuery(params)}`),
  getWifiAnalysis: (params: { minutes?: number; interface?: string; weak_threshold_dbm?: number } = {}) =>
    request<SignalAnalysis>(`/wifi/analysis${toQuery(params)}`),
  scanEnvironment: (interfaceName?: string) =>
    request<EnvironmentScanResult>(`/wifi/scan${toQuery({ interface: interfaceName })}`, { method: "POST" }),

  listRoamEvents: (params: { interface?: string; start?: string; end?: string; limit?: number } = {}) =>
    request<RoamEvent[]>(`/roam-events${toQuery(params)}`),
  getRoamEvent: (id: number) => request<RoamEvent>(`/roam-events/${id}`),

  listWalkTests: () => request<WalkTest[]>("/walk-tests"),
  getWalkTest: (id: number) => request<WalkTest>(`/walk-tests/${id}`),
  startWalkTest: (data: WalkTestCreateInput) =>
    request<WalkTest>("/walk-tests", { method: "POST", body: JSON.stringify(data) }),
  stopWalkTest: (id: number) => request<WalkTest>(`/walk-tests/${id}/stop`, { method: "POST" }),
  listWalkTestSamples: (id: number) => request<WalkTestSample[]>(`/walk-tests/${id}/samples`),
  getWalkTestAnalysis: (id: number, params: { weak_threshold_dbm?: number } = {}) =>
    request<SignalAnalysis>(`/walk-tests/${id}/analysis${toQuery(params)}`),
  walkTestExportUrl: (id: number) => `${BASE}/walk-tests/${id}/export`,
  deleteWalkTest: (id: number) => request<void>(`/walk-tests/${id}`, { method: "DELETE" }),
};

function toQuery(params: Record<string, unknown>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (entries.length === 0) return "";
  const search = new URLSearchParams(entries.map(([k, v]) => [k, String(v)]));
  return `?${search.toString()}`;
}
