"""
ap-monitor: command-line interface.

This is a thin client over the local REST API (default
http://127.0.0.1:8766/api) - it never touches the database or performs
pings itself, so `ap-monitor status` always reflects exactly what the
dashboard would show.
"""

from __future__ import annotations

import json as jsonlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import click
import httpx

DEFAULT_API_URL = "http://127.0.0.1:8766/api"

TASK_NAME = "AP Monitor"  # Windows scheduled task (scripts/install-windows.ps1)
LAUNCH_AGENT = (
    Path.home() / "Library" / "LaunchAgents" / "com.ap-monitor.agent.plist"
)  # macOS


def _is_running_hint() -> str:
    if sys.platform == "win32":
        return f"Get-ScheduledTask -TaskName '{TASK_NAME}'   (or run scripts\\run.bat from the source folder)"
    if sys.platform == "darwin":
        return "launchctl list | grep ap-monitor   (or run scripts/run.sh from the source folder)"
    return "sudo systemctl status ap-monitor   (or run scripts/run.sh from the source folder)"


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = httpx.request(
                method, f"{self.base_url}{path}", timeout=10.0, **kwargs
            )
        except httpx.ConnectError:
            raise click.ClickException(
                f"Could not reach the AP Monitor service at {self.base_url}.\n"
                f"  Is it running? Try: {_is_running_hint()}"
            )
        except httpx.TimeoutException:
            raise click.ClickException("Request to the AP Monitor service timed out.")
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            raise click.ClickException(f"API error {resp.status_code}: {detail}")
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def get(self, path: str, **kwargs) -> Any:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Any:
        return self._request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> Any:
        return self._request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> Any:
        return self._request("DELETE", path, **kwargs)


