import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Dashboard } from "../src/pages/Dashboard";
import { ThemeProvider } from "../src/hooks/useTheme";
import { api } from "../src/services/api";
import type { Target } from "../src/types";
import { A, B, baseStatus, emptyAnalysis, twoApAnalysis } from "./fixtures";

vi.mock("../src/services/api", () => ({
  api: {
    getStatus: vi.fn(),
    listTargets: vi.fn(),
    listMeasurements: vi.fn(),
    getWifiAnalysis: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

const mockTargets: Target[] = [
  { id: 1, name: "Gateway", host: "192.168.1.1", protocol: "icmp", port: null, is_gateway: true, enabled: true, interval_seconds: 5, created_at: "2026-01-01T00:00:00Z" },
];

function renderDashboard() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("Dashboard (access-point first)", () => {
  beforeEach(() => {
    vi.mocked(api.getStatus).mockResolvedValue(baseStatus);
    vi.mocked(api.listTargets).mockResolvedValue(mockTargets);
    vi.mocked(api.listMeasurements).mockResolvedValue([]);
    vi.mocked(api.getWifiAnalysis).mockResolvedValue(twoApAnalysis());
  });

  it("shows a loading state before data arrives", () => {
    renderDashboard();
    expect(screen.getByText(/connecting/i)).toBeInTheDocument();
  });

  it("leads with the connected access point: SSID, BSSID, signal, band and link details", async () => {
    renderDashboard();
    const card = await screen.findByTestId("ap-card");
    expect(within(card).getByText("HomeNet")).toBeInTheDocument();
    expect(within(card).getByTestId("ap-bssid")).toHaveTextContent("AA:BB:CC:DD:EE:FF");
    expect(within(card).getByText("-52 dBm")).toBeInTheDocument();
    expect(within(card).getByText("Good")).toBeInTheDocument();
    expect(card.textContent).toMatch(/5GHz · ch 36 · 80 MHz/);
    expect(within(card).getByText("866 Mbps")).toBeInTheDocument();
    expect(within(card).getByText("38 dB")).toBeInTheDocument();
    expect(within(card).getByText("91 / 100")).toBeInTheDocument();
  });

  it("draws the signal timeline coloured per access point with a change marker and a summary", async () => {
    renderDashboard();
    await waitFor(() => expect(screen.getAllByTestId("signal-line").length).toBeGreaterThan(0));
    const bssids = screen.getAllByTestId("signal-line").map((el) => el.getAttribute("data-bssid"));
    expect(new Set(bssids)).toEqual(new Set([A, B]));
    expect(screen.getAllByTestId("ap-change-marker")).toHaveLength(1);
    expect(screen.getByTestId("window-summary")).toHaveTextContent(/2 access points, 1 change/);
    expect(screen.getByRole("heading", { name: /access points in this period/i })).toBeInTheDocument();
  });

  it("re-queries the analysis when the time window changes", async () => {
    renderDashboard();
    await screen.findByTestId("ap-card");
    fireEvent.click(screen.getByRole("button", { name: "1 hour" }));
    await waitFor(() => expect(api.getWifiAnalysis).toHaveBeenCalledWith(expect.objectContaining({ minutes: 60 })));
  });

  it("keeps internet/gateway info secondary: summary visible, details behind a toggle", async () => {
    renderDashboard();
    await screen.findByText(/upstream reachability/i);
    expect(screen.getByText(/3 of 3 targets reachable/i)).toBeInTheDocument();
    expect(screen.queryByText(/target status/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /show latency chart and targets/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /hide latency chart and targets/i })).toBeInTheDocument());
    expect(api.listMeasurements).toHaveBeenCalled();
  });

  it("explains hidden SSID/BSSID instead of showing a silent blank", async () => {
    vi.mocked(api.getStatus).mockResolvedValue({
      ...baseStatus, ssid: null, bssid: null,
      wifi_issue: { code: "location_permission", title: "WiFi details are hidden by the OS", detail: "Turn on Location Services." },
    });
    renderDashboard();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("WiFi details are hidden by the OS");
    expect(alert).toHaveTextContent("Turn on Location Services.");
    const card = screen.getByTestId("ap-card");
    expect(within(card).getByText(/connected \(network name hidden\)/i)).toBeInTheDocument();
    expect(within(card).getByTestId("ap-bssid")).toHaveTextContent("BSSID not reported");
  });

  it("says the AP address is unavailable when the history has no BSSIDs", async () => {
    vi.mocked(api.getWifiAnalysis).mockResolvedValue(
      twoApAnalysis({ aps: [], ap_changes: [], summary: { ...twoApAnalysis().summary, bssid_available: false, distinct_aps: 0, ap_change_count: 0 } }),
    );
    renderDashboard();
    await waitFor(() => expect(screen.getByTestId("window-summary")).toHaveTextContent(/access point address not available/i));
  });

  it("shows the disconnected state without inventing an AP", async () => {
    vi.mocked(api.getStatus).mockResolvedValue({
      ...baseStatus, ssid: null, bssid: null, rssi_dbm: null, channel: null, band: null, snr_db: null, tx_bitrate_mbps: null,
      connectivity: { ...baseStatus.connectivity, wifi_connected: false, overall: "wifi_disconnected" },
    });
    vi.mocked(api.getWifiAnalysis).mockResolvedValue(emptyAnalysis());
    renderDashboard();
    await waitFor(() => expect(screen.getByText("Not connected to WiFi")).toBeInTheDocument());
    expect(screen.getAllByText(/wifi disconnected/i).length).toBeGreaterThan(0);
    expect(screen.queryByText("HomeNet")).not.toBeInTheDocument();
  });

  it("notes that Windows signal strength is derived from a percentage", async () => {
    vi.mocked(api.getStatus).mockResolvedValue({ ...baseStatus, platform: "win32", snr_db: null, noise_floor_dbm: null });
    renderDashboard();
    expect(await screen.findByText(/derived from it/i)).toBeInTheDocument();
  });

  it("shows an error state when the backend is unreachable", async () => {
    vi.mocked(api.getStatus).mockRejectedValue(new Error("Could not reach the AP Monitor backend."));
    renderDashboard();
    await waitFor(() => expect(screen.getByText(/could not reach/i)).toBeInTheDocument());
  });
});
