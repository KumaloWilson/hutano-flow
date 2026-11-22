"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorText, formatClock } from "@/lib/api";
import type { QueueEntry, ServicePoint, User, Visit } from "@/lib/types";
import { canOperateService } from "@/lib/permissions";
import { choices, reasonField, serviceChoices, useActionDialog } from "./ActionDialog";
import { EpisodeNotebook } from "./PatientWorkspace";
import { Icon } from "./ui/Icon";
import { Elapsed, Empty, StatusChip, Ticket, Urgency, Wait } from "./ui/primitives";
import type { Notice } from "./FrontDesk";

const hasAny = (user: User, roles: string[]) => user.roles.some((role) => roles.includes(role));
const canCall = (user: User, type: string) => (type === "pharmacy" && user.roles.includes("PHARMACY")) ||
  (["consultation", "laboratory", "discharge"].includes(type) && hasAny(user, ["CLINICIAN", "SERVICE_PROVIDER"])) ||
  (type === "triage" && hasAny(user, ["CLINICIAN", "TRIAGE_NURSE"]));

type RoomChoice = { id: string; name: string; staff_name: string | null; available: boolean; explanation: string };
type RoomProposal = { id: string; options: RoomChoice[]; recommended_room_id: string | null };
const NO_ROOMS = /Configure rooms and shifts/;

/** Call a patient. Where the service uses staffed rooms, the same dialog chooses the room:
 *  the server reserves room and staff and calls atomically; queue order never changes. */
function useCallAction(onDone: () => Promise<void>, setNotice: (n: Notice) => void, after?: () => Promise<void>) {
  const ask = useActionDialog();
  return async (entry: QueueEntry, confirm = true) => {
    let proposal: RoomProposal | null = null;
    try {
      proposal = await api<RoomProposal>("/api/v1/operations/proposals", { method: "POST", body: JSON.stringify({ queue_entry_id: entry.queue_entry_id, version: entry.version }) });
    } catch (e) {
      if (!NO_ROOMS.test(errorText(e, ""))) { setNotice({ kind: "error", text: errorText(e, "Call failed") }); return; }
    }
    try {
      if (proposal) {
        const free = proposal.options.filter((o) => o.available);
        if (!free.length) {
          setNotice({ kind: "error", text: `No staffed room is free for ${entry.public_token}. ${proposal.options.map((o) => `${o.name}: ${o.explanation}`).join(" · ")}. Complete or pause a current service, or check Staff & rooms.` });
          return;
        }
        const answer = await ask({
          title: `Call ${entry.public_token} to a room`,
          description: "Reserves the room and its on-duty staff member and calls the patient in one step. Queue order is unchanged.",
          fields: [
            { name: "room", label: "Room", type: "select", required: true, value: proposal.recommended_room_id || free[0].id, options: free.map((o) => ({ value: o.id, label: `${o.name} · ${o.staff_name ?? "on duty"}` })) },
            { ...reasonField, value: "Next patient called to an available staffed room" },
          ],
          submit: "Assign room & call",
        });
        if (!answer) return;
        const called = await api<{ room: string }>(`/api/v1/operations/proposals/${proposal.id}/approve`, { method: "POST", body: JSON.stringify({ room_id: answer.room, reason: answer.reason }) });
        await Promise.all([after?.(), onDone()]);
        setNotice({ kind: "success", text: `${entry.public_token} called to ${called.room}.` });
        return;
      }
      if (confirm && !await ask({ title: `Call ${entry.public_token} next?`, description: "The number appears on the waiting-room display." })) return;
      await api(`/api/v1/queue/${entry.queue_entry_id}/call`, { method: "POST", body: JSON.stringify({ version: entry.version }) });
      await Promise.all([after?.(), onDone()]);
      setNotice({ kind: "success", text: `${entry.public_token} called atomically.` });
    } catch (e) { setNotice({ kind: "error", text: errorText(e, "Call failed") }); }
  };
}

