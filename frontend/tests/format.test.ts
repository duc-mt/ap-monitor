import { describe, expect, it } from "vitest";
import { formatClock, formatDuration, formatLatency, formatPct, formatTimestamp } from "../src/services/format";

describe("formatLatency", () => {
  it("renders a dash for null/undefined", () => {
    expect(formatLatency(null)).toBe("—");
    expect(formatLatency(undefined)).toBe("—");
  });
  it("formats sub-10ms with two decimals", () => {
    expect(formatLatency(3.14159)).toBe("3.14 ms");
  });
  it("formats larger values with one decimal", () => {
    expect(formatLatency(123.456)).toBe("123.5 ms");
  });
});

describe("formatPct", () => {
  it("renders a dash for null", () => {
    expect(formatPct(null)).toBe("—");
  });
  it("formats one decimal place", () => {
    expect(formatPct(12.345)).toBe("12.3%");
  });
});

describe("formatDuration", () => {
  it("renders a dash for null", () => {
    expect(formatDuration(null)).toBe("—");
  });
  it("formats seconds only", () => {
    expect(formatDuration(42)).toBe("42s");
  });
  it("formats minutes and seconds", () => {
    expect(formatDuration(125)).toBe("2m 5s");
  });
  it("formats hours and minutes", () => {
    expect(formatDuration(3700)).toBe("1h 1m");
  });
  it("formats days and hours", () => {
    expect(formatDuration(90000)).toBe("1d 1h");
  });
  it("clamps negative values to zero", () => {
    expect(formatDuration(-5)).toBe("0s");
  });
});

// formatTimestamp/formatClock delegate to toLocaleString/toLocaleTimeString,
// whose exact output is locale- and timezone-dependent (nothing in this
// suite's setup pins either) - these tests check the behavior that's
// actually guaranteed (null handling, the unparseable-string fallback, and
// that a valid date really does get reformatted) rather than an exact
// locale-formatted string, which would be flaky across machines.
describe("formatTimestamp", () => {
  it("renders a dash for null/undefined", () => {
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp(undefined)).toBe("—");
  });
  it("returns the original string unchanged when it isn't a parseable date", () => {
    expect(formatTimestamp("not-a-date")).toBe("not-a-date");
  });
  it("formats a valid ISO timestamp into something locale-formatted, not the raw string", () => {
    const result = formatTimestamp("2026-03-15T14:30:00Z");
    expect(result).not.toBe("—");
    expect(result).not.toBe("2026-03-15T14:30:00Z");
    expect(result).toMatch(/\d/);
  });
});

describe("formatClock", () => {
  it("renders a dash for null/undefined", () => {
    expect(formatClock(null)).toBe("—");
    expect(formatClock(undefined)).toBe("—");
  });
  it("returns the original string unchanged when it isn't a parseable date", () => {
    expect(formatClock("not-a-date")).toBe("not-a-date");
  });
  it("formats a valid ISO timestamp into a time, not the raw string", () => {
    const result = formatClock("2026-03-15T14:30:00Z");
    expect(result).not.toBe("—");
    expect(result).not.toBe("2026-03-15T14:30:00Z");
    expect(result).toMatch(/\d/);
  });
});
