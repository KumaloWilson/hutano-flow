"use client";
import { formatTime } from "@/lib/api";
import type { User, Visit } from "@/lib/types";
import { Icon } from "./ui/Icon";
import { Empty, Rail } from "./ui/primitives";

export type ClinicSnapshot = {
  facility: { name: string; timezone: string; research_mode: boolean }; generated_at: string; day: string;
  counts: Record<string, number>;
  services: { id: string; name: string; type: string; waiting: number; in_progress: number; long_waits: number; oldest_wait_minutes: number; capacity: number; availability: string }[];
  hourly_arrivals: { hour: number; arrivals: number }[];
  demonstration: null | { prepared_at: string; stale: boolean; fictional: boolean; version: string; history_method: string; warning: string;
    cases: { patient_id: string; visit_id: string; patient_label: string; public_token: string; story: string; status: string; stage: string }[];
    jobs?: { id: string; type: string; status: string; error: string | null }[];
    models?: { version: string; status: string; active: boolean }[] };
};
export type Navigate = (tab: string, patientId?: string) => void;
const human = (s: string) => s.replaceAll("_", " ").toLowerCase();

export function ClinicOverview({ snapshot, user, visits, navigate, tabs }: { snapshot: ClinicSnapshot | null; user: User; visits: Visit[]; navigate: Navigate; tabs: string[] }) {
  if (!snapshot) return <article className="panel"><p role="status">Loading the clinic snapshot…</p></article>;
  const c = snapshot.counts;
  const active = visits.filter(v => !["COMPLETED", "CANCELLED", "LEFT_WITHOUT_SERVICE"].includes(v.status));
  const flow = snapshot.services.filter(s => s.type !== "discharge");
  const attention = [
    ...snapshot.services.filter(s => s.long_waits > 0).map(s => ({ key: `lw-${s.id}`, title: `${s.long_waits} long wait${s.long_waits === 1 ? "" : "s"} at ${s.name}`, note: `Oldest has waited ${s.oldest_wait_minutes} minutes.`, tab: "queues", info: false })),
    ...snapshot.services.filter(s => s.availability !== "AVAILABLE").map(s => ({ key: `av-${s.id}`, title: `${s.name} is ${human(s.availability)}`, note: `${s.waiting} still waiting; nobody is removed from the queue.`, tab: "admin", info: false })),
    ...(c.escalations ? [{ key: "esc", title: `${c.escalations} escalation alert${c.escalations === 1 ? "" : "s"}`, note: "A clinician must resolve these before routine queueing.", tab: "journeys", info: false }] : []),
    ...active.filter(v => v.episodes.some(e => (e.missed_calls ?? 0) > 0 && e.status === "WAITING")).slice(0, 3).map(v => ({ key: `mc-${v.id}`, title: `${v.public_token} missed a call`, note: "Kept their place; callable again shortly.", tab: "queues", info: true })),
  ].filter(item => tabs.includes(item.tab));
  const actions = [["registration", "Register an arrival", "New visit and printed queue ticket"], ["triage", "Assess waiting patients", "Confirm a priority category"], ["service", "Call the next patient", "Start, complete or route care"], ["queues", "See every queue", "Order, waits and overrides"], ["analytics", "Review clinic activity", "Waits and throughput by date"], ["dayclose", "Close the day", "Clear unseen visits at closing"]].filter(a => tabs.includes(a[0]));
  return <>
    <section className="welcome-card"><div><h2>A clear view of today’s clinic.</h2><p>Welcome, {user.display_name} · {snapshot.facility.name} · {snapshot.day}</p></div><span className="badge synthetic">Fictional demonstration</span></section>
    <section className="metric-grid"><Stat label="Arrivals today" value={c.arrivals_today} note="Facility-local date"/><Stat label="Waiting now" value={c.waiting} note={`${c.in_progress} called, in service or paused`}/><Stat label="Completed today" value={c.completed_today} note="Visits with a recorded completion"/><Stat label="Needs attention" value={c.long_waits+c.escalations} note={`${c.long_waits} long wait${c.long_waits===1?"":"s"} · ${c.escalations} escalation${c.escalations===1?"":"s"}`} warning={c.long_waits+c.escalations>0}/></section>
    <article className="panel spaced">
      <div className="panel-head"><div><h2>Flow through the clinic</h2><p className="muted">Waiting at each stage right now.</p></div>{tabs.includes("queues")&&<button className="secondary small" onClick={() => navigate("queues")}>Open live queues</button>}</div>
      <Rail large label="Patients waiting at each stage" stops={flow.map(s => ({ label: s.name, value: s.waiting, note: s.availability !== "AVAILABLE" ? human(s.availability) : s.long_waits ? `${s.long_waits} long` : s.waiting ? `oldest ${s.oldest_wait_minutes}m` : `${s.in_progress} in progress`, state: s.availability !== "AVAILABLE" || s.long_waits ? "alert" : s.waiting ? "busy" : "todo" }))} />
    </article>
    {snapshot.demonstration?.stale && <p className="callout caution">This rehearsal was prepared {formatTime(snapshot.demonstration.prepared_at)}. Queue ages are live and staff shifts may have ended. See Demo guide to prepare a fresh rehearsal.</p>}
    <section className="two-column spaced">
      <article className="panel"><div className="panel-head"><div><h2>Needs attention</h2><p className="muted">Long waits, paused services and escalations.</p></div><span className="count">{attention.length}</span></div>
        {attention.length ? <div className="attention-list">{attention.map(item => <div key={item.key} className={`attention-item${item.info ? " info" : ""}`}><Icon name={item.info ? "hourglass" : "alert"} /><div><strong>{item.title}</strong><small>{item.note}</small></div><button className="secondary small" onClick={() => navigate(item.tab)}>Open</button></div>)}</div> : <Empty text="Nothing needs attention right now." />}
        {actions.length > 0 && <div className="quick-actions">{actions.map(([tab,title,description]) => <button className="quick-action" key={tab} onClick={() => navigate(tab)}><strong>{title}<span aria-hidden="true">→</span></strong><small>{description}</small></button>)}</div>}
      </article>
      <article className="panel"><div className="panel-head"><div><h2>{active.length ? "Journeys in progress" : "Explore the clinic story"}</h2><p className="muted">{c.active_visits} active visits</p></div></div>
        {active.slice(0,7).map(v => <div className="clinic-visit" key={v.id}><span className="token">{v.public_token}</span><div><strong>{v.patient?.pseudonym||v.episodes.at(-1)?.service_point||"Private visit"}</strong><small>{v.episodes.at(-1)?.service_point} · {human(v.status)}</small></div>{tabs.includes("patients")&&v.patient&&<button className="ghost small" onClick={() => navigate("patients",v.patient!.id)}>Open record</button>}</div>)}
        {!active.length&&<p className="muted">Explore saved clinic history, compare staffing scenarios and inspect the methods behind advisory models.</p>}
        <button className="secondary wide" style={{ marginTop: 14 }} onClick={() => navigate("demo")}>Open guided demonstration</button>
      </article>
    </section>
  </>;
}

