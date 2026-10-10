import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { SignalChart } from "../src/components/SignalChart";
import { buildApColors } from "../src/services/signal";
import { A, B, point, twoApAnalysis } from "./fixtures";

afterEach(() => vi.restoreAllMocks());

describe("SignalChart", () => {
  const analysis = twoApAnalysis();
  const colors = buildApColors(analysis);

  it("draws one coloured line per access point, continuous across the change", () => {
    render(<SignalChart points={analysis.points} colors={colors} weakThreshold={-70} apChanges={analysis.ap_changes} />);
    const lines = screen.getAllByTestId("signal-line");
    expect(lines.map((l) => l.getAttribute("data-bssid"))).toEqual([A, B]);
    expect(lines[0].getAttribute("stroke")).toBe(colors.get(A));
    expect(lines[1].getAttribute("stroke")).toBe(colors.get(B));
    // The second line starts at the last point of the first so there is no visual gap at the roam.
    const lastOfFirst = lines[0].getAttribute("points")!.split(" ").pop();
    expect(lines[1].getAttribute("points")!.split(" ")[0]).toBe(lastOfFirst);
  });

  it("marks the AP change and the weak threshold", () => {
    render(<SignalChart points={analysis.points} colors={colors} weakThreshold={-75} apChanges={analysis.ap_changes} />);
    expect(screen.getByTestId("ap-change-marker")).toHaveTextContent("→ …dd:ee:02");
    expect(screen.getByTestId("weak-threshold")).toBeInTheDocument();
    expect(screen.getByText(/weak < -75 dBm/)).toBeInTheDocument();
  });

  it("breaks the line and shades the gap where the device was disconnected", () => {
    const pts = [point(0, A, -50), point(1, A, -52), point(2, null, null, { connected: false }), point(3, A, -51), point(4, A, -50)];
    render(<SignalChart points={pts} colors={colors} weakThreshold={-70} />);
    expect(screen.getAllByTestId("signal-line")).toHaveLength(2);   // before and after the drop, not joined
    expect(screen.getAllByTestId("disconnected-band")).toHaveLength(1);
  });

  it("shows a message instead of an empty axis when there is no signal data", () => {
    render(<SignalChart points={[point(0, null, null, { connected: false })]} colors={colors} weakThreshold={-70} />);
    expect(screen.getByText(/no signal readings in this period/i)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows exact readings for the point nearest the cursor", () => {
    render(<SignalChart points={analysis.points} colors={colors} weakThreshold={-70} apChanges={analysis.ap_changes} />);
    const svg = screen.getByRole("img");
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 900, height: 260, right: 900, bottom: 260, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.mouseMove(svg, { clientX: 880 });   // far right = last sample, on AP B at -58
    const tip = screen.getByTestId("signal-tooltip");
    expect(tip).toHaveTextContent("-58 dBm");
    expect(tip).toHaveTextContent(B);
    fireEvent.mouseLeave(svg);
    expect(screen.queryByTestId("signal-tooltip")).not.toBeInTheDocument();
  });

  it("copes with a single reading", () => {
    render(<SignalChart points={[point(0, A, -55)]} colors={colors} weakThreshold={-70} />);
    expect(screen.getAllByTestId("signal-line")).toHaveLength(1);
  });
});
