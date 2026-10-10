import { NavLink } from "react-router-dom";
import { Gauge, History, MonitorDot, Settings as SettingsIcon, Moon, Sun, Laptop, Radio, Footprints, RadioTower } from "lucide-react";
import { useStatus } from "../hooks/useStatus";
import { useTheme } from "../hooks/useTheme";
import { QUALITY_COLOR } from "./QualityBadge";
import { SIGNAL_COLOR, classifySignal } from "../services/signal";
import type { Theme } from "../types";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: Gauge, end: true },
  { to: "/targets", label: "Targets", icon: MonitorDot, end: false },
  { to: "/history", label: "History", icon: History, end: false },
  { to: "/roaming", label: "Roaming", icon: Radio, end: false },
  { to: "/walk-test", label: "Walk Test", icon: Footprints, end: false },
  { to: "/rf-tools", label: "RF Tools", icon: RadioTower, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

export function Sidebar() {
  const { data: status } = useStatus();
  const { theme, setTheme } = useTheme();

  // The sidebar speaks about the access point first; the dot follows its
  // signal strength, falling back to upstream quality when no RSSI is known.
  const dotColor = !status
    ? "var(--color-unknown)"
    : status.rssi_dbm !== null
      ? SIGNAL_COLOR[classifySignal(status.rssi_dbm)]
      : QUALITY_COLOR[status.quality];
  const apLine = !status
    ? "—"
    : status.connectivity.wifi_connected === false
      ? "WiFi disconnected"
      : [status.ssid ?? "WiFi", status.rssi_dbm !== null ? `${status.rssi_dbm} dBm` : null].filter(Boolean).join(" · ");

  return (
    <aside className="w-[220px] shrink-0 border-r border-border bg-panel flex flex-col h-full">
      <div className="px-5 py-5 border-b border-border">
        <div className="flex items-center gap-2">
          <span
            className="h-2.5 w-2.5 rounded-full transition-colors"
            style={{ backgroundColor: dotColor, boxShadow: `0 0 8px ${dotColor}` }}
          />
          <span className="font-semibold tracking-tight text-[15px]">AP Monitor</span>
        </div>
        <p className="mt-1 text-[11px] text-muted font-mono truncate" title={apLine} data-testid="sidebar-ap">
          {apLine}
        </p>
        {status && (
          <p className="text-[11px] text-muted font-mono">Internet {status.online ? "online" : "offline"}</p>
        )}
      </div>

      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-control px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-accent-soft text-accent font-medium"
                  : "text-muted hover:text-text hover:bg-panel-alt"
              }`
            }
          >
            <Icon size={16} strokeWidth={2} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-3 py-4 border-t border-border">
        <div className="flex items-center rounded-control border border-border p-0.5 gap-0.5">
          {(["light", "system", "dark"] as Theme[]).map((t) => {
            const Icon = t === "light" ? Sun : t === "dark" ? Moon : Laptop;
            return (
              <button
                key={t}
                onClick={() => setTheme(t)}
                aria-label={`${t} theme`}
                className={`flex-1 flex items-center justify-center py-1.5 rounded-[4px] transition-colors ${
                  theme === t ? "bg-accent-soft text-accent" : "text-muted hover:text-text"
                }`}
              >
                <Icon size={14} />
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
