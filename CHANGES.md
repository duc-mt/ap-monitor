# Changes in this version

## Fixed (why it "had no usable effect")
- **macOS: the WiFi reader never saw a connected radio.** CoreWLAN constants were looked up as
  `CWInterfaceStateRunning`; the real pyobjc names are `kCWInterfaceStateRunning` etc. Every reading came
  back `unknown`, so RSSI/channel stayed empty, the dashboard said "WiFi disconnected" permanently, and
  roam detection never ran. The test fakes used the same wrong names, which is why tests passed.
- An adapter that cannot tell whether WiFi is connected now reports "unknown" instead of "disconnected".
- Roam detection ignores readings with no BSSID (it used to be able to "roam" to `None`).
- The Walk Test sampler now feeds the roam detector (about twice a second while walking).
- SPA static-file serving could be tricked into reading files outside `frontend/dist` with `..` paths.
- 7 stale/failing tests fixed (walk-test fixtures below the 100 ms minimum; a roam-confidence expectation).

## New: access-point first UI
- **Dashboard**: connected AP card (SSID, BSSID, band/channel/width, dBm, SNR, link rate, quality), a signal
  chart that changes colour per access point, AP usage table and recent AP changes. Internet/gateway is a
  collapsed secondary section. The sidebar now shows the AP and signal.
- **Walk Test**: explains itself, live view while recording, and a **results page** (`/walk-test/:id`):
  summary, coloured timeline, route bar, weak-signal spots with an adjustable threshold, APs used, AP
  changes, CSV export. Sessions are clickable; stopping jumps to the result.
- **Roaming**: explains *why* it is empty and shows 24 h of access-point history.
- A **wifi_issue** banner (API + Dashboard + Roaming + CLI) explains hidden SSID/BSSID, missing Linux tools, etc.

## New: Windows support (plus working launchers everywhere)
- `app/monitoring/wifi/windows.py` (`netsh wlan`), Windows ping, gateway, notifications, data dir,
  no-console subprocesses, `app/serve.py`.
- `scripts/run.sh`, `run.ps1`, `run.bat` (run from source), `install-windows.ps1` / `uninstall-windows.ps1`.
- CLI: AP-first `status`, `wifi history`, `walk-test show|export`, platform-aware `service` commands.

## New API
`GET /api/wifi/analysis`, `GET /api/walk-tests/{id}/analysis`, `GET /api/walk-tests/{id}/export` (CSV);
`/api/status` gained `wifi_issue`, `platform`, `snr_db`, `noise_floor_dbm`, `tx_bitrate_mbps`, `channel_width_mhz`.

## Not verified on real hardware
macOS and Windows WiFi readers (tested against realistic recorded output and fakes), the Windows scripts
(PowerShell was not available to even syntax-check them), and the Windows toast notification.