function Stat({ label,value,note,warning=false }:{label:string;value:number;note:string;warning?:boolean}) {
  return <article className={`metric ${warning?"metric-alert":""}`}><p>{label}</p><strong>{value}</strong><small>{note}</small></article>;
}

export function DemoGuide({ snapshot,navigate,tabs }: { snapshot: ClinicSnapshot|null;navigate:Navigate;tabs:string[] }) {
  const demo=snapshot?.demonstration;
  const tasks=[
    ["registration","01","Welcome a walk-in","Find an existing fictional patient or register a new one. Choose the visit type and print the private receipt."],
    ["triage","02","Record a human assessment","Review previous encounters, record observations and explicitly confirm a neutral priority category."],
    ["operations","03","Coordinate staff and rooms","Inspect on-duty staff, breaks and occupied rooms. Approve a room for the current queue head."],
    ["service","04","Complete the journey","Start or resume service, preserve a note and route to laboratory/pharmacy or finish the visit."],
    ["analytics","05","Explain clinic performance","Choose a date range and compare stage waiting, completed journeys and the daily arrival pattern."],
    ["simulation","06","Test a queue scenario","Compare the same arrivals under FCFS, urgency-first and hybrid policies. Keep losses and uncertainty visible."],
    ["experiments","07","Explore staffing alternatives","Run an immutable finite-day scenario, inspect replay and export paired comparisons."],
    ["workbench","08","Inspect the research evidence","Review model uncertainty, independent synthetic-case assessment and forecast-informed planning."],
  ].filter(t=>tabs.includes(t[0]));
  return <><article className="panel"><h2>{snapshot?.facility.name||"Hutano Flow"}</h2><p>Fictional people, believable service histories and actions that update the database. All clinical categories remain human-confirmed during interactive use.</p>{demo?<><div className="demo-provenance"><span className="badge synthetic">All records fictional</span><span>Prepared {formatTime(demo.prepared_at)}</span><span>{demo.version}</span></div><p>{demo.history_method}</p><details><summary>Preparation and research boundaries</summary><p>{demo.warning}</p><p>Prepare again with <code>docker compose exec api python -m app.cli showcase</code>. To start a fresh rehearsal, add <code>--fresh</code>; only unfinished scripted cases are retired. Independently entered records and the original workspace are retained.</p></details></>:<p className="callout">This is the original workspace. The separate Hutano Community Clinic uses the <strong>@showcase.hutano.test</strong> demo accounts. Preparation instructions are in the project README.</p>}</article>
    <section className="demo-task-grid spaced">{tasks.map(([tab,step,title,description])=><article className="panel" key={tab}><span className="demo-step">{step}</span><h3>{title}</h3><p>{description}</p><button className="secondary" onClick={()=>navigate(tab)}>Open {title.toLowerCase()}</button></article>)}</section>
    {!!demo?.cases.length&&<article className="panel spaced"><h2>Patients in this rehearsal</h2><p>Initial stories are scripted. Current states below reflect subsequent staff actions.</p><div className="table-wrap"><table><thead><tr><th>Patient</th><th>Scenario</th><th>Current stage</th><th>State</th><th>Action</th></tr></thead><tbody>{demo.cases.map(c=><tr key={c.visit_id}><td><strong>{c.patient_label}</strong><small>{c.public_token}</small></td><td>{c.story}</td><td>{c.stage}</td><td><span className="badge">{human(c.status)}</span></td><td>{tabs.includes("patients")?<button className="secondary small" onClick={()=>navigate("patients",c.patient_id)}>Open record</button>:<button className="secondary small" onClick={()=>navigate("journeys")}>View journeys</button>}</td></tr>)}</tbody></table></div></article>}
    {!!demo?.jobs?.length&&<article className="panel spaced"><h2>Computed research preparation</h2><p>These are real worker jobs. Training does not activate or clinically validate an advisory model.</p>{demo.jobs.map(j=><div className="clinic-stage" key={j.id}><strong>{human(j.type)}</strong><span className="badge">{human(j.status)}</span>{j.error&&<small>{j.error}</small>}</div>)}</article>}
  </>;
}