def print_table(rows: list[dict], columns: Optional[list[str]] = None) -> None:
    if not rows:
        click.echo("(none)")
        return
    cols = columns or list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    header = "  ".join(c.upper().ljust(widths[c]) for c in cols)
    click.echo(header)
    click.echo("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        click.echo("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


@click.group()
@click.option(
    "--api-url",
    default=DEFAULT_API_URL,
    envvar="AP_MONITOR_API_URL",
    help="Base URL of the AP Monitor API.",
    show_default=True,
)
@click.pass_context
def cli(ctx: click.Context, api_url: str):
    """Command-line interface for AP Monitor."""
    ctx.obj = ApiClient(api_url)


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------
@cli.command()
@click.option(
    "--json", "as_json", is_flag=True, help="Print raw JSON instead of a summary."
)
@click.pass_obj
def status(client: ApiClient, as_json: bool):
    """Show current connectivity status."""
    data = client.get("/status")
    if as_json:
        click.echo(jsonlib.dumps(data, indent=2))
        return

    # The access point comes first: that is what this tool is for. Internet and
    # gateway reachability follow as context.
    click.echo(click.style("Access point", bold=True))
    if data["ssid"] or data.get("bssid"):
        click.echo(f"  Network:  {data['ssid'] or '(name hidden)'}")
        click.echo(f"  BSSID:    {data.get('bssid') or 'not reported'}")
        radio = [
            f"ch {data['channel']}" if data["channel"] is not None else None,
            data["band"],
            f"{data['channel_width_mhz']} MHz"
            if data.get("channel_width_mhz")
            else None,
            data["phy_mode"],
        ]
        if any(radio):
            click.echo(f"  Radio:    {'  ·  '.join(x for x in radio if x)}")
        if data["rssi_dbm"] is not None:
            snr = (
                f"  (SNR {data['snr_db']} dB)" if data.get("snr_db") is not None else ""
            )
            click.echo(f"  Signal:   {data['rssi_dbm']} dBm{snr}")
        if data.get("tx_bitrate_mbps"):
            click.echo(f"  Link:     {round(data['tx_bitrate_mbps'])} Mbps")
        if data["wireless_quality_score"] is not None:
            click.echo(f"  Quality:  {data['wireless_quality_score']}/100")
    else:
        click.echo(
            "  not connected"
            if data["connectivity"]["wifi_connected"] is False
            else "  no AP information available"
        )
    issue = data.get("wifi_issue")
    if issue:
        click.echo(click.style(f"  ! {issue['title']}", fg="yellow", bold=True))
        click.echo(f"    {issue['detail']}")

    click.echo()
    state = "ONLINE" if data["online"] else "OFFLINE"
    color = "green" if data["online"] else "red"
    click.echo(
        f"Internet: {click.style(state, fg=color, bold=True)}  (quality: {data['quality']})"
    )
    click.echo(f"Latency:     {_fmt_ms(data['latency_ms'])}")
    click.echo(f"Packet loss: {_fmt_pct(data['packet_loss'])}")
    click.echo(f"Jitter:      {_fmt_ms(data['jitter_ms'])}")
    click.echo(
        f"Targets reachable: {data['targets_reachable']}/{data['targets_total']}"
    )
    click.echo(
        f"Monitoring: {'running' if data['monitoring_running'] else 'stopped'} "
        f"(uptime {int(data['monitoring_uptime_seconds'])}s)"
    )
    click.echo(f"Connectivity: {data['connectivity']['overall'].replace('_', ' ')}")


def _fmt_secs(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _print_analysis(data: dict) -> None:
    """Human summary of a /wifi/analysis or /walk-tests/{id}/analysis response."""
    s = data["summary"]
    if s["sample_count"] == 0:
        click.echo("No WiFi readings in that period.")
        return
    click.echo(f"{s['sample_count']} readings over {_fmt_secs(s['duration_seconds'])}")
    if s["rssi_avg"] is not None:
        weak = (
            f", {s['pct_samples_weak']:.0f}% below {s['weak_threshold_dbm']} dBm"
            if s["pct_samples_weak"] is not None
            else ""
        )
        click.echo(
            f"Signal: avg {s['rssi_avg']} dBm, best {s['rssi_max']}, worst {s['rssi_min']}{weak}"
        )
    if not s["bssid_available"]:
        click.echo(
            click.style(
                "Access point addresses were not reported by the system, so the per-AP "
                "breakdown is unavailable (run `ap-monitor status` for how to fix this).",
                fg="yellow",
            )
        )
        return
    click.echo(
        f"Access points: {s['distinct_aps']}   AP changes: {s['ap_change_count']}"
    )
    if data["aps"]:
        click.echo()
        print_table(
            [
                {
                    "BSSID": a["bssid"] or "unknown",
                    "SSID": a["ssid"] or "",
                    "Band": a["band"] or "",
                    "Ch": a["channel"] if a["channel"] is not None else "",
                    "Time": _fmt_secs(a["total_seconds"]),
                    "Share": f"{a['share_pct']:.0f}%",
                    "Avg dBm": a["rssi_avg"] if a["rssi_avg"] is not None else "",
                }
                for a in data["aps"]
            ]
        )
    if data["ap_changes"]:
        click.echo()
        click.echo("AP changes:")
        for c in data["ap_changes"]:
            note = "" if c["same_ssid"] else "  (different network)"
            note += "  (via a disconnect)" if c["via_disconnect"] else ""
            click.echo(
                f"  {c['timestamp']}  {c['from_bssid']} -> {c['to_bssid']}  {c['rssi_before']} -> {c['rssi_after']} dBm{note}"
            )
    if data["weak_stretches"]:
        click.echo()
        click.echo(f"Weak-signal stretches (below {s['weak_threshold_dbm']} dBm):")
        for w in data["weak_stretches"]:
            click.echo(
                f"  {w['start']}  {_fmt_secs(w['duration_seconds'])}  worst {w['min_rssi_dbm']} dBm  on {w['bssid'] or 'unknown AP'}"
            )


def _fmt_ms(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f} ms"


def _fmt_pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}%"


# --------------------------------------------------------------------------
# start / stop
# --------------------------------------------------------------------------
@cli.command()
@click.pass_obj
def start(client: ApiClient):
    """Start the monitoring loops."""
    result = client.post("/monitoring/start")
    click.echo(
        "Monitoring started." if result["running"] else "Monitoring did not start."
    )


@cli.command()
@click.pass_obj
def stop(client: ApiClient):
    """Stop the monitoring loops."""
    result = client.post("/monitoring/stop")
    click.echo(
        "Monitoring stopped."
        if not result["running"]
        else "Monitoring is still running."
    )


# --------------------------------------------------------------------------
# targets
# --------------------------------------------------------------------------
@cli.group()
def targets():
    """Manage monitored targets."""


@targets.command("list")
@click.pass_obj
def targets_list(client: ApiClient):
    """List all configured targets."""
    rows = client.get("/targets")
    print_table(
        [
            {
                "id": t["id"],
                "name": t["name"],
                "host": t["host"],
                "protocol": t["protocol"],
                "interval": f"{t['interval_seconds']}s",
                "enabled": t["enabled"],
                "gateway": t["is_gateway"],
            }
            for t in rows
        ]
    )


@targets.command("add")
@click.argument("name")
@click.argument("host")
@click.option(
    "--protocol", type=click.Choice(["icmp", "tcp"]), default="icmp", show_default=True
)
@click.option(
    "--port",
    type=int,
    default=None,
    help="TCP port (required for --protocol tcp unless you want the default of 443).",
)
@click.option(
    "--interval", type=int, default=5, show_default=True, help="Seconds between checks."
)
@click.option("--gateway", is_flag=True, help="Mark as the local gateway.")
@click.option("--disabled", is_flag=True, help="Create the target disabled.")
@click.pass_obj
def targets_add(
    client: ApiClient, name, host, protocol, port, interval, gateway, disabled
):
    """Add a new monitored target, e.g. `ap-monitor targets add "Office WAN" 203.0.113.5`."""
    payload = {
        "name": name,
        "host": host,
        "protocol": protocol,
        "port": port,
        "interval_seconds": interval,
        "is_gateway": gateway,
        "enabled": not disabled,
    }
    created = client.post("/targets", json=payload)
    click.echo(f"Created target #{created['id']} ({created['name']}).")


@targets.command("edit")
@click.argument("target_id", type=int)
@click.option("--name", default=None)
@click.option("--host", default=None)
@click.option("--protocol", type=click.Choice(["icmp", "tcp"]), default=None)
@click.option("--port", type=int, default=None)
@click.option("--interval", type=int, default=None)
@click.option("--enable/--disable", "enabled", default=None)
@click.pass_obj
def targets_edit(
    client: ApiClient, target_id, name, host, protocol, port, interval, enabled
):
    """Edit fields of an existing target by id."""
    payload = {
        k: v
        for k, v in {
            "name": name,
            "host": host,
            "protocol": protocol,
            "port": port,
            "interval_seconds": interval,
            "enabled": enabled,
        }.items()
        if v is not None
    }
    if not payload:
        raise click.UsageError("Provide at least one field to change.")
    updated = client.put(f"/targets/{target_id}", json=payload)
    click.echo(f"Updated target #{updated['id']} ({updated['name']}).")


@targets.command("remove")
@click.argument("target_id", type=int)
@click.confirmation_option(prompt="Delete this target and its measurement history?")
@click.pass_obj
def targets_remove(client: ApiClient, target_id):
    """Delete a target."""
    client.delete(f"/targets/{target_id}")
    click.echo(f"Deleted target #{target_id}.")


# --------------------------------------------------------------------------
# history
# --------------------------------------------------------------------------
@cli.command()
@click.option(
    "--target", "target_id", type=int, default=None, help="Filter by target id."
)
@click.option(
    "--range",
    "range_name",
    default="24h",
    type=click.Choice(["1h", "24h", "7d", "30d"]),
    show_default=True,
)
@click.option("--limit", type=int, default=20, show_default=True)
@click.pass_obj
def history(client: ApiClient, target_id, range_name, limit):
    """Show recent measurements and a summary for the chosen range."""
    stats = client.get(
        "/statistics",
        params={"range": range_name, **({"target_id": target_id} if target_id else {})},
    )
    click.echo(f"Statistics ({range_name}):")
    click.echo(
        f"  avg={_fmt_ms(stats['avg_latency_ms'])}  min={_fmt_ms(stats['min_latency_ms'])}  "
        f"max={_fmt_ms(stats['max_latency_ms'])}  p95={_fmt_ms(stats['p95_latency_ms'])}"
    )
    click.echo(
        f"  packet loss={_fmt_pct(stats['packet_loss_pct'])}  jitter={_fmt_ms(stats['avg_jitter_ms'])}  "
        f"samples={stats['sample_count']}"
    )
    click.echo()

    params = {"limit": limit}
    if target_id:
        params["target_id"] = target_id
    rows = client.get("/measurements", params=params)
    print_table(
        [
            {
                "time": m["timestamp"],
                "target": m.get("target_name", m["target_id"]),
                "latency_ms": m["latency_ms"],
                "loss%": m["packet_loss"],
                "success": m["success"],
            }
            for m in rows
        ]
    )


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------
@cli.command()
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["csv", "json"]),
    default="csv",
    show_default=True,
)
@click.option("--target", "target_id", type=int, default=None)
@click.option(
    "--range",
    "range_name",
    default="24h",
    type=click.Choice(["1h", "24h", "7d", "30d"]),
    show_default=True,
    help="Only used for --format json (the summarized report).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Write to this file instead of stdout.",
)
@click.pass_obj
def export(client: ApiClient, fmt, target_id, range_name, output):
    """Export measurement data as CSV, or a summarized report as JSON."""
    if fmt == "csv":
        params = {"target_id": target_id} if target_id else {}
        resp = httpx.get(
            f"{client.base_url}/export/measurements.csv", params=params, timeout=30.0
        )
        content = resp.text
    else:
        params = {
            "range": range_name,
            **({"target_id": target_id} if target_id else {}),
        }
        resp = httpx.get(
            f"{client.base_url}/export/report.json", params=params, timeout=30.0
        )
        content = resp.text

    if output:
        with open(output, "w") as f:
            f.write(content)
        click.echo(f"Wrote {output}")
    else:
        click.echo(content)


