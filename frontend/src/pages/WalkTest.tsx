import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Play, Square, Footprints, Download, Trash2 } from "lucide-react";
import { usePolling } from "../hooks/usePolling";
import { useTargets } from "../hooks/useTargets";
import { api, ApiError } from "../services/api";
import { Modal } from "../components/Modal";
import { SignalChart } from "../components/SignalChart";
import { ApSwatch } from "../components/ApTables";
import { LoadingState, EmptyState } from "../components/States";
import { formatTimestamp, formatDuration } from "../services/format";
import { buildApColors, formatDbm, shortBssid } from "../services/signal";
import type { WalkTest as WalkTestSession, WalkTestCreateInput } from "../types";

const inputClass =
  "w-full rounded-control border border-border bg-panel-alt px-3 py-2 text-sm text-text placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent";
const labelClass = "block text-xs font-medium text-muted mb-1";

const DEFAULT_FORM: WalkTestCreateInput = { name: "", site: "", area: "", interface: "", target_ids: [] };

function sessionDurationSeconds(session: WalkTestSession): number {
  const end = session.ended_at ? new Date(session.ended_at).getTime() : Date.now();
  return (end - new Date(session.started_at).getTime()) / 1000;
}

export function WalkTest() {
  const navigate = useNavigate();
  const sessionsFetcher = useCallback(() => api.listWalkTests(), []);
  const { data: sessions, error, loading, refetch } = usePolling(sessionsFetcher, 3000);
  const interfacesFetcher = useCallback(() => api.listWifiInterfaces(), []);
  const { data: interfaces } = usePolling(interfacesFetcher, 30000);
  const { targets } = useTargets();

  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<WalkTestCreateInput>(DEFAULT_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const active = (sessions ?? []).find((s) => s.status === "recording") ?? null;

  const openCreate = () => {
    setForm({ ...DEFAULT_FORM, interface: interfaces?.[0]?.name ?? "" });
    setFormError(null);
    setCreating(true);
  };

  const submitCreate = async () => {
    if (!form.name.trim() || !form.interface) {
      setFormError("Name and interface are required.");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      await api.startWalkTest({
        ...form,
        site: form.site || null,
        area: form.area || null,
      });
      setCreating(false);
      await refetch();
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Could not start the session.");
    } finally {
      setSubmitting(false);
    }
  };

  const stopActive = async () => {
    if (!active) return;
    const stopped = active;
    await api.stopWalkTest(stopped.id);
    await refetch();
    // Stopping is the moment the result becomes useful, so go straight to it.
    navigate(`/walk-test/${stopped.id}`);
  };

  const removeSession = async (session: WalkTestSession) => {
    if (!window.confirm(`Delete "${session.name}" and its ${session.sample_count} samples?`)) return;
    await api.deleteWalkTest(session.id);
    await refetch();
  };

  const toggleTarget = (id: number) => {
    setForm((f) => ({
      ...f,
      target_ids: f.target_ids.includes(id) ? f.target_ids.filter((t) => t !== id) : [...f.target_ids, id],
    }));
  };

  if (loading && !sessions) return <LoadingState label="Loading walk-test sessions…" />;

  return (
    <div className="space-y-5">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Walk Test</h1>
          <p className="text-sm text-muted mt-0.5">
            Walk a site with this device and see where the signal gets weak and which access point you were on.
          </p>
        </div>
        {!active && (
          <button
            onClick={openCreate}
            className="flex items-center gap-1.5 rounded-control bg-accent text-bg text-sm font-medium px-3 py-2 hover:opacity-90 transition-opacity"
          >
            <Play size={15} /> Start session
          </button>
        )}
      </header>

      {error && <div className="text-sm text-offline">{error}</div>}

      <div className="rounded-card border border-border bg-panel p-4">
        <h3 className="text-sm font-medium">How a walk test works</h3>
        <ol className="mt-2 grid gap-3 sm:grid-cols-3 text-sm text-muted">
          <li><span className="text-text font-medium">1. Start.</span> Pick your WiFi interface and start recording. The signal is sampled about twice a second.</li>
          <li><span className="text-text font-medium">2. Walk.</span> Carry this device along your route at a steady pace, pausing at spots you care about. The chart below follows you live.</li>
          <li><span className="text-text font-medium">3. Stop.</span> You get the result: signal along the route coloured by access point, weak spots, AP changes, and a CSV export.</li>
        </ol>
      </div>

      {active && (
        <div className="rounded-card border border-accent bg-panel p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-offline opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-offline" />
            </span>
            <div>
              <p className="text-sm font-medium">
                Recording "{active.name}"{active.site ? ` at ${active.site}` : ""}
              </p>
              <p className="text-xs text-muted mt-0.5">
                {active.sample_count} sample{active.sample_count === 1 ? "" : "s"} ·{" "}
                {formatDuration(sessionDurationSeconds(active))} elapsed · {active.interface}
              </p>
            </div>
          </div>
          <button
            onClick={stopActive}
            className="flex items-center gap-1.5 rounded-control border border-offline text-offline text-sm font-medium px-3 py-2 hover:bg-offline/10 transition-colors"
          >
            <Square size={14} /> Stop
          </button>
        </div>
      )}

      {active && <LiveWalk session={active} />}

      <div className="rounded-card border border-border bg-panel">
        {!sessions || sessions.length === 0 ? (
          <EmptyState
            title="No walk-test sessions yet"
            description="Start a session, walk your route, then stop it to see the signal map for that walk."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted uppercase tracking-wide border-b border-border">
                  <th className="py-2.5 px-4 font-medium">Name</th>
                  <th className="py-2.5 px-4 font-medium">Site / area</th>
                  <th className="py-2.5 px-4 font-medium">Interface</th>
                  <th className="py-2.5 px-4 font-medium">Samples</th>
                  <th className="py-2.5 px-4 font-medium">Started</th>
                  <th className="py-2.5 px-4 font-medium">Status</th>
                  <th className="py-2.5 px-4 font-medium text-right">Result</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr
                    key={s.id}
                    onClick={() => navigate(`/walk-test/${s.id}`)}
                    onKeyDown={(e) => e.key === "Enter" && navigate(`/walk-test/${s.id}`)}
                    tabIndex={0}
                    aria-label={`Open results for ${s.name}`}
                    className="border-b border-border last:border-0 cursor-pointer hover:bg-panel-alt focus:outline-none focus:bg-panel-alt"
                  >
                    <td className="py-2.5 px-4 font-medium flex items-center gap-2">
                      <Footprints size={14} className="text-muted" /> {s.name}
                    </td>
                    <td className="py-2.5 px-4 text-muted">
                      {[s.site, s.area].filter(Boolean).join(" · ") || "—"}
                    </td>
                    <td className="py-2.5 px-4 font-mono text-xs">{s.interface}</td>
                    <td className="py-2.5 px-4 font-mono font-tabular">{s.sample_count}</td>
                    <td className="py-2.5 px-4 text-xs text-muted font-mono">{formatTimestamp(s.started_at)}</td>
                    <td className="py-2.5 px-4">
                      {s.status === "recording" ? (
                        <span className="text-offline font-medium">Recording</span>
                      ) : (
                        <span className="text-muted">Stopped</span>
                      )}
                    </td>
                    <td className="py-2.5 px-4" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-3 text-xs">
                        <button onClick={() => navigate(`/walk-test/${s.id}`)} className="text-accent hover:underline">
                          View results
                        </button>
                        <a href={api.walkTestExportUrl(s.id)} aria-label={`Export ${s.name} as CSV`} title="Export CSV" className="text-muted hover:text-text">
                          <Download size={14} />
                        </a>
                        <button onClick={() => removeSession(s)} aria-label={`Delete ${s.name}`} title="Delete" className="text-muted hover:text-offline">
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {creating && (
        <Modal title="Start walk-test session" onClose={() => setCreating(false)}>
          <div className="space-y-3">
            <div>
              <label className={labelClass}>Name</label>
              <input
                className={inputClass} autoFocus placeholder="e.g. 3rd floor east wing"
                value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelClass}>Site</label>
                <input className={inputClass} value={form.site ?? ""} onChange={(e) => setForm({ ...form, site: e.target.value })} />
              </div>
              <div>
                <label className={labelClass}>Area</label>
                <input className={inputClass} value={form.area ?? ""} onChange={(e) => setForm({ ...form, area: e.target.value })} />
              </div>
            </div>
            <div>
              <label className={labelClass}>Interface</label>
              <select className={inputClass} value={form.interface} onChange={(e) => setForm({ ...form, interface: e.target.value })}>
                <option value="">Select an interface…</option>
                {(interfaces ?? []).map((i) => (
                  <option key={i.name} value={i.name}>{i.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelClass}>Targets to check (optional)</label>
              <div className="space-y-1.5 max-h-32 overflow-y-auto rounded-control border border-border p-2">
                {targets.length === 0 && <p className="text-xs text-muted">No targets configured.</p>}
                {targets.map((t) => (
                  <label key={t.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.target_ids.includes(t.id)} onChange={() => toggleTarget(t.id)} />
                    {t.name}
                  </label>
                ))}
              </div>
            </div>
            {formError && <p className="text-xs text-offline">{formError}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setCreating(false)} className="text-sm px-3 py-2 rounded-control border border-border text-muted hover:text-text">
                Cancel
              </button>
              <button
                onClick={submitCreate} disabled={submitting}
                className="text-sm px-3 py-2 rounded-control bg-accent text-bg font-medium hover:opacity-90 disabled:opacity-50"
              >
                {submitting ? "Starting…" : "Start recording"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

/** Live view while recording: the last two minutes of the walk, so you can see
 *  the signal and the current access point change as you move. */
function LiveWalk({ session }: { session: WalkTestSession }) {
  const fetcher = useCallback(() => api.getWalkTestAnalysis(session.id, { weak_threshold_dbm: -70 }), [session.id]);
  const { data } = usePolling(fetcher, 1500, [session.id]);
  const colors = useMemo(() => (data ? buildApColors(data) : new Map<string | null, string>()), [data]);

  if (!data || data.points.length === 0) {
    return <p className="text-xs text-muted px-1">Waiting for the first readings…</p>;
  }
  const latest = [...data.points].reverse().find((p) => p.connected && p.rssi !== null) ?? null;
  const lastT = new Date(data.points[data.points.length - 1].t).getTime();
  const recent = data.points.filter((p) => new Date(p.t).getTime() >= lastT - 120_000);
  const recentChanges = data.ap_changes.filter((c) => new Date(c.timestamp).getTime() >= lastT - 120_000);

  return (
    <div className="rounded-card border border-border bg-panel p-4" data-testid="live-walk">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <p className="text-sm">
          Now:{" "}
          <span className="font-mono font-tabular font-semibold">{latest ? formatDbm(latest.rssi) : "no signal"}</span>
          {latest?.bssid && (
            <span className="ml-2 inline-flex items-center gap-1.5 text-xs text-muted">
              on <ApSwatch bssid={latest.bssid} colors={colors} /> <span className="font-mono">{shortBssid(latest.bssid)}</span>
              {latest.channel !== null && <> · ch {latest.channel}</>}
            </span>
          )}
        </p>
        <p className="text-xs text-muted">
          {data.summary.ap_change_count} AP change{data.summary.ap_change_count === 1 ? "" : "s"} so far · last 2 minutes shown
        </p>
      </div>
      <SignalChart points={recent} colors={colors} weakThreshold={-70} apChanges={recentChanges} height={200} />
    </div>
  );
}
