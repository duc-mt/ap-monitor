from __future__ import annotations

import subprocess
import sys

import pytest
from click.testing import CliRunner

from ap_monitor_cli import main as cli_main

ANALYSIS = {
    "summary": {
        "sample_count": 7, "duration_seconds": 6, "rssi_avg": -63.4, "rssi_max": -50, "rssi_min": -75,
        "pct_samples_weak": 42.9, "weak_threshold_dbm": -70, "bssid_available": True, "distinct_aps": 2,
        "ap_change_count": 1,
    },
    "aps": [
        {"bssid": "aa:01", "ssid": "Net", "band": "5GHz", "channel": 36, "total_seconds": 4, "share_pct": 71.4, "rssi_avg": -63},
        {"bssid": "aa:02", "ssid": "Net", "band": "2.4GHz", "channel": 6, "total_seconds": 1, "share_pct": 28.6, "rssi_avg": -59},
    ],
    "ap_changes": [{"timestamp": "t5", "from_bssid": "aa:01", "to_bssid": "aa:02", "rssi_before": -74, "rssi_after": -60,
                    "same_ssid": True, "via_disconnect": False}],
    "weak_stretches": [{"start": "t2", "duration_seconds": 2, "min_rssi_dbm": -75, "bssid": "aa:01"}],
}

STATUS = {
    "online": True, "quality": "good", "latency_ms": 20.0, "packet_loss": 0.0, "jitter_ms": 1.0,
    "monitoring_uptime_seconds": 60, "targets_reachable": 3, "targets_total": 3, "monitoring_running": True,
    "ssid": "HomeNet", "bssid": "aa:bb:cc:dd:ee:01", "rssi_dbm": -52, "channel": 36, "band": "5GHz",
    "phy_mode": "802.11ac", "channel_width_mhz": 80, "snr_db": 38, "tx_bitrate_mbps": 866.0,
    "wifi_issue": None, "wireless_quality_score": 91,
    "connectivity": {"wifi_connected": True, "overall": "internet_available"},
}


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.base_url = "http://x/api"

    def get(self, path, **kw):
        return self.data


def run(monkeypatch, data, *args):
    """Invoke the real CLI with its API client replaced by a canned one (the
    `cli` group builds its own client from --api-url, so `obj=` cannot be used)."""
    monkeypatch.setattr(cli_main, "ApiClient", lambda url: FakeClient(data))
    return CliRunner().invoke(cli_main.cli, list(args))


def test_status_leads_with_the_access_point(monkeypatch):
    out = run(monkeypatch, STATUS, "status").output
    assert out.index("Access point") < out.index("Internet:")
    assert "aa:bb:cc:dd:ee:01" in out and "-52 dBm" in out and "SNR 38 dB" in out and "80 MHz" in out


def test_status_explains_a_hidden_bssid(monkeypatch):
    data = {**STATUS, "ssid": None, "bssid": None, "wifi_issue": {"code": "x", "title": "WiFi details are hidden by the OS", "detail": "Turn on Location."}}
    out = run(monkeypatch, data, "status").output
    assert "WiFi details are hidden by the OS" in out and "Turn on Location." in out


def test_wifi_history_and_walk_test_show_print_the_ap_breakdown(monkeypatch):
    out = run(monkeypatch, ANALYSIS, "wifi", "history").output
    assert "aa:01" in out and "aa:02" in out and "71%" in out
    assert "aa:01 -> aa:02" in out and "worst -75 dBm" in out


def test_analysis_without_bssids_says_why_instead_of_printing_an_empty_table(monkeypatch):
    data = {**ANALYSIS, "summary": {**ANALYSIS["summary"], "bssid_available": False}}
    out = run(monkeypatch, data, "wifi", "history").output
    assert "not reported by the system" in out
    assert "Access points:" not in out          # no empty/misleading AP table follows


@pytest.mark.parametrize("platform,first,count", [
    ("linux", "sudo", 1), ("darwin", "launchctl", 1), ("win32", "schtasks", 2),
])
def test_service_commands_follow_the_platform(monkeypatch, platform, first, count):
    monkeypatch.setattr(sys, "platform", platform)
    enable = cli_main._service_commands("enable")
    assert enable[0][0] == first and len(enable) == count
    disable = cli_main._service_commands("disable")
    assert disable[-1][0] == first


def test_windows_enable_runs_the_task_and_disable_stops_then_disables(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert cli_main._service_commands("enable") == [
        ["schtasks", "/Change", "/TN", "AP Monitor", "/ENABLE"], ["schtasks", "/Run", "/TN", "AP Monitor"]]
    assert cli_main._service_commands("disable") == [
        ["schtasks", "/End", "/TN", "AP Monitor"], ["schtasks", "/Change", "/TN", "AP Monitor", "/DISABLE"]]


def test_missing_os_tool_gives_an_actionable_error(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    def boom(*a, **k): raise FileNotFoundError()
    monkeypatch.setattr(subprocess, "run", boom)
    res = run(monkeypatch, {}, "service", "enable-boot")
    assert res.exit_code != 0 and "launchctl not found" in res.output and "install-macos.sh" in res.output


@pytest.mark.parametrize("platform,needle", [("win32", "Get-ScheduledTask"), ("darwin", "launchctl list"), ("linux", "systemctl status")])
def test_unreachable_hint_is_platform_specific(monkeypatch, platform, needle):
    monkeypatch.setattr(sys, "platform", platform)
    assert needle in cli_main._is_running_hint()
