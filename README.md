# AP Monitor

A self-hosted WiFi **access-point** monitor for Linux, macOS and Windows. It
shows which access point (BSSID) your device is connected to, how strong and
clean the link is, when it moves to another access point, and — with the Walk
Test — where along a route the signal gets weak. Internet and gateway
reachability are tracked too, but as context ("is the problem the AP, or
upstream of it?"), not as the point of the app.

Everything runs and is stored on your own machine; there is no cloud
dependency.

- **Backend**: Python / FastAPI, async monitoring engine, SQLite storage
- **Frontend**: React + TypeScript + Tailwind CSS dashboard
- **CLI**: `ap-monitor` — talks to the same local REST API
- **Runs as**: a systemd service (Linux), a LaunchAgent (macOS) or a
  per-user Scheduled Task (Windows) — or straight from a source checkout

---

## Contents

1. [Quick start](#quick-start)
2. [What each page is for](#what-each-page-is-for)
3. [Platform support](#platform-support)
4. [Architecture](#architecture)
5. [Building from source](#building-from-source)
6. [Running](#running)
7. [Installing](#installing)
8. [Uninstalling](#uninstalling)
9. [Configuration](#configuration)
10. [The CLI](#the-cli)
11. [Testing](#testing)
12. [Packaging internals](#packaging-internals)
13. [Troubleshooting](#troubleshooting)
14. [Engineering decisions & known limitations](#engineering-decisions--known-limitations)

## Quick start

Run it straight from the source folder — no root/administrator rights, no
service install. The launcher creates a private virtualenv, builds the
dashboard if needed, starts the backend and opens your browser at
<http://127.0.0.1:8766>.

**Prerequisites**: Python 3.12 or 3.13 (3.10+ works where the pinned
dependencies have wheels; 3.14 may need newer pins), and Node.js 18+ only if
`frontend/dist` is not already built.

**Linux / macOS**

```bash
./scripts/run.sh            # add --no-open to skip opening the browser
```

**Windows** — double-click `scripts\run.bat`, or in PowerShell:

```powershell
.\scripts\run.ps1           # add -NoOpen to skip opening the browser
```

A virtualenv copied from another operating system (for example one inside a
zip made on a Mac) cannot run elsewhere; the launchers detect that and
rebuild it automatically.

Linux needs `nmcli` and `iw` to read WiFi (`sudo apt install network-manager
iw`). The dashboard tells you if anything the app needs is missing or blocked
on your system — see [Troubleshooting](#troubleshooting).

To keep it running in the background across restarts, see
[Installing](#installing). For frontend hot-reload development, see
[Building from source](#building-from-source).

---

## What each page is for

- **Dashboard** — the connected access point at a glance (network, BSSID,
  band/channel/width, signal in dBm, SNR, link rate), then a **signal-over-time
  chart whose line changes colour each time you move to a different access
  point**, with a legend and a table of every AP used. Internet/gateway
  reachability sits in a collapsed section underneath. If the OS is hiding
  WiFi details, a banner says so and how to fix it instead of leaving
  blanks.
- **Roaming** — every confirmed move between access points of the same
  network, with the signal before/after and an estimate of how long
  connectivity was interrupted. When there are none it tells you *why* (one
  access point only, WiFi details hidden, not connected, …) and shows the
  access-point history for the last 24 hours either way.
- **Walk Test** — for walking a site. Start a session, carry the device along
  your route (it samples about twice a second and shows a live view), then
  stop. You land on the **result**: signal along the route coloured by access
  point, the route as a bar showing how long each AP covered, the weak-signal
  spots (with a threshold you can change), every AP change, and a CSV export.
  Old sessions stay in the list; click one to reopen its result.
- **RF Tools** — an on-demand scan of the networks around you (the only thing
  that triggers an active radio scan; nothing runs it on a timer).
- **Targets / History** — the gateway/internet checks behind the
  "upstream reachability" numbers, and their history.

---

## Platform support

| | Linux | macOS | Windows |
|---|---|---|---|
| WiFi read | `nmcli` + `iw` | CoreWLAN (pyobjc) | `netsh wlan show interfaces` |
| Signal strength | RSSI (dBm) | RSSI (dBm), noise, SNR | derived from signal-quality % (0% = −100 dBm, 100% = −50 dBm); no noise/SNR |
| Connected BSSID | normally available | needs **Location Services** | Windows 11 may need **Location** enabled |
| Neighbour scan (RF Tools) | `iw scan` | SSID/channel only (no BSSIDs) | `netsh wlan show networks mode=bssid` (with BSSIDs) |
| ICMP ping | `ping` | `ping` | `ping` |
| Desktop notifications | `notify-send` | `osascript` | PowerShell toast |
| Runs in background as | systemd service | LaunchAgent (per-user) | Scheduled Task at logon (per-user) |
| Installer | `scripts/install.sh` | `scripts/install-macos.sh` | `scripts/install-windows.ps1` |

**How well each is verified.** The logic and parsers on every platform are
covered by automated tests, and the app has been run end to end on Linux.
The macOS and Windows WiFi readers have been tested against realistic
recorded output and fakes, **not on real macOS or Windows hardware** — if you
see odd values, run `ap-monitor status --json` and open an issue with the
output. A real bug of exactly this kind was found in the macOS reader during
this work (it looked up CoreWLAN constants under the wrong names and so never
saw a connected radio), which is why the test fakes there now mirror the real
module's names.

**Linux.** Gateway detection reads `/proc/net/route`; ICMP needs nothing
beyond the base dependencies. Without `nmcli`/`iw` every WiFi field is empty
and the dashboard says why.

**macOS.** The install is a per-user LaunchAgent (no `sudo` anywhere): a
LaunchDaemon would run outside a user session, where macOS's privacy system
does not apply to CoreWLAN's SSID/BSSID at all. From macOS 14/15 onward the
SSID and BSSID are withheld from any process without Location Services
permission; RSSI, channel and everything else still work. When that happens
the dashboard shows a banner and **roaming cannot be detected** until it is
fixed (System Settings → Privacy & Security → Location Services, allow the
app that launches the backend, then restart it). macOS may not show a prompt
for a background Python process by itself; if your launcher is not listed
there, start the backend from Terminal with `scripts/run.sh` and grant Terminal.

**Windows.** Signal strength is converted from the percentage `netsh`
reports using Microsoft's documented mapping, so it is accurate to roughly
2 dB and cannot read stronger than −50 dBm; the dashboard says so. `netsh`
prints localized labels: English is matched exactly and other languages are
recovered structurally (MAC address, `NN%`, `N GHz`, fixed line order), which
is best-effort. The installer registers a **per-user Scheduled Task** rather
than a Windows service, because `netsh wlan` works from the signed-in user's
session and is subject to that user's Location privacy setting, which a
service in session 0 cannot use. No console window appears: background
processes are started without one, and the task runs `pythonw`, with logs in
`%LOCALAPPDATA%\ap-monitor\logs\ap-monitor.log`.

---

## Architecture

```
ap-monitor/
├── backend/            FastAPI app, monitoring engine, SQLite layer
│   ├── app/
│   │   ├── api/        REST endpoints (status, wifi, roam-events, walk-tests, targets, measurements,
│   │   │               statistics, settings, monitoring, export, health)
│   │   ├── database/   schema.sql + async repositories (aiosqlite)
│   │   ├── monitoring/ wifi/ (one adapter per OS: linux.py, macos.py, windows.py, + diagnostics.py),
│   │   │               pinger.py (ICMP/TCP probes), scheduler.py (per-target + WiFi async loops)
│   │   ├── models/     Pydantic request/response/settings models
│   │   ├── services/   roaming + roam-interruption, walk tests, ap_analysis_service (signal/AP analysis),
│   │   │               statistics, quality, connectivity tracking, notifications, settings cache
│   │   ├── serve.py    console-less entry point (used by the Windows scheduled task)
│   │   └── main.py     app wiring, lifespan startup/shutdown, static frontend mount
│   └── tests/          pytest; OS tools and the WiFi radio are mocked/simulated
├── frontend/           React + TypeScript + Tailwind dashboard (Vite)
├── cli/                `ap-monitor` command-line client (Click + httpx)
├── packaging/
│   ├── systemd/        ap-monitor.service (hardened unit, Linux)
│   └── launchd/        com.ap-monitor.agent.plist (per-user LaunchAgent, macOS)
└── scripts/            run.sh / run.ps1 / run.bat   run from source (all platforms)
                         install.sh / uninstall.sh (Linux)
                         install-macos.sh / uninstall-macos.sh (macOS)
                         install-windows.ps1 / uninstall-windows.ps1 (Windows)
```

**Data flow**: `scheduler.py` runs one async task per enabled target. Each
tick calls `pinger.run_check()` (real ICMP via the system `ping` binary,
falling back to a raw TCP connect if ICMP isn't available), writes a
`measurements` row, checks per-target alert thresholds, then — serialized
behind a lock so concurrent target loops can't race — updates the global
online/offline state. A separate WiFi loop reads the radio through the
platform adapter every few seconds, stores a `wifi_samples` row, and feeds the
roam detector (as does the Walk Test sampler while a session is recording).
The dashboard and CLI both just read this same SQLite-backed state through
the REST API; the AP timeline and Walk Test results are derived on request by
`ap_analysis_service` from the stored samples, so nothing is computed twice.

**Why the API binds to `127.0.0.1` and never needs root**: the monitoring
process never opens a raw socket itself. It shells out to the system `ping`
binary (which is what actually needs `CAP_NET_RAW`) using `argv`-list
`subprocess`/`asyncio.create_subprocess_exec` calls — never `shell=True` —
so there's no shell-injection surface even though hostnames are
user-supplied, and no reason for the FastAPI process itself to run as root
or be network-reachable from anywhere but localhost.

---

## Building from source

**Backend**

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # includes uvicorn + test deps
```

**Frontend**

```bash
cd frontend
npm install
npm run build        # → frontend/dist, served by FastAPI in production
# or: npm run dev     # → http://127.0.0.1:5174 with hot reload, proxying /api
```

**CLI**

```bash
cd cli
pip install -e .     # installs the `ap-monitor` command
```

---

## Running

```bash
./scripts/run.sh          # Linux / macOS
.\scripts\run.ps1         # Windows
```

or, if you have already set up a virtualenv:

```bash
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8766     # Windows: .venv\Scripts\python
```

Open `http://127.0.0.1:8766` (if the frontend was built) or
`http://127.0.0.1:8766/docs` for the interactive API reference.

Useful environment variables (all optional):

| Variable | Default | Purpose |
|---|---|---|
| `AP_MONITOR_DATA_DIR` | `~/.local/share/ap-monitor` (Linux/macOS), `%LOCALAPPDATA%\ap-monitor` (Windows) | Where `ap-monitor.db` lives |
| `AP_MONITOR_HOST` | `127.0.0.1` | API bind address (keep this loopback-only) |
| `AP_MONITOR_PORT` | `8766` | API port |
| `AP_MONITOR_LOG_LEVEL` | `INFO` | Python logging level |
| `AP_MONITOR_AUTOSTART` | `1` | Set to `0` to boot the API without starting monitoring loops |

---

## Installing

**Linux:**
```bash
sudo ./scripts/install.sh --enable
```

This creates an unprivileged `ap-monitor` system user, installs to
`/opt/ap-monitor`, sets up a Python virtual environment (fetching
FastAPI/uvicorn/etc. from PyPI — **an internet connection is required at
install time**), installs the systemd unit, and (with `--enable`) enables
+ starts the service immediately. Works on any systemd-based Linux
distribution, not just Debian/Ubuntu.

```bash
sudo systemctl status ap-monitor
ap-monitor status
```

**macOS:**
```bash
./scripts/install-macos.sh --enable
```

No `sudo` at any point — installs to `~/Library/Application Support/ap-monitor`
for the current user only, as a LaunchAgent rather than a system-wide
service (see `packaging/launchd/com.ap-monitor.agent.plist` for why).

```bash
launchctl list | grep ap-monitor
ap-monitor status
```

**Windows** (PowerShell, no administrator rights needed):
```powershell
.\scripts\install-windows.ps1 -Start
```

Copies the app to `%LOCALAPPDATA%\ap-monitor`, creates a virtualenv, and
registers a per-user Scheduled Task named **AP Monitor** that starts at every
logon without a console window. (If PowerShell blocks the script, run it with
`powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1 -Start`.)

```powershell
Get-ScheduledTask -TaskName 'AP Monitor'
& "$env:LOCALAPPDATA\ap-monitor\venv\Scripts\ap-monitor.exe" status
```

---

## Uninstalling

**Linux:**
```bash
sudo ./scripts/uninstall.sh             # keeps data in /var/lib/ap-monitor
sudo ./scripts/uninstall.sh --purge     # also deletes stored history/settings
```

**macOS:**
```bash
./scripts/uninstall-macos.sh            # keeps data in ~/Library/Application Support/ap-monitor/data
./scripts/uninstall-macos.sh --purge    # also deletes stored history/settings
```

**Windows:**
```powershell
.\scripts\uninstall-windows.ps1              # keeps the database and logs
.\scripts\uninstall-windows.ps1 -RemoveData  # also deletes them
```

---

## Configuration

Everything in **Settings** on the dashboard (thresholds, notification
preferences, quality-classification boundaries, data retention, theme,
etc.) is stored in the `settings` table and editable at runtime via
`PUT /api/settings` — no restart needed. See `backend/app/models/settings.py`
for the full schema and defaults, or `ap-monitor config get` for the
current values. An example is below:

```json
{
  "ping_timeout_seconds": 2.0,
  "pings_per_check": 3,
  "latency_warning_threshold_ms": 150,
  "packet_loss_warning_threshold_pct": 5,
  "classification": {
    "excellent_latency_ms": 30, "excellent_packet_loss_pct": 1,
    "good_latency_ms": 60, "good_packet_loss_pct": 2,
    "fair_latency_ms": 100, "fair_packet_loss_pct": 5
  },
  "data_retention_days": 30,
  "theme": "system"
}
```

**Targets** (which hosts are monitored) are managed separately via the
Targets page, the `/api/targets` endpoints, or `ap-monitor targets`.
Three defaults are seeded on first run: your detected gateway, Cloudflare
DNS (`1.1.1.1`), and Google DNS (`8.8.8.8`).

**Start on boot**: the dashboard's toggle only records a preference — the
app never grants itself permission to change systemd state. Actually
enabling/disabling the boot-time service is a deliberate, explicit step:

```bash
ap-monitor service enable-boot     # sudo systemctl enable --now ap-monitor
ap-monitor service disable-boot    # sudo systemctl disable ap-monitor
```

---

## The CLI

```
ap-monitor status [--json]                 # access point first, then internet/gateway
ap-monitor wifi interfaces
ap-monitor wifi history [--minutes N] [--weak DBM]   # APs used, signal, AP changes, weak spots
ap-monitor wifi scan [--interface IF]
ap-monitor roam list [--interface IF] [--limit N]
ap-monitor walk-test start NAME [--site S] [--area A] [--interface IF] [--target-id ID ...]
ap-monitor walk-test stop ID
ap-monitor walk-test list
ap-monitor walk-test show ID [--weak DBM]            # the walk test result
ap-monitor walk-test export ID [-o FILE.csv]
ap-monitor start | stop                              # the monitoring loops
ap-monitor targets list | add | edit | remove
ap-monitor history [--target ID] [--range 1h|24h|7d|30d] [--limit N]
ap-monitor export --format csv|json [--target ID] [--range ...] [-o FILE]
ap-monitor config get [KEY] | set KEY VALUE
ap-monitor service enable-boot|disable-boot          # systemd / LaunchAgent / Scheduled Task
```

It's a thin client — every command calls the same local REST API the
dashboard uses (default `http://127.0.0.1:8766/api`, override with
`--api-url` or `AP_MONITOR_API_URL`). It never touches the database
or performs pings itself.

---

## Testing

**Backend** (211 tests; no real network or WiFi hardware required — every
subprocess and socket call is mocked or points at an ephemeral local server,
and the OS-level WiFi read is simulated). Includes an end-to-end test that
"walks" between two access points through the real HTTP API and checks the
roam event, the walk-test result and the CSV:

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest -q --cov=app --cov-report=term-missing
```

**Frontend** (99 tests: formatting and signal helpers, the signal chart,
the Dashboard / Walk Test / Walk Test result / Roaming pages against a mocked
API, and the API client's error handling):

```bash
cd frontend
npm test
```

**CLI** (12 tests):

```bash
cd cli && pip install -e . pytest && python -m pytest -q tests
```

---

## Packaging internals

- **systemd** (`packaging/systemd/ap-monitor.service`), installed by
  `scripts/install.sh`: see the comments in the unit file for the
  capability/hardening reasoning (short version: `NoNewPrivileges=true` +
  `ProtectSystem=strict` + everything else locked down, with exactly two
  capabilities granted via `AmbientCapabilities` — `CAP_NET_RAW` so ICMP
  works without the service running as root or relying on `ping` being
  setuid on the host distro, and `CAP_NET_ADMIN` so the on-demand "Scan
  Environment" feature can trigger a fresh `iw scan`).
- **launchd** (`packaging/launchd/com.ap-monitor.agent.plist`), installed
  by `scripts/install-macos.sh`: a per-user LaunchAgent, not a
  system-wide LaunchDaemon — see the comments at the top of the plist for
  why a LaunchDaemon wouldn't work here. Needs no special capability grant
  at all: ICMP shells out to the system `ping` binary (already privileged
  on macOS for any user), and CoreWLAN/`system_profiler` need no elevated
  privilege either.

---

## Troubleshooting

**The dashboard shows a yellow banner about WiFi details** — the app is
telling you something is missing. The text of the banner is specific to your
system; in short:

- *macOS*: grant **Location Services** (System Settings → Privacy & Security →
  Location Services) to the app that launches the backend, then restart it.
- *Windows*: turn on **Location** (Settings → Privacy & security → Location,
  including "Let desktop apps access your location"), then restart it.
  To see what Windows itself reports, run `netsh wlan show interfaces`.
- *Linux*: install `network-manager` and `iw`, and check that
  `iw dev <interface> link` prints a BSSID.

**The Roaming page is empty while I walk around** — first check the banner
above. If there is none, run `ap-monitor wifi history --minutes 30`: if it
lists a single access point, the device simply never switched. A device only
roams when *it* decides to, normally once the signal gets weak and another
access point is clearly stronger, so staying within range of one access point
(or having only one) produces no roams. Use a Walk Test along a route between
two access points to see where the handover happens.

**"Could not reach the AP Monitor service"** (CLI or dashboard) — the
backend isn't running, or is bound somewhere other than what you're asking.
Check `sudo systemctl status ap-monitor` (Linux), `launchctl list | grep
ap-monitor` (macOS) or `Get-ScheduledTask -TaskName 'AP Monitor'` (Windows),
or that your manual `uvicorn` process is still alive; check
`AP_MONITOR_PORT` matches what the client expects. On Windows the background
log is `%LOCALAPPDATA%\ap-monitor\logs\ap-monitor.log`.

**All targets show 100% loss / "ICMP not permitted"** — some
containers/sandboxes block raw sockets entirely, even for `CAP_NET_RAW`
processes. The app automatically falls back to TCP checks the first time
ICMP fails outright (logged once, not on every check) — if it doesn't,
confirm the `ping` binary exists at all (`which ping`; on minimal Linux images
you may need `apt install iputils-ping`).

**No desktop notifications** — Linux uses `notify-send` (`libnotify-bin`);
if it's not installed, notifications are logged instead of shown
(`sudo apt install libnotify-bin`, then restart). macOS uses `osascript` and
Windows uses a PowerShell toast; both need notifications allowed for the
respective app in system settings.

**Dashboard shows "Frontend build not found"** — you're running the backend
without having built the frontend first. Run `npm run build` in `frontend/`,
or use `npm run dev` for a hot-reloading dev server on port 5174.

**"database is locked" or similar SQLite errors** — shouldn't happen in
normal operation (writes are serialized through a single connection +
lock), but if you see it, check that nothing else has the database file
open (e.g. a second instance of the backend pointed at the same
`AP_MONITOR_DATA_DIR`).

**Journal logs**: `journalctl -u ap-monitor -f` for a packaged Linux install.

**Windows: installing dependencies fails with a Rust/compiler or
`CERTIFICATE_VERIFY_FAILED` error** — you are likely on a Python version the
pinned dependencies have no pre-built wheels for (for example 3.14), so `pip`
tries to compile `pydantic-core` from source. Use Python 3.12 or 3.13
(`py -3.12 -m venv .venv`).

**Windows: `'npm' is not recognized`** — Node.js is not installed or not on
`PATH`. Install the LTS release from nodejs.org (leave "Tools for Native
Modules" unticked) and open a new terminal. You only need Node to build the
frontend; a prebuilt `frontend\dist` works without it.

**Windows: `Error: connect ECONNREFUSED 127.0.0.1:8766` in the Vite dev
server** — the dev proxy cannot reach the backend. Make sure it is running
on port 8766. If it crashed with `[Errno 10048]` (port in use), find the PID
with `netstat -ano | findstr :8766` and stop it with `taskkill /PID <PID> /F`.

---

## Engineering decisions & known limitations

The brief asked for reasonable engineering decisions to be made and
documented where it left things unspecified. Here's what was decided and
why:

- **A check is a small batch, not a single ping.** Each "check" sends
  `pings_per_check` (default 3) ICMP echoes or TCP connection attempts in
  one go, and the stored `latency_ms`/`jitter_ms`/`packet_loss` for that
  measurement row are the average, mean-absolute-successive-difference, and
  loss % *within that batch*. This is what makes a meaningful per-check
  jitter and loss percentage possible at all — a single ping can't have
  "jitter." Aggregate statistics (min/max/median/p95 over a time range) are
  then computed across many such rows.
- **Headline latency/loss/jitter on the status view are averaged across
  non-gateway targets.** The gateway is typically a ~1ms local hop and
  isn't representative of "Internet" quality.
- **ICMP-unavailable fallback is logged once, not stamped onto every
  measurement.** If the `ping` binary is missing or blocked, the app
  permanently switches that process's checks to TCP and logs it a single
  time — it doesn't decorate every subsequent successful measurement's
  `error` field with a "used TCP instead" note forever.
- **The systemd unit needs `CAP_NET_RAW` for ICMP under `NoNewPrivileges`.**
  See the packaging section above and the unit file's comments.
- **The "Start on boot" setting never lets the app self-elevate.** It's
  purely a stored preference; actually changing systemd's enabled state is
  a separate, explicit `ap-monitor service enable-boot` command that
  shells out to `sudo systemctl` and will prompt for a password
  interactively. The API/dashboard process itself never gains, requests,
  or needs elevated privileges to do this.
- **`scripts/install.sh` fetches dependencies from PyPI at install time**
  rather than vendoring wheels, keeping the repo itself small and simple
  at the cost of requiring network access during install. For a fully
  offline install, `pip download` the requirements yourself ahead of
  time and point `pip install` at that local cache instead.
- **macOS WiFi metrics use CoreWLAN (via `pyobjc`), not a shelled-out CLI
  tool.** This is a direct framework binding (`app/monitoring/wifi/macos.py`),
  so it's fast and non-blocking enough to call on every poll - unlike
  `system_profiler SPAirPortDataType`, which forces an active scan and is
  reserved solely for the explicit, on-demand "Scan Environment" feature.
  If `pyobjc`/CoreWLAN isn't importable for some reason, the one documented
  fallback is the `airport` binary's `-I` flag specifically (reads kernel
  state immediately, no scan) - never `system_profiler`, and never a
  general CLI-tool fallback chain. (Apple removed `airport` in macOS 14.4, so
  on current systems pyobjc is the only working path.) Starting with macOS 15/Sequoia, reading
  `ssid`/`bssid` (through either path) additionally requires the calling
  process to have Location Services authorization, a one-time OS prompt
  this app can't skip or pre-grant - see the README's Platform support
  section and this file's own module docstring for the full detail.
- **Gateway auto-detection is a genuinely different mechanism per platform,
  not a shared code path.** Linux reads `/proc/net/route` directly (no
  subprocess needed); macOS has no `/proc` filesystem, so it shells out to
  `route -n get default`; Windows parses `route print -4` and takes the
  lowest-metric IPv4 default route. Both fall back to `192.168.1.1` if
  detection fails for any reason, rather than leaving the seeded Gateway
  target with an empty/invalid host.
- **Desktop notifications shell out to the OS's own tool** (`notify-send`,
  `osascript`, or a PowerShell toast on Windows) rather than a Python
  GUI-toolkit binding, so the monitoring service has zero GUI dependencies
  and runs identically headless or on a desktop. On Windows the title and
  message reach PowerShell through environment variables, never interpolated
  into the script.
- **The WiFi half of the app never fails silently.** The OS can hide the SSID
  and BSSID (macOS Location Services, Windows Location) while everything else
  keeps working, which would otherwise look exactly like a broken app. Every
  adapter flags that case, `/api/status` carries a `wifi_issue` with a
  platform-specific explanation, and the Dashboard, Roaming page, Walk Test
  result and CLI all show it. An adapter that cannot tell whether the radio is
  connected reports "unknown", which is deliberately not treated as
  "disconnected".
- **Roams are detected from BSSID changes, and a missing BSSID is "no
  information", never a new access point.** Otherwise two empty readings in
  a row would be confirmed as a roam to nothing. The Walk Test sampler feeds
  the same detector (about twice a second), so walking is when roams are
  caught fastest; the background poll is every few seconds.
- **Signal analysis is one shared, I/O-free module** (`ap_analysis_service`):
  it turns any time-ordered series of readings into per-AP usage, AP changes,
  weak-signal stretches and a thinned timeline, so the Dashboard's rolling
  window and a Walk Test result are computed identically.
- **Windows RSSI is derived, and says so.** `netsh` exposes quality %, not
  dBm; the documented linear mapping is applied and the UI notes it. Noise
  floor and SNR are left empty rather than invented.
- **Windows autostart is a per-user Scheduled Task, not a service**, for the
  session/Location reasons in [Platform support](#platform-support).