function Flags({ entry }: { entry: QueueEntry }) {
  return <>
    {entry.manual_pin && <span className="badge pinned">Override</span>}
    {entry.deferred_until && <span className="badge deferred">Missed call · back {formatClock(entry.deferred_until)}</span>}
    {!entry.deferred_until && (entry.missed_calls ?? 0) > 0 && <span className="badge attention">Missed {entry.missed_calls}×</span>}
    {entry.carried_over && <span className="badge carried">From an earlier day</span>}
    {entry.review_recommended && <span className="badge attention" title={`${entry.minutes_since_review} min since last clinician review; ${entry.overtaken_by} later arrival(s) seen first`}>Review suggested</span>}
    {!entry.review_recommended && (entry.overtaken_by ?? 0) > 0 && <span className="badge plain" title="Later arrivals seen first while this patient waited">Overtaken {entry.overtaken_by}×</span>}
  </>;
}

export function Queues({ points, visits, user, onDone, setNotice, navigate }: { points: ServicePoint[]; visits: Visit[]; user: User; onDone: () => Promise<void>; setNotice: (x: Notice) => void; navigate: (tab: string, patientId?: string) => void }) {
  const ask = useActionDialog();
  const [queues, setQueues] = useState<Record<string, QueueEntry[]>>({});
  const [filter, setFilter] = useState(""), [service, setService] = useState(""), [longOnly, setLongOnly] = useState(false), [loadError, setLoadError] = useState("");
  const byVisit = useMemo(() => new Map(visits.map((v) => [v.id, v])), [visits]);
  const shown = points.filter((p) => !["registration", "discharge"].includes(p.type) && (!service || p.id === service));
  const visible = (entry: QueueEntry) => (!longOnly || entry.long_wait_warning) && `${entry.public_token} ${byVisit.get(entry.visit_id)?.patient?.pseudonym || ""}`.toLowerCase().includes(filter.toLowerCase());
  const load = useCallback(async () => {
    const pairs = await Promise.all(points.map(async (point) => [point.id, (await api<{ entries: QueueEntry[] }>(`/api/v1/service-points/${point.id}/queue`)).entries] as const));
    setQueues(Object.fromEntries(pairs)); setLoadError("");
  }, [points]);
  useEffect(() => { load().catch((e) => setLoadError(e.message)); }, [load]);
  const call = useCallAction(onDone, setNotice, load);
  async function review(entry: QueueEntry) {
    const visit = byVisit.get(entry.visit_id);
    if (!visit) return;
    const response = await ask({ title: `Review ${entry.public_token}`, description: `Waiting ${entry.minutes_since_review} min since the last clinician review; ${entry.overtaken_by} later arrival(s) seen first. Confirm the category to keep their place, or change it. The system never changes it for you.`,
      submit: "Record review", fields: [{ name: "urgency", label: "Confirmed category", type: "select", value: entry.confirmed_urgency || "P3", options: choices(["P1", "P2", "P3", "P4", "P5"]) }, { ...reasonField, value: "Reviewed after a long wait" }] });
    if (!response) return;
    try {
      await api(`/api/v1/visits/${visit.id}/reassess`, { method: "POST", body: JSON.stringify({ version: visit.version, configured_urgency: response.urgency, reason: response.reason, action: "REASSESS" }) });
      await Promise.all([load(), onDone()]);
      setNotice({ kind: "success", text: `${entry.public_token} reviewed: ${response.urgency === entry.confirmed_urgency ? "category confirmed" : `category changed to ${response.urgency}`}.` });
    } catch (e) { setNotice({ kind: "error", text: errorText(e, "Review failed") }); }
  }
  async function pin(entry: QueueEntry) {
    const response = await ask({ title: "Clinician queue override", description: "Moves this patient to a specific place. Recorded with your reason; releases when they are called.", fields: [{ name: "rank", label: "New rank", type: "number", value: "1", min: 1, required: true }, reasonField] });
    if (!response) return;
    try {
      await api("/api/v1/queue/override", { method: "POST", body: JSON.stringify({ queue_entry_id: entry.queue_entry_id, new_rank: Number(response.rank), reason_code: "CLINICAL_JUDGEMENT", note: response.reason, version: entry.version }) });
      await load(); setNotice({ kind: "success", text: "Override pinned and audited." });
    } catch (e) { setNotice({ kind: "error", text: errorText(e, "Override failed") }); }
  }

  return <>
    <article className="panel">
      <div className="queue-toolbar">
        <label>Filter queue<input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Ticket or authorised patient name" /></label>
        <label style={{ flex: "0 1 220px" }}>Service<select value={service} onChange={(e) => setService(e.target.value)}><option value="">All services</option>{points.filter((p) => !["registration", "discharge"].includes(p.type)).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label className="checkbox"><input type="checkbox" checked={longOnly} onChange={(e) => setLongOnly(e.target.checked)} />Long waits only</label>
        {hasAny(user, ["ADMIN", "CLINICIAN", "TRIAGE_NURSE", "SERVICE_PROVIDER", "PHARMACY"]) && <button className="secondary" onClick={() => navigate("operations")}><Icon name="rooms" />Staffed rooms</button>}
      </div>
      <small style={{ display: "block", marginTop: 10 }}>Filtering only hides rows. It never changes the server&apos;s order or who can be called.</small>
      {loadError && <p role="alert" className="error">{loadError}</p>}
    </article>
    <section className="queue-grid spaced">{shown.map((point) => {
      const all = queues[point.id] || [];
      const rows = all.filter(visible);
      const paused = point.capacity === 0 || point.outage_state === "UNAVAILABLE";
      return <article className="panel queue-panel" key={point.id}>
        <div className="panel-head">
          <div><h2>{point.name}</h2><div className="queue-meter"><span>{all.length} waiting</span><span aria-hidden="true">·</span><span>capacity {point.capacity}</span></div></div>
          <StatusChip status={paused ? "UNAVAILABLE" : point.outage_state} label={paused ? "Paused" : point.outage_state === "AVAILABLE" ? "Open" : undefined} />
        </div>
        {rows.length ? <ol className="queue-list">{rows.map((entry) => {
          const visit = byVisit.get(entry.visit_id);
          const head = entry.recommended_order === 1 && !entry.deferred_until;
          return <li key={entry.queue_entry_id} data-visit-id={entry.visit_id} className={`${head ? "head" : ""}${entry.deferred_until ? " deferred" : ""}`}>
            <span className="rank" aria-label={`Position ${entry.recommended_order}`}>{entry.recommended_order}</span>
            <div className="queue-person">
              <strong><Ticket token={entry.public_token} />{visit?.patient?.pseudonym && <span className="who">{visit.patient.pseudonym}</span>}<Urgency level={entry.confirmed_urgency} /><Flags entry={entry} /></strong>
              <span className="cluster" style={{ gap: 10 }}><Wait minutes={entry.waiting_minutes} long={entry.long_wait_warning} />{entry.long_wait_warning && <em>Long wait — stays flagged</em>}</span>
              <details className="why"><summary>Why this position</summary><ul>{entry.explanations.map((line) => <li key={line}>{line}</li>)}</ul></details>
            </div>
            <div className="row-actions">
              {canCall(user, point.type) && <button className={head ? "primary small" : "secondary small"} disabled={paused} onClick={() => call(entry)}>Call</button>}
              {hasAny(user, ["CLINICIAN", "TRIAGE_NURSE"]) && entry.review_recommended && <button className="attention small" onClick={() => review(entry)}>Review</button>}
              {hasAny(user, ["CLINICIAN", "TRIAGE_NURSE"]) && <button className="secondary small" onClick={() => pin(entry)}>Override</button>}
              {hasAny(user, ["RECEPTIONIST", "TRIAGE_NURSE", "CLINICIAN"]) && visit?.patient && <button className="ghost small" onClick={() => navigate("patients", visit.patient!.id)}>Record</button>}
            </div>
          </li>;
        })}</ol> : <Empty icon={paused ? "pause" : "check"} text={paused ? "Queue paused while capacity is zero. Nobody is removed." : all.length ? "No rows match the filter." : "No eligible waiting visits."} />}
      </article>;
    })}</section>
  </>;
}

export function ServiceConsole({ visits, points, user, onDone, setNotice }: { visits: Visit[]; points: ServicePoint[]; user: User; onDone: () => Promise<void>; setNotice: (x: Notice) => void }) {
  const ask = useActionDialog();
  const mine = points.filter((p) => canOperateService(user, p.type) && p.type !== "registration");
  const [heads, setHeads] = useState<Record<string, QueueEntry[]>>({});
  const loadHeads = useCallback(async () => {
    const pairs = await Promise.all(mine.map(async (p) => [p.id, (await api<{ entries: QueueEntry[] }>(`/api/v1/service-points/${p.id}/queue`)).entries] as const));
    setHeads(Object.fromEntries(pairs));
  }, [mine.map((p) => p.id).join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadHeads().catch(() => undefined); }, [loadHeads, visits]);
  const call = useCallAction(onDone, setNotice, loadHeads);
  const episodes = visits.flatMap((visit) => visit.episodes.map((episode) => ({ visit, episode })))
    .filter(({ episode }) => canOperateService(user, episode.service_type) && ["CALLED", "IN_SERVICE", "PAUSED"].includes(episode.status));

  const run = async (path: string, body: object, success: string) => {
    try { await api(path, { method: "POST", body: JSON.stringify(body) }); await Promise.all([onDone(), loadHeads()]); setNotice({ kind: "success", text: success }); }
    catch (e) { setNotice({ kind: "error", text: errorText(e) }); }
  };
  const start = (id: string, version: number) => run(`/api/v1/episodes/${id}/start`, { version }, "Service started.");
  async function complete(id: string, version: number, current: string) {
    const routes = points.find((p) => p.type === current)?.allowed_routes || [];
    const response = await ask({ title: "Complete service & route", description: "The completed stage is preserved. Returning from laboratory creates a new consultation episode.", fields: [{ name: "next", label: "Next service", type: "select", value: current === "consultation" && routes.includes("pharmacy") ? "pharmacy" : "", options: [{ value: "", label: "Finish visit" }, ...serviceChoices(routes)] }, { name: "note", label: "Service completion note", type: "textarea", value: "", max: 500 }] });
    if (!response) return;
    await run(`/api/v1/episodes/${id}/complete`, { version, next_service_type: response.next || null, operational_note: response.note || null }, response.next ? `Service completed and routed to ${response.next}.` : "Service completed and visit closed.");
  }
  async function pauseOrResume(id: string, version: number, action: "PAUSE" | "RESUME") {
    const response = await ask({ title: action === "PAUSE" ? "Pause service" : "Resume service", fields: [{ ...reasonField, max: 240 }] });
    if (!response) return;
    await run(`/api/v1/episodes/${id}/${action === "RESUME" ? "start" : "state"}`, action === "RESUME" ? { version, reason: response.reason } : { action, version, reason: response.reason }, action === "PAUSE" ? "Service paused; room reservation retained." : "Service resumed.");
  }
  const recall = (id: string, version: number, token: string) => run(`/api/v1/episodes/${id}/state`, { action: "RECALL", version, reason: "Called again on the display" }, `${token} called again on the display.`);
  async function notHere(id: string, version: number, token: string) {
    const response = await ask({ title: `${token} did not come`, description: "They keep their place but others are called first until the grace period ends. After three missed calls, record a no-show instead.", submit: "Keep place & call others", fields: [{ name: "minutes", label: "Grace period (minutes)", type: "number", value: "10", min: 1, max: 60, required: true }, { ...reasonField, value: "Not in the waiting area when called" }] });
    if (!response) return;
    await run(`/api/v1/episodes/${id}/state`, { action: "DEFER", version, reason: response.reason, defer_minutes: Number(response.minutes) }, `${token} keeps their place; calling others for ${response.minutes} minutes.`);
  }

  return <section className="service-layout">
    <article className="panel">
      <div className="panel-head"><div><h2>With you now</h2><p className="muted">Called, in service or paused at your service points.</p></div><span className="count">{episodes.length}</span></div>
      {episodes.length ? <div className="service-cards">{episodes.map(({ visit, episode }) => <div key={episode.id} className="service-card" data-visit-id={visit.id} data-state={episode.status}>
        <div>
          <div className="cluster"><Ticket token={visit.public_token} /><StatusChip status={episode.status} />{(episode.recall_count ?? 0) > 0 && <span className="badge recalled">Called {(episode.recall_count ?? 0) + 1}×</span>}</div>
          <h3>{episode.service_point}</h3>
          <p>{visit.patient?.pseudonym || "Synthetic patient"}</p>
          <small>{episode.status === "CALLED" ? `Called ${formatClock(episode.called_at)}` : `Started ${formatClock(episode.started_at)}`}</small>
        </div>
        <div style={{ textAlign: "right" }}><small>{episode.status === "CALLED" ? "Waiting at door" : "In room"}</small><div className="elapsed"><Elapsed since={episode.status === "CALLED" ? episode.called_at : episode.started_at} /></div></div>
        <div className="row-actions">
          {episode.status === "CALLED" && <>
            <button className="primary" onClick={() => start(episode.id, episode.version)}><Icon name="play" size={14} />Start service</button>
            <button className="secondary" onClick={() => recall(episode.id, episode.version, visit.public_token)}><Icon name="megaphone" />Call again</button>
            <button className="secondary" onClick={() => notHere(episode.id, episode.version, visit.public_token)}><Icon name="hourglass" />Not here</button>
          </>}
          {episode.status === "IN_SERVICE" && <>
            <button className="primary" onClick={() => complete(episode.id, episode.version, episode.service_type)}><Icon name="check" />Complete & route</button>
            <button className="secondary" onClick={() => pauseOrResume(episode.id, episode.version, "PAUSE")}><Icon name="pause" />Pause service</button>
          </>}
          {episode.status === "PAUSED" && <button className="primary" onClick={() => pauseOrResume(episode.id, episode.version, "RESUME")}><Icon name="play" size={14} />Resume service</button>}
        </div>
        <EpisodeNotebook episodeId={episode.id} />
      </div>)}</div> : <Empty icon="door" text="Nobody is with you. Call the next patient from the panel alongside." />}
    </article>
    <div className="stack">
      {mine.map((point) => {
        const entries = heads[point.id] || [];
        const next = entries.find((e) => !e.deferred_until) || entries[0];
        const paused = point.capacity === 0 || point.outage_state === "UNAVAILABLE";
        return <article className="panel" key={point.id}>
          <div className="panel-head" style={{ marginBottom: 10 }}><div><h2>{point.name}</h2><p className="muted">{entries.length} waiting</p></div>{paused && <StatusChip status="UNAVAILABLE" label="Paused" />}</div>
          {next && canCall(user, point.type) ? <div className="call-next">
            <div className="split"><div className="cluster"><Ticket token={next.public_token} large /><Urgency level={next.confirmed_urgency} /></div><Wait minutes={next.waiting_minutes} long={next.long_wait_warning} /></div>
            <p>{next.explanations[0]}</p>
            <button className="primary large" disabled={paused} onClick={() => call(next)}><Icon name="megaphone" />Call next</button>
          </div> : <Empty text={paused ? "Paused while capacity is zero." : "Queue is clear."} />}
          {entries.length > 1 && <div className="up-next">{entries.slice(1, 5).map((entry) => <div className="next-row" key={entry.queue_entry_id}>
            <span className="rank">{entry.recommended_order}</span><Ticket token={entry.public_token} /><div><Flags entry={entry} /></div><Wait minutes={entry.waiting_minutes} long={entry.long_wait_warning} />
          </div>)}</div>}
        </article>;
      })}
    </div>
  </section>;
}
