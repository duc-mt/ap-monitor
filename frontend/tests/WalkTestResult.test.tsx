import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { WalkTestResult } from "../src/pages/WalkTestResult";
import { api } from "../src/services/api";
import type { WalkTest } from "../src/types";
import { A, emptyAnalysis, twoApAnalysis } from "./fixtures";

vi.mock("../src/services/api", () => ({
  api: {
    getWalkTest: vi.fn(),
    getWalkTestAnalysis: vi.fn(),
    deleteWalkTest: vi.fn(),
    walkTestExportUrl: (id: number) => `/api/walk-tests/${id}/export`,
  },
  ApiError: class ApiError extends Error {},
}));

const session: WalkTest = {
  id: 5, name: "Floor 2 east", site: "HQ", area: "Wing B", interface: "wlan0", target_ids: [],
  status: "stopped", started_at: "2026-01-01T00:00:00+00:00", ended_at: "2026-01-01T00:00:06+00:00", sample_count: 7,
};

function renderAt(path = "/walk-test/5") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/walk-test/:id" element={<WalkTestResult />} />
        <Route path="/walk-test" element={<div>sessions list</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("WalkTestResult", () => {
  beforeEach(() => {
    vi.mocked(api.getWalkTest).mockResolvedValue(session);
    vi.mocked(api.getWalkTestAnalysis).mockResolvedValue(twoApAnalysis());
    vi.restoreAllMocks();
    vi.mocked(api.getWalkTest).mockResolvedValue(session);
    vi.mocked(api.getWalkTestAnalysis).mockResolvedValue(twoApAnalysis());
  });

  it("answers the walk-test question: signal, weak spots, and which AP covered what", async () => {
    renderAt();
    expect(await screen.findByRole("heading", { name: "Floor 2 east" })).toBeInTheDocument();
    expect(await screen.findByText("Average signal")).toBeInTheDocument();
    expect(screen.getByText("-75")).toBeInTheDocument();                       // weakest point
    expect(screen.getByText("43% of samples")).toBeInTheDocument();           // share of time weak
    expect(screen.getAllByTestId("signal-line").length).toBe(2);
    expect(screen.getByTestId("route-strip").children).toHaveLength(2);

    const weak = screen.getByRole("region", { name: /weak signal spots/i });
    expect(within(weak).getByText("-75 dBm")).toBeInTheDocument();

    const used = screen.getByRole("region", { name: /access points used/i });
    expect(within(used).getByText(A)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /access point changes/i })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /route timeline/i })).toBeInTheDocument();
  });

  it("offers a CSV export and lets the weak threshold be changed", async () => {
    renderAt();
    const link = await screen.findByRole("link", { name: /export csv/i });
    expect(link).toHaveAttribute("href", "/api/walk-tests/5/export");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "-75" } });
    await waitFor(() => expect(api.getWalkTestAnalysis).toHaveBeenLastCalledWith(5, { weak_threshold_dbm: -75 }));
  });

  it("says so when no weak stretch was found", async () => {
    vi.mocked(api.getWalkTestAnalysis).mockResolvedValue(twoApAnalysis({ weak_stretches: [] }));
    renderAt();
    expect(await screen.findByText(/coverage along this route looks solid/i)).toBeInTheDocument();
  });

  it("explains missing AP addresses instead of showing an empty breakdown", async () => {
    const base = twoApAnalysis();
    vi.mocked(api.getWalkTestAnalysis).mockResolvedValue({
      ...base, aps: [], ap_changes: [],
      segments: [{ ...base.segments[0], bssid: null }],
      summary: { ...base.summary, bssid_available: false, distinct_aps: 0, ap_change_count: 0 },
    });
    renderAt();
    expect(await screen.findByRole("alert")).toHaveTextContent(/access point addresses were not available/i);
    expect(screen.queryByRole("region", { name: /access points used/i })).not.toBeInTheDocument();
  });

  it("handles a session that recorded nothing", async () => {
    vi.mocked(api.getWalkTestAnalysis).mockResolvedValue(emptyAnalysis());
    renderAt();
    expect(await screen.findByText(/no samples were recorded/i)).toBeInTheDocument();
  });

  it("deletes the session after confirmation and returns to the list", async () => {
    vi.mocked(api.deleteWalkTest).mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderAt();
    fireEvent.click(await screen.findByRole("button", { name: /delete/i }));
    await waitFor(() => expect(api.deleteWalkTest).toHaveBeenCalledWith(5));
    expect(await screen.findByText("sessions list")).toBeInTheDocument();
  });

  it("does not delete when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderAt();
    fireEvent.click(await screen.findByRole("button", { name: /delete/i }));
    expect(api.deleteWalkTest).not.toHaveBeenCalled();
  });

  it("rejects a non-numeric id", () => {
    renderAt("/walk-test/abc");
    expect(screen.getByText(/not a valid walk test/i)).toBeInTheDocument();
  });
});