# --------------------------------------------------------------------------
# wifi
# --------------------------------------------------------------------------
@cli.group()
def wifi():
    """WiFi interfaces and on-demand scanning."""


@wifi.command("interfaces")
@click.pass_obj
def wifi_interfaces(client: ApiClient):
    """List WiFi-capable interfaces."""
    rows = client.get("/wifi/interfaces")
    print_table(
        [
            {"name": r["name"], "state": r["state"], "active": r["is_active"]}
            for r in rows
        ]
    )


@wifi.command("history")
@click.option(
    "--minutes",
    default=60,
    show_default=True,
    type=click.IntRange(1, 10080),
    help="Look-back window.",
)
@click.option(
    "--weak",
    "weak_dbm",
    default=-70,
    show_default=True,
    type=click.IntRange(-100, -30),
    help="Weak-signal threshold (dBm).",
)
@click.pass_obj
def wifi_history(client: ApiClient, minutes: int, weak_dbm: int):
    """Which access points you were on recently, and how strong the signal was."""
    _print_analysis(
        client.get(
            "/wifi/analysis",
            params={"minutes": minutes, "weak_threshold_dbm": weak_dbm},
        )
    )


@wifi.command("scan")
@click.option(
    "--interface",
    default=None,
    help="Interface to scan on (default: the currently active one).",
)
@click.pass_obj
def wifi_scan(client: ApiClient, interface: Optional[str]):
    """
    Actively scan for surrounding networks. On-demand only - this is the
    one command in the whole app that triggers a real radio scan; nothing
    here ever runs on a timer.
    """
    params = {"interface": interface} if interface else {}
    result = client.post("/wifi/scan", params=params)
    header = f"{len(result['neighbors'])} network(s) found on {result['interface']}"
    if result["connected_channel"] is not None:
        header += f"  (you're on channel {result['connected_channel']}, {result['connected_band']})"
    click.echo(header)
    click.echo()
    neighbors = sorted(
        result["neighbors"],
        key=lambda n: -(n["rssi_dbm"] if n["rssi_dbm"] is not None else -999),
    )
    print_table(
        [
            {
                "ssid": n["ssid"] or "(hidden)",
                "channel": f"{n['channel']}{'*' if n['is_co_channel'] else ''}"
                if n["channel"] is not None
                else "-",
                "phy": n["phy_mode"] or "-",
                "security": n["security"] or "-",
                "rssi": f"{n['rssi_dbm']} dBm" if n["rssi_dbm"] is not None else "-",
            }
            for n in neighbors
        ]
    )
    if any(n["is_co_channel"] for n in neighbors):
        click.echo()
        click.echo("* co-channel with your current connection")


