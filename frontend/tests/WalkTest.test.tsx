import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { WalkTest } from "../src/pages/WalkTest";
import { api } from "../src/services/api";
import type { WalkTest as Session } from "../src/types";
import { twoApAnalysis } from "./fixtures";

vi.mock("../src/services/api", () => ({
  api: {
    listWalkTests: vi.fn(),
    listWifiInterfaces: vi.fn(),
    listTargets: vi.fn(),
    startWalkTest: vi.fn(),
    stopWalkTest: vi.fn(),
    deleteWalkTest: vi.fn(),
    getWalkTestAnalysis: vi.fn(),
    walkTestExportUrl: (id: number) => `/api/walk-tests/${id}/export`,
  },
  ApiError: class ApiError extends Error {},
}));

const stopped: Session = {
  id: 3, name: "Lobby loop", site: "HQ", area: null, interface: "wlan0", target_ids: [], status: "stopped",
  started_at: "2026-01-01T00:00:00+00:00", ended_at: "2026-01-01T00:05:00+00:00", sample_count: 600,
};
const recording: Session = { ...stopped, id: 4, name: "Live one", status: "recording", ended_at: null, sample_count: 12 };

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/walk-test"]}>
      <Routes>
        <Route path="/walk-test" element={<WalkTest />} />
        <Route path="/walk-test/:id" element={<div>result page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("WalkTest page", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(api.listWifiInterfaces).mockResolvedValue([{ name: "wlan0", state: "connected", is_active: true }]);
    vi.mocked(api.listTargets).mockResolvedValue([]);
    vi.mocked(api.getWalkTestAnalysis).mockResolvedValue(twoApAnalysis());
  });

  it("explains what a walk test is for, so the purpose is clear before starting", async () => {
    vi.mocked(api.listWalkTests).mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/how a walk test works/i)).toBeInTheDocument();
    expect(screen.getByText(/you get the result/i)).toBeInTheDocument();
  });

  it("opens the results when a finished session is clicked", async () => {
    vi.mocked(api.listWalkTests).mockResolvedValue([stopped]);
    renderPage();
    fireEvent.click(await screen.findByRole("row", { name: /open results for lobby loop/i }));
    expect(await screen.findByText("result page")).toBeInTheDocument();
  });

  it("links each session to its CSV export without opening the result", async () => {
    vi.mocked(api.listWalkTests).mockResolvedValue([stopped]);
    renderPage();
    const link = await screen.findByRole("link", { name: /export lobby loop as csv/i });
    expect(link).toHaveAttribute("href", "/api/walk-tests/3/export");
    link.addEventListener("click", (e) => e.preventDefault());   // jsdom cannot navigate to a download
    fireEvent.click(link);
    expect(screen.queryByText("result page")).not.toBeInTheDocument();
  });

  it("shows a live signal view while recording and jumps to the result on stop", async () => {
    vi.mocked(api.listWalkTests).mockResolvedValue([recording]);
    vi.mocked(api.stopWalkTest).mockResolvedValue({ ...recording, status: "stopped" });
    renderPage();
    expect(await screen.findByTestId("live-walk")).toBeInTheDocument();
    expect(screen.getByTestId("live-walk")).toHaveTextContent(/now:\s*-58 dBm/i);
    fireEvent.click(screen.getByRole("button", { name: /stop/i }));
    await waitFor(() => expect(api.stopWalkTest).toHaveBeenCalledWith(4));
    expect(await screen.findByText("result page")).toBeInTheDocument();
  });

  it("deletes a session only after confirmation", async () => {
    vi.mocked(api.listWalkTests).mockResolvedValue([stopped]);
    vi.mocked(api.deleteWalkTest).mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderPage();
    const del = await screen.findByRole("button", { name: /delete lobby loop/i });
    fireEvent.click(del);
    expect(api.deleteWalkTest).not.toHaveBeenCalled();
    fireEvent.click(del);
    await waitFor(() => expect(api.deleteWalkTest).toHaveBeenCalledWith(3));
  });
});
