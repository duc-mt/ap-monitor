import { TriangleAlert } from "lucide-react";
import type { WifiIssue } from "../types";

/** Explains why AP data is missing or incomplete. Shown prominently on purpose:
 *  a silent blank is indistinguishable from a broken app. */
export function IssueBanner({ issue }: { issue: WifiIssue }) {
  return (
    <div
      role="alert"
      className="flex gap-3 rounded-card border p-4"
      style={{ borderColor: "var(--color-degraded)", backgroundColor: "color-mix(in srgb, var(--color-degraded) 10%, transparent)" }}
    >
      <TriangleAlert size={18} className="shrink-0 mt-0.5" style={{ color: "var(--color-degraded)" }} />
      <div className="min-w-0">
        <p className="text-sm font-medium">{issue.title}</p>
        <p className="text-sm text-muted mt-1">{issue.detail}</p>
      </div>
    </div>
  );
}
