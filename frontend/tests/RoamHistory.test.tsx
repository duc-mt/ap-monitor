import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { RoamHistory } from "../src/pages/RoamHistory";
import { explainNoRoams } from "../src/services/roamExplain";
import { api } from "../src/services/api";
import { A, baseStatus, emptyAnalysis, twoApAnalysis } from "./fixtures";

vi.mock("../src/services/api", () => ({
  api: { listRoamEvents: vi.fn(), getStatus: vi.fn(), getWifiAnalysis: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

const oneAp = () =>
  twoApAnalysis({
    aps: [twoApAnalysis().aps[0]], segments: [twoApAnalysis().segments[0]], ap_changes: [], weak_stretches: [],
    summary: { ...twoApAnalysis().summary, distinct_aps: 1, ap_change_count: 0 },
  });

describe("explainNoRoams", () => {
  it("blames a hidden-BSSID system first, since nothing else can be concluded", () => {
    const e = explainNoRoams(
      { ...baseStatus, wifi_issue: { code: "location_permission", title: "WiFi details are hidden by the OS", detail: "x" } },
      oneAp(),
    );
    expect(e.title).toMatch(/cannot be detected/i);
    expect(e.body).toMatch(/hidden by the os/i);
  });

  it("reports a disconnected radio", () => {
    const e = explainNoRoams({ ...baseStatus, connectivity: { ...baseStatus.connectivity, wifi_connected: false } }, oneAp());
    expect(e.title).toMatch(/not connected/i);
  });

  it("reports no data yet", () => {
    expect(explainNoRoams(baseStatus, emptyAnalysis()).title).toMatch(/no wifi readings/i);
    expect(explainNoRoams(baseStatus, null).title).toMatch(/no wifi readings/i);
  });

  it("explains that staying on one AP is normal and names it", () => {
    const e = explainNoRoams(baseStatus, oneAp());
    expect(e.title).toMatch(/stayed on one access point/i);
    expect(e.body).toContain("…dd:ee:01");
    expect(e.body).toMatch(/walk test/i);
  });

  it("distinguishes AP switches that are not roams (different network / after a disconnect)", () => {
    const a = twoApAnalysis({ ap_changes: [{ ...twoApAnalysis().ap_changes[0], same_ssid: false }] });
    expect(explainNoRoams(baseStatus, a).title).toMatch(/none count as roams/i);
    const b = twoApAnalysis({ ap_changes: [{ ...twoApAnalysis().ap_changes[0], via_disconnect: true }] });
    expect(explainNoRoams(baseStatus, b).title).toMatch(/none count as roams/i);
  });

  it("mentions a pending confirmation when a real roam-like change exists but no event does", () => {
    expect(explainNoRoams(baseStatus, twoApAnalysis()).title).toMatch(/waiting for confirmation/i);
  });

  it("says addresses are unavailable when the history has no BSSIDs", () => {
    const a = twoApAnalysis({ summary: { ...twoApAnalysis().summary, bssid_available: false } });
    expect(explainNoRoams(baseStatus, a).title).toMatch(/addresses are not available/i);
  });
});

describe("RoamHistory page", () => {
  beforeEach(() => {
    vi.mocked(api.getStatus).mockResolvedValue(baseStatus);
    vi.mocked(api.listRoamEvents).mockResolvedValue([]);
    vi.mocked(api.getWifiAnalysis).mockResolvedValue(oneAp());
  });

  it("explains an empty roam list and still shows which AP was used", async () => {
    render(<MemoryRouter><RoamHistory /></MemoryRouter>);
    const box = await screen.findByTestId("no-roams");
    expect(box).toHaveTextContent(/stayed on one access point/i);
    expect(await screen.findByRole("region", { name: /access point history/i })).toHaveTextContent(A);
  });

  it("surfaces the OS-hidden-BSSID banner on this page too", async () => {
    vi.mocked(api.getStatus).mockResolvedValue({
      ...baseStatus, bssid: null,
      wifi_issue: { code: "bssid_unavailable", title: "Connected AP address (BSSID) not reported", detail: "Turn on Location." },
    });
    render(<MemoryRouter><RoamHistory /></MemoryRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not reported/i);
    expect(await screen.findByTestId("no-roams")).toHaveTextContent(/cannot be detected/i);
  });
});
