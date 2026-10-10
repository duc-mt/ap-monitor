import type { SignalAnalysis, StatusResponse } from "../types";
import { shortBssid } from "./signal";

export interface Explanation {
  title: string;
  body: string;
}

/**
 * Why the Roaming page has no events, in order of how fixable the cause is.
 * "No roams recorded yet" with no reason is indistinguishable from a broken
 * monitor, so this inspects the live status and the recent AP history and
 * says which situation applies.
 */
export function explainNoRoams(
  status: StatusResponse | null,
  analysis: SignalAnalysis | null,
  windowLabel = "24 hours",
): Explanation {
  if (status?.wifi_issue) {
    return {
      title: "Roams cannot be detected right now",
      body: `Roaming is detected from changes in the access point's address, and this system is not providing it (${status.wifi_issue.title.toLowerCase()}). Fix the problem shown above, then walk around again.`,
    };
  }
  if (status?.connectivity.wifi_connected === false) {
    return {
      title: "WiFi is not connected",
      body: "This device is not connected to a WiFi network right now, so there is no access point to track.",
    };
  }
  if (!analysis || analysis.summary.sample_count === 0) {
    return {
      title: "No WiFi readings yet",
      body: "Readings are collected every few seconds. Roams will appear here as soon as the device moves to another access point.",
    };
  }
  if (!analysis.summary.bssid_available) {
    return {
      title: "Access point addresses are not available",
      body: "Signal readings exist but none include the access point address, so a change of access point cannot be seen.",
    };
  }
  if (analysis.ap_changes.length > 0) {
    const roamLike = analysis.ap_changes.filter((c) => c.same_ssid && !c.via_disconnect);
    if (roamLike.length === 0) {
      return {
        title: "Access point changes were seen, but none count as roams",
        body: "The device switched to a different network or reconnected after a drop. Roams are only logged when the device moves between access points of the same network without disconnecting.",
      };
    }
    return {
      title: "A change was seen and is waiting for confirmation",
      body: "A roam is logged once the new access point holds for two consecutive readings. If the device keeps flipping between access points, it may not stay long enough to be confirmed.",
    };
  }
  if (analysis.summary.distinct_aps <= 1) {
    const only = analysis.aps.find((a) => a.bssid)?.bssid ?? null;
    return {
      title: "The device has stayed on one access point",
      body: `For the last ${windowLabel} it was connected to ${only ? shortBssid(only) : "a single access point"}. A device only roams when it decides to, usually when the signal gets weak and another access point is clearly stronger, so staying within range of one access point produces no roams. Try a Walk Test along a route between two access points.`,
    };
  }
  return {
    title: "No roams recorded yet",
    body: "A roam is logged once a new access point holds for two consecutive readings.",
  };
}
