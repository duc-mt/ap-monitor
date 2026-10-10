import type { RoamClassification, RoamConfidence } from "../types";

const CLASSIFICATION_COLOR: Record<RoamClassification, string> = {
  excellent: "var(--color-healthy)",
  good: "var(--color-healthy)",
  fair: "var(--color-degraded)",
  poor: "var(--color-offline)",
  failed: "var(--color-offline)",
};

const CLASSIFICATION_LABEL: Record<RoamClassification, string> = {
  excellent: "Excellent",
  good: "Good",
  fair: "Fair",
  poor: "Poor",
  failed: "Failed",
};

export function RoamClassificationBadge({ classification }: { classification: RoamClassification | null }) {
  if (classification === null) {
    return <span className="text-xs text-muted">—</span>;
  }
  const color = CLASSIFICATION_COLOR[classification];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium"
      style={{ borderColor: color, color }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
      {CLASSIFICATION_LABEL[classification]}
    </span>
  );
}

const CONFIDENCE_LABEL: Record<RoamConfidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
  unknown: "Unknown confidence",
};

export function RoamConfidenceLabel({ confidence }: { confidence: RoamConfidence | null }) {
  if (confidence === null) return <span className="text-xs text-muted">—</span>;
  return <span className="text-xs text-muted">{CONFIDENCE_LABEL[confidence]}</span>;
}