# --------------------------------------------------------------------------
# roam
# --------------------------------------------------------------------------
@cli.group()
def roam():
    """Roaming event history."""


@roam.command("list")
@click.option("--interface", default=None, help="Filter by interface.")
@click.option("--limit", type=int, default=20, show_default=True)
@click.pass_obj
def roam_list(client: ApiClient, interface: Optional[str], limit: int):
    """List recent confirmed roams, most recent first."""
    params: dict = {"limit": limit}
    if interface:
        params["interface"] = interface
    rows = client.get("/roam-events", params=params)
    print_table(
        [
            {
                "time": r["timestamp"],
                "ssid": r["ssid"] or "-",
                "bssid change": f"{r['previous_bssid'] or '-'} -> {r['new_bssid'] or '-'}",
                "interruption": _fmt_ms(
                    r["internet_interruption_ms"]
                    if r["internet_interruption_ms"] is not None
                    else r["gateway_interruption_ms"]
                ),
                "classification": r["classification"]
                or ("failed" if r["success"] is False else "-"),
                "confidence": r["confidence"] or "-",
            }
            for r in rows
        ]
    )


# --------------------------------------------------------------------------
# walk-test
# --------------------------------------------------------------------------
@cli.group("walk-test")
def walk_test():
    """Walk-test session management (dense WiFi sampling while walking a site)."""


