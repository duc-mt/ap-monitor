import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConnectivityStateBadge } from "../src/components/ConnectivityStateBadge";
import type { ConnectivityState } from "../src/types";

describe("ConnectivityStateBadge", () => {
  it.each([
    ["unknown", "Unknown"],
    ["wifi_disconnected", "WiFi disconnected"],
    ["wifi_connected", "WiFi connected"],
    ["gateway_unavailable", "Gateway unavailable"],
    ["gateway_available", "Gateway available"],
    ["internet_unavailable", "Internet unavailable"],
    ["degraded", "Degraded"],
    ["internet_available", "Internet available"],
  ] as [ConnectivityState, string][])("renders the %s label as %s", (state, label) => {
    render(<ConnectivityStateBadge state={state} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
