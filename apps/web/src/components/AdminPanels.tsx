"use client";
import { FormEvent, Fragment, useCallback, useEffect, useState } from "react";
import { API_URL, api, errorText, formatClock, formatTime } from "@/lib/api";
import type { ServicePoint, User } from "@/lib/types";
import { choices, reasonField, useActionDialog } from "./ActionDialog";
import { Icon } from "./ui/Icon";
import { Empty, Loading, StatusChip } from "./ui/primitives";
import { QrCode } from "./ui/QrCode";
import type { Notice } from "./FrontDesk";

export function ServicePoints({ points, user, onDone, setNotice }: { points: ServicePoint[]; user: User; onDone: () => Promise<void>; setNotice: (x: Notice) => void }) {
  const ask = useActionDialog();
  async function update(point: ServicePoint) {
    const response = await ask({ title: `Availability: ${point.name}`, description: "Capacity zero pauses ordinary calls. Waiting patients are never removed.", fields: [{ name: "capacity", label: "Capacity", type: "number", value: String(point.capacity), min: 0, max: 20, required: true }, reasonField] });
    if (!response) return;
    const capacity = Number(response.capacity);
    try {
      await api(`/api/v1/service-points/${point.id}/availability`, { method: "POST", body: JSON.stringify({ capacity, outage_state: capacity === 0 ? "UNAVAILABLE" : "AVAILABLE", reason: response.reason, version: point.version }) });
      await onDone(); setNotice({ kind: "success", text: `${point.name} availability updated and audited.` });
    } catch (e) { setNotice({ kind: "error", text: errorText(e, "Update failed") }); }
  }
  async function configure(point: ServicePoint) {
    const response = await ask({ title: "Configure routing & hours", fields: [{ name: "name", label: "Service name", value: point.name, required: true }, { name: "open", label: "Opening time", type: "time", value: String(point.operating_hours?.open || "08:00"), required: true }, { name: "close", label: "Closing time", type: "time", value: String(point.operating_hours?.close || "17:00"), required: true }, { name: "routes", label: "Permitted onward services", type: "checks", value: point.allowed_routes.join(","), options: choices(["consultation", "laboratory", "pharmacy", "discharge"]) }, reasonField] });
    if (!response) return;
    try {
      await api(`/api/v1/admin/service-points/${point.id}/configuration`, { method: "POST", body: JSON.stringify({ name: response.name, operating_hours: { open: response.open, close: response.close }, allowed_routes: response.routes ? response.routes.split(",") : [], version: point.version, reason: response.reason }) });
      await onDone(); setNotice({ kind: "success", text: "Service point configuration saved." });
    } catch (e) { setNotice({ kind: "error", text: errorText(e, "Configuration failed") }); }
  }
  return <article className="panel">
    <div className="panel-head"><div><h2>Service points</h2><p className="muted">Every change is audited with a reason.</p></div></div>
    <div className="admin-list">{points.map((point) => <div key={point.id}>
      <div><strong>{point.name}</strong><p className="muted" style={{ fontSize: ".85rem" }}>{point.type} · capacity {point.capacity} · {point.operating_hours?.open}–{point.operating_hours?.close}</p>{point.outage_reason && <small>{point.outage_reason}</small>}</div>
      <StatusChip status={point.outage_state} />
      <button className="secondary small" onClick={() => update(point)}>Change availability</button>
      {user.roles.includes("ADMIN") && <button className="secondary small" onClick={() => configure(point)}>Configure routing & hours</button>}
    </div>)}</div>
  </article>;
}

type Screen = { id: string; label: string; created_at: string; last_seen_at: string | null; revoked_at: string | null; active: boolean };
export function DisplayScreens({ setNotice }: { setNotice: (n: Notice) => void }) {
  const ask = useActionDialog();
  const [screens, setScreens] = useState<Screen[]>([]);
  const [created, setCreated] = useState<{ label: string; link: string } | null>(null);
  const load = useCallback(() => api<Screen[]>("/api/v1/admin/display-screens").then(setScreens), []);
  useEffect(() => { load().catch((e) => setNotice({ kind: "error", text: errorText(e) })); }, [load, setNotice]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formEl = event.currentTarget, label = String(new FormData(formEl).get("label"));
    try {
      const result = await api<Screen & { display_key: string }>("/api/v1/admin/display-screens", { method: "POST", body: JSON.stringify({ label }) });
      setCreated({ label, link: `${window.location.origin}/display#key=${result.display_key}` });
      formEl.reset(); await load();
    } catch (e) { setNotice({ kind: "error", text: errorText(e) }); }
  }
  async function revoke(screen: Screen) {
    if (!await ask({ title: `Revoke “${screen.label}”?`, description: "That screen stops updating immediately. Create a new link to replace it.", submit: "Revoke display" })) return;
    try { await api(`/api/v1/admin/display-screens/${screen.id}/revoke`, { method: "POST", body: "{}" }); await load(); setNotice({ kind: "success", text: "Display revoked." }); }
    catch (e) { setNotice({ kind: "error", text: errorText(e) }); }
  }
  return <article className="panel">
    <div className="panel-head"><div><h2>Waiting-room displays</h2><p className="muted">A TV shows the ticket numbers being called and queue lengths — never names or priority.</p></div></div>
    {created && <div className="callout" style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 120px", gap: 14, alignItems: "center" }}>
      <div><strong>Link for “{created.label}” — shown once</strong><p style={{ margin: "6px 0" }}>Open it on the TV browser (or scan the code with the TV stick). Anyone with this link can view the board.</p>
        <input readOnly value={created.link} className="mono" onFocus={(e) => e.currentTarget.select()} aria-label="Display link" /></div>
      <div className="receipt-qr" style={{ width: 120, height: 120 }}><QrCode value={created.link} label="QR code for the display link" /></div>
    </div>}
    <form onSubmit={create} className="cluster" style={{ alignItems: "end" }}>
      <label style={{ flex: 1 }}>Screen name<input name="label" required minLength={2} maxLength={80} placeholder="e.g. Main waiting area TV" /></label>
      <button className="primary"><Icon name="monitor" />Create display link</button>
    </form>
    {screens.length ? <div className="table-wrap"><table><thead><tr><th>Screen</th><th>Last seen</th><th>Status</th><th /></tr></thead><tbody>{screens.map((s) => <tr key={s.id}>
      <td>{s.label}<small>Created {formatTime(s.created_at)}</small></td>
      <td className="num">{s.last_seen_at ? formatClock(s.last_seen_at) : "Never"}</td>
      <td><StatusChip status={s.active ? (s.last_seen_at && Date.now() - new Date(s.last_seen_at).getTime() < 300_000 ? "ACTIVE" : "UNKNOWN") : "CANCELLED"} label={s.active ? (s.last_seen_at && Date.now() - new Date(s.last_seen_at).getTime() < 300_000 ? "Online" : "Not seen recently") : "Revoked"} /></td>
      <td>{s.active && <button className="danger-outline small" onClick={() => revoke(s)}>Revoke</button>}</td>
    </tr>)}</tbody></table></div> : <Empty icon="monitor" text="No displays yet." />}
  </article>;
}