@walk_test.command("start")
@click.argument("name")
@click.option("--site", default=None)
@click.option("--area", default=None)
@click.option("--interface", required=True, help="WiFi interface to sample.")
@click.option(
    "--target",
    "target_ids",
    type=int,
    multiple=True,
    help="Target id to also check latency against during the session (repeatable). Optional - "
    "walk-test mode never requires connectivity to run.",
)
@click.pass_obj
def walk_test_start(client: ApiClient, name: str, site, area, interface, target_ids):
    """Start a new walk-test recording session."""
    payload = {
        "name": name,
        "site": site,
        "area": area,
        "interface": interface,
        "target_ids": list(target_ids),
    }
    result = client.post("/walk-tests", json=payload)
    click.echo(
        f"Started walk-test session #{result['id']} ('{result['name']}') on {result['interface']}."
    )
    click.echo(
        f"Run `ap-monitor walk-test stop {result['id']}` when you're done walking."
    )


@walk_test.command("stop")
@click.argument("walk_test_id", type=int)
@click.pass_obj
def walk_test_stop(client: ApiClient, walk_test_id: int):
    """Stop a recording walk-test session."""
    result = client.post(f"/walk-tests/{walk_test_id}/stop")
    click.echo(
        f"Stopped walk-test session #{result['id']} ({result['sample_count']} sample(s) recorded)."
    )


@walk_test.command("show")
@click.argument("walk_test_id", type=int)
@click.option(
    "--weak",
    "weak_dbm",
    default=-70,
    show_default=True,
    type=click.IntRange(-100, -30),
    help="Weak-signal threshold (dBm).",
)
@click.pass_obj
def walk_test_show(client: ApiClient, walk_test_id: int, weak_dbm: int):
    """Show the result of a walk test: signal, weak spots, and the APs used."""
    session = client.get(f"/walk-tests/{walk_test_id}")
    click.echo(
        f"{session['name']}  ({session['status']}, {session['sample_count']} samples)"
    )
    click.echo()
    _print_analysis(
        client.get(
            f"/walk-tests/{walk_test_id}/analysis",
            params={"weak_threshold_dbm": weak_dbm},
        )
    )


@walk_test.command("export")
@click.argument("walk_test_id", type=int)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="File to write (default: stdout).",
)
@click.pass_obj
def walk_test_export(client: ApiClient, walk_test_id: int, output: Optional[str]):
    """Export every sample of a walk test as CSV."""
    resp = httpx.get(
        f"{client.base_url}/walk-tests/{walk_test_id}/export", timeout=30.0
    )
    if resp.status_code >= 400:
        raise click.ClickException(f"API error {resp.status_code}: {resp.text}")
    if output:
        Path(output).write_bytes(resp.content)
        click.echo(f"Wrote {output}")
    else:
        click.echo(resp.text, nl=False)


