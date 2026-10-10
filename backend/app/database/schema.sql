-- AP Monitor database schema.
-- Applied idempotently at startup (CREATE TABLE IF NOT EXISTS).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS targets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    host            TEXT NOT NULL,
    protocol        TEXT NOT NULL CHECK (protocol IN ('icmp', 'tcp')),
    port            INTEGER,
    is_gateway      INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    interval_seconds INTEGER NOT NULL DEFAULT 5,
    created_at      TEXT NOT NULL
);

-- One row per completed check (a small batch of pings/connects against a
-- single target). latency_ms/jitter_ms are NULL when every attempt in the
-- batch failed.
CREATE TABLE IF NOT EXISTS measurements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id       INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    timestamp       TEXT NOT NULL,
    latency_ms      REAL,
    packet_loss     REAL NOT NULL,
    jitter_ms       REAL,
    success         INTEGER NOT NULL,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_measurements_target_ts ON measurements(target_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_measurements_ts ON measurements(timestamp);

-- One row per periodic WiFi metrics poll (see app/monitoring/wifi/), plus
-- one row per walk-test sample once Stage 11 lands. Every metric column is
-- nullable by design (app/monitoring/wifi/models.py never fabricates an
-- unsupported reading), and *_addresses/dns_servers store a JSON array
-- rather than a separate child table since they're small, fixed-purpose,
-- and never queried by individual address.
CREATE TABLE IF NOT EXISTS wifi_samples (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    interface         TEXT NOT NULL,
    interface_state   TEXT NOT NULL,
    ssid              TEXT,
    bssid             TEXT,
    frequency_mhz     INTEGER,
    channel           INTEGER,
    band              TEXT,
    rssi_dbm          INTEGER,
    signal_pct        INTEGER,
    noise_floor_dbm   INTEGER,
    snr_db            INTEGER,
    phy_mode          TEXT,
    channel_width_mhz INTEGER,
    mcs_index         INTEGER,
    tx_bitrate_mbps   REAL,
    rx_bitrate_mbps   REAL,
    phy_rate_mbps     REAL,
    ipv4_addresses    TEXT,
    ipv6_addresses    TEXT,
    gateway           TEXT,
    dns_servers       TEXT
);

CREATE INDEX IF NOT EXISTS idx_wifi_samples_interface_ts ON wifi_samples(interface, timestamp);
CREATE INDEX IF NOT EXISTS idx_wifi_samples_ts ON wifi_samples(timestamp);

-- One row per *confirmed* roam (see app/services/roaming_service.py) - a
-- single-tick BSSID flicker never reaches this table, only a change that
-- held for a second consecutive reading. previous_*/new_* capture the
-- topology change itself; gateway_interruption_ms through confidence are
-- filled in later, by the interruption measurement and classification
-- logic (Stage 10) - left NULL here rather than defaulted to 0, since 0ms
-- interruption and "not measured yet" must stay distinguishable.
CREATE TABLE IF NOT EXISTS roam_events (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp                   TEXT NOT NULL,
    interface                   TEXT NOT NULL,
    ssid                        TEXT,

    previous_bssid              TEXT,
    new_bssid                   TEXT,
    previous_frequency_mhz      INTEGER,
    new_frequency_mhz           INTEGER,
    previous_channel            INTEGER,
    new_channel                 INTEGER,
    previous_band               TEXT,
    new_band                    TEXT,
    previous_phy_mode           TEXT,
    new_phy_mode                TEXT,
    previous_channel_width_mhz  INTEGER,
    new_channel_width_mhz       INTEGER,
    previous_mcs_index          INTEGER,
    new_mcs_index               INTEGER,
    previous_rssi_dbm           INTEGER,
    new_rssi_dbm                INTEGER,

    ip_changed                  INTEGER NOT NULL DEFAULT 0,
    previous_ipv4               TEXT,
    new_ipv4                    TEXT,

    -- Stage 10 fields.
    gateway_interruption_ms     REAL,
    internet_interruption_ms    REAL,
    packet_loss_during_pct      REAL,
    peak_latency_ms             REAL,
    success                     INTEGER,
    classification              TEXT,
    confidence                  TEXT
);

CREATE INDEX IF NOT EXISTS idx_roam_events_interface_ts ON roam_events(interface, timestamp);
CREATE INDEX IF NOT EXISTS idx_roam_events_ts ON roam_events(timestamp);

-- A walk-test session: a user-initiated, named recording run (typically
-- physically walking through a site) that samples WiFi + latency far more
-- densely (500ms default) than the background monitoring loop. Does not
-- require internet connectivity - target_ids is a JSON array and may be
-- empty; latency/packet_loss/reachable on each sample are then simply None.
CREATE TABLE IF NOT EXISTS walk_tests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    site        TEXT,
    area        TEXT,
    interface   TEXT NOT NULL,
    target_ids  TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'recording',
    started_at  TEXT NOT NULL,
    ended_at    TEXT
);

CREATE TABLE IF NOT EXISTS walk_test_samples (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    walk_test_id      INTEGER NOT NULL REFERENCES walk_tests(id) ON DELETE CASCADE,
    timestamp         TEXT NOT NULL,
    interface_state   TEXT,
    ssid              TEXT,
    bssid             TEXT,
    frequency_mhz     INTEGER,
    channel           INTEGER,
    band              TEXT,
    rssi_dbm          INTEGER,
    signal_pct        INTEGER,
    noise_floor_dbm   INTEGER,
    snr_db            INTEGER,
    phy_mode          TEXT,
    channel_width_mhz INTEGER,
    mcs_index         INTEGER,
    tx_bitrate_mbps   REAL,
    rx_bitrate_mbps   REAL,
    phy_rate_mbps     REAL,
    -- Best-effort connectivity snapshot against the session's target_ids;
    -- all three stay NULL when no targets were selected for this session.
    latency_ms        REAL,
    packet_loss_pct   REAL,
    reachable         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_walk_test_samples_test_ts ON walk_test_samples(walk_test_id, timestamp);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
