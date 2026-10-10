import { describe, expect, it } from "vitest";
import { AP_PALETTE, UNKNOWN_AP_COLOR, buildApColors, classifySignal, formatDbm, shortBssid, signalBarPct } from "../src/services/signal";
import { A, B, twoApAnalysis } from "./fixtures";

describe("signal helpers", () => {
  it.each([
    [-45, "excellent"], [-50, "excellent"], [-55, "good"], [-65, "fair"], [-75, "weak"], [-85, "poor"], [null, "none"],
  ])("classifies %s dBm as %s", (rssi, expected) => {
    expect(classifySignal(rssi as number | null)).toBe(expected);
  });

  it("maps RSSI onto a clamped 0-100 bar", () => {
    expect(signalBarPct(-90)).toBe(0);
    expect(signalBarPct(-40)).toBe(100);
    expect(signalBarPct(-65)).toBe(50);
    expect(signalBarPct(-120)).toBe(0);
    expect(signalBarPct(-10)).toBe(100);
    expect(signalBarPct(null)).toBe(0);
  });

  it("gives each BSSID a stable colour in airtime order, and unknown APs a neutral one", () => {
    const colors = buildApColors(twoApAnalysis());
    expect(colors.get(A)).toBe(AP_PALETTE[0]);
    expect(colors.get(B)).toBe(AP_PALETTE[1]);
    expect(colors.get(null)).toBe(UNKNOWN_AP_COLOR);
    expect(buildApColors(twoApAnalysis()).get(A)).toBe(colors.get(A));
  });

  it("shortens a BSSID to its device-specific half", () => {
    expect(shortBssid("aa:bb:cc:dd:ee:01")).toBe("…dd:ee:01");
    expect(shortBssid(null)).toBe("unknown AP");
    expect(shortBssid("weird")).toBe("weird");
  });

  it("formats dBm", () => {
    expect(formatDbm(-52.4)).toBe("-52 dBm");
    expect(formatDbm(null)).toBe("—");
  });
});