@walk_test.command("list")
@click.pass_obj
def walk_test_list(client: ApiClient):
    """List walk-test sessions, most recent first."""
    rows = client.get("/walk-tests")
    print_table(
        [
            {
                "id": r["id"],
                "name": r["name"],
                "site": r["site"] or "-",
                "interface": r["interface"],
                "status": r["status"],
                "samples": r["sample_count"],
                "started": r["started_at"],
            }
            for r in rows
        ]
    )


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
@cli.group()
def config():
    """View or change monitoring settings."""


@config.command("get")
@click.argument("key", required=False)
@click.pass_obj
def config_get(client: ApiClient, key: Optional[str]):
    """Print all settings, or a single dotted key (e.g. notifications.on_offline)."""
    data = client.get("/settings")
    if key is None:
        click.echo(jsonlib.dumps(data, indent=2))
        return
    value = _dotted_get(data, key)
    click.echo(jsonlib.dumps(value) if isinstance(value, (dict, list)) else value)


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_obj
def config_set(client: ApiClient, key: str, value: str):
    """Set a single dotted key, e.g. `config set data_retention_days 60`."""
    parsed = _parse_scalar(value)
    payload = _dotted_set({}, key, parsed)
    updated = client.put("/settings", json=payload)
    click.echo(f"{key} = {_dotted_get(updated, key)}")


def _dotted_get(data: dict, key: str) -> Any:
    node = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise click.ClickException(f"Unknown setting: {key}")
        node = node[part]
    return node


def _dotted_set(root: dict, key: str, value: Any) -> dict:
    parts = key.split(".")
    node = root
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    return root


def _parse_scalar(raw: str) -> Any:
    lowered = raw.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


# --------------------------------------------------------------------------
# service (start-at-login/boot integration - the one place the CLI changes
# anything outside the app, and only when the user explicitly asks for it)
# --------------------------------------------------------------------------
@cli.group()
def service():
    """Manage start-at-boot (systemd on Linux, a LaunchAgent on macOS, a Scheduled Task on Windows)."""


def _service_commands(action: str) -> list[list[str]]:
    """The OS commands that enable or disable autostart, one list per command."""
    if sys.platform == "win32":
        if action == "enable":
            return [
                ["schtasks", "/Change", "/TN", TASK_NAME, "/ENABLE"],
                ["schtasks", "/Run", "/TN", TASK_NAME],
            ]
        return [
            ["schtasks", "/End", "/TN", TASK_NAME],
            ["schtasks", "/Change", "/TN", TASK_NAME, "/DISABLE"],
        ]
    if sys.platform == "darwin":
        return [
            [
                "launchctl",
                "load" if action == "enable" else "unload",
                "-w",
                str(LAUNCH_AGENT),
            ]
        ]
    if action == "enable":
        return [["sudo", "systemctl", "enable", "--now", "ap-monitor.service"]]
    return [["sudo", "systemctl", "disable", "ap-monitor.service"]]


@service.command("enable-boot")
def service_enable_boot():
    """Start AP Monitor automatically (and start it now)."""
    _run_service_commands(_service_commands("enable"))


@service.command("disable-boot")
def service_disable_boot():
    """Stop starting AP Monitor automatically."""
    _run_service_commands(_service_commands("disable"))


def _run_service_commands(commands: list[list[str]]) -> None:
    for cmd in commands:
        click.echo(f"Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True)
        except FileNotFoundError:
            raise click.ClickException(
                f"{cmd[0]} not found - this command needs the AP Monitor installer for your OS "
                f"(scripts/install.sh, scripts/install-macos.sh or scripts/install-windows.ps1)."
            )
        except subprocess.CalledProcessError as exc:
            raise click.ClickException(
                f"{cmd[0]} exited with status {exc.returncode}. Has AP Monitor been installed with the "
                f"installer for your OS (scripts/install*)?"
            )


def main() -> None:
    cli(auto_envvar_prefix="AP_MONITOR")


if __name__ == "__main__":
    sys.exit(cli())