type Check = { state: string; [key: string]: unknown };
type Health = { status: string; server_time: string; timezone: string; checks: Record<string, Check> };
const TITLES: Record<string, string> = { database: "Database", worker: "Background worker", live_updates: "Live updates", storage: "Storage", backup: "Backups", security: "Accounts & sessions", operations: "Clinic floor", displays: "Displays" };
const LABELS: Record<string, string> = { latency_ms: "Latency (ms)", migration: "Schema version", stale_running: "Stuck jobs", oldest_pending_minutes: "Oldest queued (min)", events_last_hour: "Events last hour", free_percent: "Free space (%)", age_hours: "Age (hours)", encrypted: "Encrypted", completed_at: "Last backup", locked_accounts: "Locked accounts", temporary_passwords: "Temporary passwords", secure_cookies: "Secure cookies (HTTPS)", session_idle_minutes: "Idle sign-out (min)", session_absolute_minutes: "Max session (min)", open_visits: "Open visits", carried_over_waiting: "Waiting from earlier days", previous_day_closed: "Yesterday closed", active: "Active", stale: "Not seen in 5 min", detail: "Note" };
const show = (value: unknown) => typeof value === "boolean" ? (value ? "Yes" : "No") : value == null ? "—" : typeof value === "object" ? Object.entries(value as object).map(([k, v]) => `${k.toLowerCase()} ${v}`).join(", ") || "none" : String(value).includes("T") && !Number.isNaN(Date.parse(String(value))) ? formatTime(String(value)) : String(value);

export function SystemHealth() {
  const [health, setHealth] = useState<Health | null>(null), [error, setError] = useState("");
  const load = useCallback(() => api<Health>("/api/v1/admin/system-health").then((h) => { setHealth(h); setError(""); }).catch((e) => setError(errorText(e))), []);
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);
  if (!health) return error ? <p className="error" role="alert">{error}</p> : <Loading text="Checking system…" />;
  const skew = Math.round((Date.now() - new Date(health.server_time).getTime()) / 1000);
  return <>
    <article className="panel"><div className="split"><div><h2>{health.status === "ok" ? "All systems normal" : "Needs attention"}</h2><p className="muted" style={{ margin: 0 }}>Server time {formatClock(health.server_time)} ({health.timezone}). Refreshes every 30 seconds.</p></div>
      <div className="cluster"><StatusChip status={health.status === "ok" ? "OK" : "ATTENTION"} label={health.status === "ok" ? "Healthy" : "Attention"} /><button className="secondary small" onClick={load}><Icon name="refresh" />Refresh</button></div></div>
      {Math.abs(skew) > 120 && <p className="callout caution">This device&apos;s clock is {Math.abs(Math.round(skew / 60))} minutes {skew > 0 ? "ahead of" : "behind"} the server. Wrong clocks make wait times look wrong — fix the device time.</p>}
    </article>
    <section className="health-grid spaced">{Object.entries(health.checks).map(([key, check]) => <article key={key} className="health-card" data-state={check.state}>
      <header><h3>{TITLES[key] || key}</h3><StatusChip status={check.state === "ok" ? "OK" : check.state === "unknown" ? "UNKNOWN" : "ATTENTION"} label={check.state === "ok" ? "OK" : check.state === "unknown" ? "Unknown" : "Attention"} /></header>
      <dl>{Object.entries(check).filter(([k]) => !["state", "total_bytes", "free_bytes", "snapshot"].includes(k)).map(([k, v]) => <Fragment key={k}><dt>{LABELS[k] || k.replaceAll("_", " ")}</dt><dd>{show(v)}</dd></Fragment>)}</dl>
    </article>)}</section>
  </>;
}

export function FhirExport() {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Harare" }).format(new Date());
  const [from, setFrom] = useState(today), [to, setTo] = useState(today);
  return <article className="panel">
    <h2>Interoperability export</h2>
    <p className="muted">One-way FHIR R4-shaped bundle (Patient, Encounter, Observation) for synthetic records. No names; local code systems; not a certified FHIR interface.</p>
    <div className="cluster" style={{ alignItems: "end" }}>
      <label>From<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
      <label>To<input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></label>
      <a className="button secondary" href={`${API_URL}/api/v1/interop/fhir/export?from_date=${from}&to_date=${to}`} target="_blank" rel="noreferrer"><Icon name="download" />Download bundle</a>
    </div>
  </article>;
}
