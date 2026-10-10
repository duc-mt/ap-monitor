import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RoamClassificationBadge, RoamConfidenceLabel } from "../src/components/RoamBadges";
import type { RoamClassification, RoamConfidence } from "../src/types";

describe("RoamClassificationBadge", () => {
  it.each([
    ["excellent", "Excellent"],
    ["good", "Good"],
    ["fair", "Fair"],
    ["poor", "Poor"],
    ["failed", "Failed"],
  ] as [RoamClassification, string][])("renders the %s label as %s", (classification, label) => {
    render(<RoamClassificationBadge classification={classification} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("renders a dash when classification is null (not yet measured)", () => {
    render(<RoamClassificationBadge classification={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("RoamConfidenceLabel", () => {
  it.each([
    ["high", "High confidence"],
    ["medium", "Medium confidence"],
    ["low", "Low confidence"],
    ["unknown", "Unknown confidence"],
  ] as [RoamConfidence, string][])("renders the %s threshold as %s", (confidence, label) => {
    render(<RoamConfidenceLabel confidence={confidence} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("renders a dash when confidence is null", () => {
    render(<RoamConfidenceLabel confidence={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
