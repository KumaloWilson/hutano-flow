"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { API_URL, api, ApiError, formatTime, waitForJob } from "@/lib/api";
import type { QueueEntry, ServicePoint, User, Visit } from "@/lib/types";
import { canOperateService } from "@/lib/permissions";
import { ServiceWorker } from "@/components/ServiceWorker";
import { ActionDialogProvider, useActionDialog, choices, reasonField } from "@/components/ActionDialog";
import { PatientWorkspace, ObservationInputs, HandoverInbox, EpisodeNotebook } from "@/components/PatientWorkspace";
import { OperationsConsole, PredictionPanel } from "@/components/Operations";
import { ExperimentsConsole } from "@/components/Experiments";
import { ResearchWorkbench } from "@/components/ResearchWorkbench";
import { ClinicOverview, DemoGuide, type ClinicSnapshot } from "@/components/ClinicOverview";
import { JourneyConsole, ResearchConsole, AdminConsole, AdvisoryPanel, ReviewPanel, FeedbackPanel, BaselinePanel } from "@/components/Workflows";

type Tab = "home" | "registration" | "triage" | "queues" | "service" | "analytics" | "simulation" | "research" | "admin" | "audit" | "help" | "journeys" | "patients" | "operations" | "experiments" | "workbench" | "demo";
type Notice = { kind: "success" | "error"; text: string } | null;

const labels: Record<Tab, string> = {
  home: "Overview", registration: "Registration", triage: "Triage", queues: "Live queues",
  service: "Service console", analytics: "Analytics", simulation: "Simulation lab",
  research: "AI research", admin: "Facility admin", audit: "Audit log", help: "Help & safety",
  journeys: "Patient journeys",
  patients: "Patient workspace", operations: "Staff & rooms", experiments: "Experiments",
  workbench: "Research workbench", demo: "Demo guide",
};

function hasAny(user: User | null, roles: string[]) {
  return Boolean(user?.roles.some((role) => roles.includes(role)));
}

export default function Dashboard() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [tab, setTab] = useState<Tab>("home");
  const [visits, setVisits] = useState<Visit[]>([]);
  const [points, setPoints] = useState<ServicePoint[]>([]);
  const [notice, setNotice] = useState<Notice>(null);
  const [online, setOnline] = useState(true);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [events, setEvents] = useState(0);
  const [clinic, setClinic] = useState<ClinicSnapshot | null>(null);
  const [requestedPatient, setRequestedPatient] = useState("");
  const refreshing=useRef<Promise<void>|null>(null);
  function navigate(value: string, patientId?: string) {
    if (!(value in labels)) return;
    if (patientId) setRequestedPatient(patientId);
    setTab(value as Tab);
    window.history.replaceState(null, "", `/dashboard?view=${value}`);
  }

  const refresh = useCallback(async () => {
    if(refreshing.current)return refreshing.current;
    const work=(async()=>{try {
      const current = await api<User>("/api/v1/me");
      const canSeeVisits = hasAny(current, ["ADMIN", "RECEPTIONIST", "TRIAGE_NURSE", "CLINICIAN", "SERVICE_PROVIDER", "PHARMACY"]);
      const [visitData, pointData, snapshot] = await Promise.all([canSeeVisits ? api<Visit[]>("/api/v1/visits") : Promise.resolve([]), api<ServicePoint[]>("/api/v1/service-points"), api<ClinicSnapshot>("/api/v1/clinic/snapshot")]);
      setClinic(snapshot);
      setVisits(visitData);
      setPoints(hasAny(current, ["ADMIN", "RECEPTIONIST", "CLINICIAN", "MANAGER", "RESEARCHER"]) ? pointData : pointData.filter((p) => canOperateService(current,p.type) || (current.roles.includes("TRIAGE_NURSE") && p.type === "consultation")));
      setLastSync(new Date());
      setOnline(true);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) router.replace("/");
      else { setOnline(false); setNotice({ kind: "error", text: caught instanceof Error ? caught.message : "Refresh failed" }); }
    }})();
    refreshing.current=work;
    try{await work;}finally{if(refreshing.current===work)refreshing.current=null;}
  }, [router]);

  useEffect(() => {
    api<User>("/api/v1/me").then(setUser).then(refresh).catch(() => router.replace("/"));
    const updateOnline = () => { if (!navigator.onLine) setOnline(false); else refresh(); };
    window.addEventListener("online", updateOnline);
    window.addEventListener("offline", updateOnline);
    return () => { window.removeEventListener("online", updateOnline); window.removeEventListener("offline", updateOnline); };
  }, [refresh, router]);

  useEffect(() => {
    if (!user) return;
    const polling = setInterval(refresh, 5000);
    let refreshTimer:ReturnType<typeof setTimeout>|undefined;
    const changed=()=>{setEvents(value=>value+1);if(!refreshTimer)refreshTimer=setTimeout(()=>{refreshTimer=undefined;refresh();},100);};
    const stream = new EventSource(`${API_URL}/api/v1/events`, { withCredentials: true });
    stream.onmessage = changed;
    const topics = ["visit.created", "visit.state_changed", "episode.queued", "episode.called", "episode.started", "episode.completed", "clinician.override_recorded", "service_point.capacity_changed", "simulation.completed", "queue.rank_changed", "reset"];
    topics.forEach((topic) => stream.addEventListener(topic, changed));
    return () => { stream.close(); clearInterval(polling); if(refreshTimer)clearTimeout(refreshTimer); };
  }, [user, refresh]);

  const tabs = useMemo(() => {
    const result: Tab[] = ["home"];
    if (hasAny(user, ["RECEPTIONIST", "CLINICIAN", "TRIAGE_NURSE"])) result.push("patients");
    if (hasAny(user, ["ADMIN", "MANAGER", "CLINICIAN", "TRIAGE_NURSE", "SERVICE_PROVIDER", "PHARMACY"])) result.push("operations");
    if (hasAny(user, ["ADMIN", "MANAGER", "RESEARCHER"])) result.push("experiments");
    if (hasAny(user, ["ADMIN", "RECEPTIONIST"])) result.push("registration");
    if (hasAny(user, ["TRIAGE_NURSE", "CLINICIAN"])) result.push("triage");
    if (hasAny(user, ["ADMIN", "RECEPTIONIST", "TRIAGE_NURSE", "CLINICIAN", "SERVICE_PROVIDER", "PHARMACY"])) result.push("queues", "journeys");
    if (hasAny(user, ["CLINICIAN", "SERVICE_PROVIDER", "PHARMACY"])) result.push("service");
    if (hasAny(user, ["ADMIN", "MANAGER", "RESEARCHER"])) result.push("analytics", "simulation");
    if (hasAny(user, ["ADMIN", "RESEARCHER"])) result.push("research");
    if (hasAny(user, ["ADMIN", "RESEARCHER", "CLINICIAN", "TRIAGE_NURSE"])) result.push("workbench");
    if (hasAny(user, ["ADMIN", "CLINICIAN", "SERVICE_PROVIDER"])) result.push("admin");
    if (hasAny(user, ["ADMIN", "MANAGER", "RESEARCHER"])) result.push("audit");
    result.push("demo", "help");
    return result;
  }, [user]);

  useEffect(() => {
    const view = new URLSearchParams(window.location.search).get("view") as Tab;
    if (user && view && tabs.includes(view)) setTab(view);
  }, [user, tabs]);

  async function logout() {
    await api("/api/v1/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/");
  }

  if (!user) return <main className="center"><div className="spinner" /><p>Loading secure workspace…</p></main>;

  return (
    <div className="app-shell">
      <ServiceWorker />
      <aside className="sidebar">
        <div className="brand"><span>HF</span><div><strong>Hutano Flow</strong><small>{clinic?.facility.name || "Outpatient workspace"}</small></div></div>
        <nav aria-label="Main navigation">
          {[["Clinic",["home","registration","patients","triage","queues","service","journeys"]],["Operations",["operations","analytics"]],["Research",["simulation","experiments","research","workbench"]],["Workspace",["admin","audit","demo","help"]]].map(([section, items]) => <div className="nav-group" key={String(section)}>{(items as string[]).some(item=>tabs.includes(item as Tab))&&<span className="nav-heading">{String(section)}</span>}{(items as Tab[]).filter(item=>tabs.includes(item)).map(item=><button key={item} aria-current={tab===item?"page":undefined} className={tab === item ? "active" : ""} onClick={() => navigate(item)}>{labels[item]}</button>)}</div>)}
        </nav>
        <div className="sidebar-foot"><div className="avatar">{user.display_name.split(" ").map((x) => x[0]).join("").slice(0, 2)}</div><div><strong>{user.display_name}</strong><small>{user.roles.join(" · ")}</small></div><button onClick={logout} aria-label="Sign out">↗</button></div>
      </aside>
      <main className="workspace">
        <header className="workspace-head">
          <div><p className="eyebrow">{labels[tab]}</p><h1>{labels[tab]}</h1></div>
          <div className="sync"><span className={online ? "dot online" : "dot offline"} />{online ? "Connected" : "Offline — read-only"}<small>Last sync {lastSync?.toLocaleTimeString() || "pending"} · {events} live updates</small></div>
        </header>
        {notice && <div className={`notice ${notice.kind}`} role="status"><span>{notice.text}</span><button onClick={() => setNotice(null)}>×</button></div>}
        {tab === "home" && <ClinicOverview snapshot={clinic} user={user} visits={visits} navigate={navigate} tabs={tabs}/>}
        {tab === "demo" && <DemoGuide snapshot={clinic} navigate={navigate} tabs={tabs}/>}
        <fieldset disabled={!online} className="workspace-actions"><ActionDialogProvider>
        {tab === "patients" && <PatientWorkspace user={user} points={points} refresh={refresh} requestedPatient={requestedPatient}/>}
        {tab === "operations" && <OperationsConsole user={user} points={points} refresh={refresh}/>}
        {tab === "experiments" && <ExperimentsConsole/>}
        {tab === "workbench" && <ResearchWorkbench roles={user.roles}/>}
        {tab === "registration" && <Registration onDone={refresh} setNotice={setNotice} />}
        {tab === "triage" && <Triage visits={visits} onDone={refresh} setNotice={setNotice} />}
        {tab === "queues" && <Queues points={points} visits={visits} user={user} onDone={refresh} setNotice={setNotice} navigate={navigate} />}
        {tab === "journeys" && <JourneyConsole visits={visits} user={user} refresh={refresh} />}
        {tab === "service" && <><ServiceConsole visits={visits} points={points} user={user} onDone={refresh} setNotice={setNotice} /><HandoverInbox/></>}
        {tab === "analytics" && <><Analytics /><PredictionPanel user={user}/></>}
        {tab === "simulation" && <Simulation />}
        {tab === "research" && <><ResearchConsole user={user} /><BaselinePanel /></>}
        {tab === "admin" && <><Admin points={points} user={user} onDone={refresh} setNotice={setNotice} /><AdminConsole user={user} /><ReviewPanel user={user} /></>}
        {tab === "audit" && <Audit />}
        {tab === "help" && <><Help /><ReviewPanel user={user} />{hasAny(user, ["ADMIN", "RESEARCHER", "MANAGER"]) && <FeedbackPanel />}</>}
        </ActionDialogProvider></fieldset>
      </main>
    </div>
  );
}

function Metric({ label, value, note, alert = false }: { label: string; value: number | string; note: string; alert?: boolean }) {
  return <article className={`metric ${alert ? "metric-alert" : ""}`}><p>{label}</p><strong>{value}</strong><small>{note}</small></article>;
}

function VisitTable({ visits }: { visits: Visit[] }) {
  if (!visits.length) return <Empty text="No visits to show yet." />;
  return <div className="table-wrap"><table><thead><tr><th>Token</th><th>Synthetic patient</th><th>State</th><th>Arrived</th><th>Current stage</th></tr></thead><tbody>{visits.map((visit) => <tr key={visit.id}><td><span className="token">{visit.public_token}</span></td><td>{visit.patient?.pseudonym || "Anonymous synthetic"}</td><td><span className={`badge ${visit.status.toLowerCase()}`}>{visit.status.replaceAll("_", " ")}</span></td><td>{formatTime(visit.arrival_at)}</td><td>{visit.episodes.at(-1)?.service_point || "—"}</td></tr>)}</tbody></table></div>;
}

function Registration({ onDone, setNotice }: { onDone: () => Promise<void>; setNotice: (x: Notice) => void }) {
  const [name, setName] = useState("");
  const [ageBand, setAgeBand] = useState("adult");
  const [visitType,setVisitType]=useState("walk_in"),[plannedPharmacy,setPlannedPharmacy]=useState(true);
  const [sex, setSex] = useState("not_recorded");
  const [created, setCreated] = useState<Visit | null>(null);
  const [existing, setExisting] = useState("");
  const [matches, setMatches] = useState<any[]>([]);
  const draft = useRef<{patient?: {id:string}; visit?: Visit}>({});
  async function search() { try { setMatches(await api<any[]>(`/api/v1/patients?q=${encodeURIComponent(name)}`)); } catch(e) { setNotice({kind:"error",text:e instanceof Error?e.message:"Search failed"}); } }
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setCreated(null);
    try {
      const patient = draft.current.patient || (existing ? {id:existing} : await api<{ id: string }>("/api/v1/patients", { method: "POST", body: JSON.stringify({ pseudonym: name || null, age_band: ageBand, sex, synthetic_flag: true }) }));
      draft.current.patient = patient;
      const visit = draft.current.visit || await api<Visit>("/api/v1/visits", { method: "POST", body: JSON.stringify({ patient_id: patient.id, visit_type: visitType, planned_services: ["triage", "consultation", ...(plannedPharmacy?["pharmacy"]:[])] }) });
      draft.current.visit = visit;
      const registered = await api<{ version: number }>(`/api/v1/visits/${visit.id}/register`, { method: "POST", body: JSON.stringify({ version: visit.version }) });
      setCreated({ ...visit, status: "AWAITING_TRIAGE", version: registered.version }); setName(""); setExisting("");setMatches([]);draft.current={}; await onDone();
      setNotice({ kind: "success", text: "Synthetic visit registered and queued for triage." });
    } catch (error) { setNotice({ kind: "error", text: error instanceof Error ? error.message : "Registration failed" }); }
    finally { setBusy(false); }
  }
  return <section className="two-column form-layout">
    <article className="panel"><div className="panel-head"><div><p className="eyebrow">Arrival desk</p><h2>Register a synthetic patient</h2></div><span className="badge synthetic">Synthetic only</span></div>
      <div className="row-actions"><button className="secondary" onClick={search}>Find existing synthetic patient</button></div>{matches.length > 0 && <label>Existing patient<select value={existing} onChange={e=>setExisting(e.target.value)}><option value="">Create a new patient</option>{matches.map(p=><option key={p.id} value={p.id}>{p.pseudonym || p.id} · {p.id.slice(0,8)}</option>)}</select></label>}<form onSubmit={submit} className="form-grid"><label className="span-2">Pseudonym or internal ID (for search)<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Tadiwa Moyo (fictional)" maxLength={120} /></label><label>Age band<select value={ageBand} onChange={(e) => setAgeBand(e.target.value)}><option>child</option><option>adult</option><option>older_adult</option></select></label><label>Recorded sex<select value={sex} onChange={(e) => setSex(e.target.value)}><option value="not_recorded">Not recorded</option><option value="female">Female</option><option value="male">Male</option></select></label><label>Visit type<select value={visitType} onChange={e=>setVisitType(e.target.value)}><option value="walk_in">Walk-in</option><option value="follow_up">Follow-up</option><option value="referral">Referral</option></select></label><label className="checkbox"><input type="checkbox" checked={plannedPharmacy} onChange={e=>setPlannedPharmacy(e.target.checked)}/>Plan pharmacy after consultation</label><div className="callout span-2">No national ID, address, contact details or real patient data are needed for this demonstration.</div><button className="primary span-2" disabled={busy}>{busy ? "Creating visit…" : "Create visit and complete registration"}</button></form>
    </article>
    <article className="panel receipt"><p className="eyebrow">Private queue receipt</p>{created ? <><div className="receipt-token">{created.public_token}</div><p>Display number · {formatTime(created.arrival_at)}</p><p>Next step: triage. Keep this private receipt with you.</p><label>Opaque status token<textarea readOnly value={created.opaque_status_token || ""} rows={3} /></label><div className="row-actions no-print"><button className="secondary" onClick={async()=>{try{if(!navigator.clipboard)throw new Error("Select and copy the token manually on this network connection.");await navigator.clipboard.writeText(created.opaque_status_token||"");setNotice({kind:"success",text:"Private token copied."});}catch(e){setNotice({kind:"error",text:e instanceof Error?e.message:"Select and copy the token manually."});}}}>Copy private token</button><button className="secondary" onClick={()=>window.print()}>Print receipt</button></div><p className="receipt-url">Check status at {typeof window!=="undefined"?window.location.origin:""}/status</p><small>Only the full opaque token can retrieve patient status. It is shown once.</small></> : <Empty text="The private queue token appears here after registration." />}</article>
  </section>;
}

function Triage({ visits, onDone, setNotice }: { visits: Visit[]; onDone: () => Promise<void>; setNotice: (x: Notice) => void }) {
  const ask=useActionDialog();
  const awaiting = visits.filter((item) => item.status === "AWAITING_TRIAGE");
  const [selected, setSelected] = useState("");
  const [urgency, setUrgency] = useState("P3");
  const [reason, setReason] = useState("");
  const [escalation, setEscalation] = useState(false);
  const [observations, setObservations] = useState<Record<string,string>>({});
  const [recommendation, setRecommendation] = useState<{id: string; suggestion?: string; decision: string} | null>(null);
  const visit = awaiting.find((item) => item.id === selected) || awaiting[0];
  useEffect(() => { setRecommendation(null);setUrgency("P3");setObservations({});setReason("");setEscalation(false); }, [visit?.id]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!visit) return;
    if (!await ask({title:`Confirm ${urgency} for ${visit.public_token}`,description:"This records your clinician assessment, not an autonomous AI decision.",submit:"Confirm clinician assessment"})) return;
    try { await api(`/api/v1/visits/${visit.id}/triage`, { method: "POST", body: JSON.stringify({ configured_urgency: urgency, reason: reason || null, observations: Object.fromEntries(Object.entries(observations).map(([k,v])=>[k,v===""?null:Number(v)])), escalation_required: escalation, recommendation_id: recommendation?.id || null, recommendation_decision: recommendation?.decision || "NO_MODEL", version: visit.version }) }); await onDone(); setReason(""); setNotice({ kind: "success", text: escalation ? "Escalation alert recorded for clinician-directed handling." : "Clinician urgency confirmed; consultation queue updated." }); }
    catch (error) { setNotice({ kind: "error", text: error instanceof Error ? error.message : "Triage failed" }); }
  }
  return <section className="two-column form-layout"><article className="panel"><div className="panel-head"><div><p className="eyebrow">Awaiting assessment</p><h2>Triage station</h2></div><span className="count">{awaiting.length}</span></div>{awaiting.length ? <form onSubmit={submit} className="form-grid"><label className="span-2">Visit<select value={visit?.id || ""} onChange={(e) => setSelected(e.target.value)}>{awaiting.map((item) => <option key={item.id} value={item.id}>{item.public_token} · {item.patient?.pseudonym || "Synthetic patient"}</option>)}</select></label><label>Clinician-confirmed urgency<select value={urgency} onChange={(e) => setUrgency(e.target.value)}>{["P1", "P2", "P3", "P4", "P5"].map((item) => <option key={item}>{item}</option>)}</select></label><label className="checkbox"><input type="checkbox" checked={escalation} onChange={(e) => setEscalation(e.target.checked)} /> Escalation required</label><label className="span-2">Assessment rationale<textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="Operational or clinical rationale (no diagnosis required)" rows={4} /></label><ObservationInputs values={observations} onChange={setObservations}/><button className="primary span-2">Confirm assessment</button></form> : <Empty text="No visits are waiting for triage." />}</article><AdvisoryPanel visitId={visit?.id} onDecision={(value) => { setRecommendation(value); if (value?.decision === "ACCEPT" && value.suggestion) setUrgency(value.suggestion); }} /></section>;
}

function Queues({ points, visits, user, onDone, setNotice, navigate }: { points: ServicePoint[]; visits: Visit[]; user: User; onDone: () => Promise<void>; setNotice: (x: Notice) => void; navigate: (tab:string, patientId?:string)=>void }) {
  const ask=useActionDialog();
  const [queues, setQueues] = useState<Record<string, QueueEntry[]>>({});
  const [filter,setFilter]=useState(""),[service,setService]=useState(""),[longOnly,setLongOnly]=useState(false),[loadError,setLoadError]=useState("");
  const visible=(entry:QueueEntry)=>{const visit=visits.find(v=>v.id===entry.visit_id);return (!longOnly||entry.long_wait_warning)&&`${entry.public_token} ${visit?.patient?.pseudonym||""}`.toLowerCase().includes(filter.toLowerCase());};
  const load = useCallback(async () => { const pairs = await Promise.all(points.map(async (point) => [point.id, (await api<{ entries: QueueEntry[] }>(`/api/v1/service-points/${point.id}/queue`)).entries] as const)); setQueues(Object.fromEntries(pairs)); setLoadError(""); }, [points]);
  useEffect(() => { load().catch(e=>setLoadError(e.message)); }, [load]);
  async function call(entry: QueueEntry) { if (!await ask({title:`Call ${entry.public_token} next?`,description:"For staffed rooms, use Staff & rooms to approve a reservation first."})) return; try { await api(`/api/v1/queue/${entry.queue_entry_id}/call`, { method: "POST", body: JSON.stringify({ version: entry.version }) }); await Promise.all([load(), onDone()]); setNotice({ kind: "success", text: `${entry.public_token} called atomically.` }); } catch (e) { setNotice({ kind: "error", text: e instanceof Error ? e.message : "Call failed" }); } }
  async function pin(entry: QueueEntry) { const response=await ask({title:"Clinician queue override",fields:[{name:"rank",label:"New rank",type:"number",value:"1",min:1,required:true},reasonField]});if(!response)return;const value=response.rank,note=response.reason; try { await api("/api/v1/queue/override", { method: "POST", body: JSON.stringify({ queue_entry_id: entry.queue_entry_id, new_rank: Number(value), reason_code: "CLINICAL_JUDGEMENT", note, version: entry.version }) }); await load(); setNotice({ kind: "success", text: "Override pinned and audited." }); } catch (e) { setNotice({ kind: "error", text: e instanceof Error ? e.message : "Override failed" }); } }
  return <><article className="panel spaced"><div className="form-grid"><label>Filter queue<input value={filter} onChange={e=>setFilter(e.target.value)} placeholder="Token or authorised patient name"/></label><label>Service<select value={service} onChange={e=>setService(e.target.value)}><option value="">All services</option>{points.filter(p=>!["registration","discharge"].includes(p.type)).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label className="checkbox"><input type="checkbox" checked={longOnly} onChange={e=>setLongOnly(e.target.checked)}/>Long waits only</label>{hasAny(user,["ADMIN","CLINICIAN","TRIAGE_NURSE","SERVICE_PROVIDER","PHARMACY"])&&<button className="secondary" onClick={()=>navigate("operations")}>View staffed rooms</button>}</div><small>Filtering preserves the server’s queue ranks. It does not change priority or call eligibility.</small>{loadError&&<p role="alert" className="error">{loadError}</p>}</article><section className="queue-grid spaced">{points.filter((p) => !["registration", "discharge"].includes(p.type)&&(!service||p.id===service)).map((point) => <article className="panel queue-panel" key={point.id}><div className="panel-head"><div><p className="eyebrow">Capacity {point.capacity}</p><h2>{point.name}</h2></div><span className={`badge ${point.outage_state.toLowerCase()}`}>{point.outage_state}</span></div>{(queues[point.id] || []).filter(visible).length ? <ol className="queue-list">{queues[point.id].filter(visible).map((entry) => <li key={entry.queue_entry_id} data-visit-id={entry.visit_id}><span className="rank">{entry.recommended_order}</span><div className="queue-person"><strong>{entry.public_token} · {visits.find(v=>v.id===entry.visit_id)?.patient?.pseudonym||point.name} <span className="badge priority">{entry.confirmed_urgency}</span>{entry.manual_pin && <span className="badge pinned">Override</span>}</strong><small>{entry.explanations.join(" · ")}</small>{entry.long_wait_warning && <em>Long-wait warning remains active</em>}</div><div className="row-actions">{hasAny(user,["RECEPTIONIST","TRIAGE_NURSE","CLINICIAN"])&&visits.find(v=>v.id===entry.visit_id)?.patient&&<button className="small secondary" onClick={()=>navigate("patients",visits.find(v=>v.id===entry.visit_id)!.patient!.id)}>Record</button>}{((point.type === "pharmacy" && user.roles.includes("PHARMACY")) || (["consultation","laboratory","discharge"].includes(point.type) && hasAny(user,["CLINICIAN","SERVICE_PROVIDER"])) || (point.type === "triage" && hasAny(user,["CLINICIAN","TRIAGE_NURSE"]))) && <button className="small primary" disabled={point.capacity === 0} onClick={() => call(entry)}>Call</button>}{hasAny(user, ["CLINICIAN", "TRIAGE_NURSE"]) && <button className="small secondary" onClick={() => pin(entry)}>Override</button>}</div></li>)}</ol> : <Empty text={point.capacity === 0 ? "Queue paused; capacity is zero." : "No eligible waiting visits."} />}</article>)}</section></>;
}

function ServiceConsole({ visits, points, user, onDone, setNotice }: { visits: Visit[]; points: ServicePoint[]; user: User; onDone: () => Promise<void>; setNotice: (x: Notice) => void }) {
  const ask=useActionDialog();
  const episodes = visits.flatMap((visit) => visit.episodes.map((episode) => ({ visit, episode }))).filter(({ episode }) => canOperateService(user,episode.service_type) && ["CALLED", "IN_SERVICE", "PAUSED"].includes(episode.status));
  async function start(id: string, version: number) { try { await api(`/api/v1/episodes/${id}/start`, { method: "POST", body: JSON.stringify({ version }) }); await onDone(); setNotice({ kind: "success", text: "Service started." }); } catch (e) { setNotice({ kind: "error", text: e instanceof Error ? e.message : "Start failed" }); } }
  async function complete(id: string, version: number, current: string) { const response=await ask({title:"Complete service & route",description:"The completed stage is preserved. Returning from laboratory creates a new consultation episode.",fields:[{name:"next",label:"Next service",type:"select",value:current==="consultation"&&points.find(p=>p.type===current)?.allowed_routes.includes("pharmacy")?"pharmacy":"",options:[{value:"",label:"Finish visit"},...choices(points.find(p=>p.type===current)?.allowed_routes||[])]},{name:"note",label:"Service completion note",type:"textarea",value:"",max:500}]});if(!response)return;const next=response.next; try { await api(`/api/v1/episodes/${id}/complete`, { method: "POST", body: JSON.stringify({ version, next_service_type: next || null, operational_note: response.note || null }) }); await onDone(); setNotice({ kind: "success", text: next ? `Service completed and routed to ${next}.` : "Service completed and visit closed." }); } catch (e) { setNotice({ kind: "error", text: e instanceof Error ? e.message : "Complete failed" }); } }
  async function changeState(id:string,version:number,action:"PAUSE"|"RESUME") {const response=await ask({title:action==="PAUSE"?"Pause service":"Resume service",fields:[{...reasonField,max:240}]});if(!response)return;try{await api(`/api/v1/episodes/${id}/${action==="RESUME"?"start":"state"}`,{method:"POST",body:JSON.stringify(action==="RESUME"?{version,reason:response.reason}:{action,version,reason:response.reason})});await onDone();setNotice({kind:"success",text:action==="PAUSE"?"Service paused; room reservation retained.":"Service resumed."});}catch(e){setNotice({kind:"error",text:e instanceof Error?e.message:"State change failed"});}}
  return <article className="panel"><div className="panel-head"><div><p className="eyebrow">Provider worklist</p><h2>Called and in-service visits</h2></div><span className="count">{episodes.length}</span></div>{episodes.length ? <div className="service-cards">{episodes.map(({ visit, episode }) => <div key={episode.id} className="service-card" data-visit-id={visit.id}><div><span className="token">{visit.public_token}</span><h3>{episode.service_point}</h3><p>{visit.patient?.pseudonym || "Synthetic patient"}</p><small>Called {formatTime(episode.called_at)}</small></div><span className={`badge ${episode.status.toLowerCase()}`}>{episode.status.replaceAll("_", " ")}</span><div className="row-actions">{episode.status === "CALLED" && <button className="primary" onClick={() => start(episode.id, episode.version)}>Start service</button>}{episode.status === "IN_SERVICE" && <button className="primary" onClick={() => complete(episode.id, episode.version, episode.service_type)}>Complete & route</button>}</div>{episode.status==="IN_SERVICE"&&<button className="secondary" onClick={()=>changeState(episode.id,episode.version,"PAUSE")}>Pause service</button>}{episode.status==="PAUSED"&&<button className="primary" onClick={()=>changeState(episode.id,episode.version,"RESUME")}>Resume service</button>}<EpisodeNotebook episodeId={episode.id}/></div>)}</div> : <Empty text="Call a patient from a live queue to begin service." />}</article>;
}

function Analytics() {
  const [data, setData] = useState<any>(null);
  const [error,setError]=useState("");
  const [from,setFrom]=useState(""),[through,setThrough]=useState(""),[query,setQuery]=useState(""),[busy,setBusy]=useState(false);
  useEffect(() => { let live=true;setBusy(true);setError("");api(`/api/v1/analytics/overview?${query}`).then(value=>{if(live)setData(value);}).catch(e=>{if(live)setError(e.message);}).finally(()=>{if(live)setBusy(false);});return()=>{live=false;}; }, [query]);
  function applyRange(start:string,end:string){const params=new URLSearchParams();if(start)params.set("from_date",start);if(end)params.set("to_date",end);setQuery(params.toString());}
  function recent(days:number){const end=new Intl.DateTimeFormat("en-CA",{timeZone:"Africa/Harare",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());const date=new Date(end+"T12:00:00Z");date.setUTCDate(date.getUTCDate()-days+1);const start=date.toISOString().slice(0,10);setFrom(start);setThrough(end);applyRange(start,end);}
  if (!data&&!error) return <Loading />;
  if(!data)return <p role="alert">{error}</p>;
  const max = Math.max(1, ...data.service_points.map((p: any) => p.waiting.p90 || 0));
  return <><article className="panel spaced"><form className="form-grid" onSubmit={e=>{e.preventDefault();applyRange(from,through);}}><label>Arrival date from<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label><label>Arrival date through<input type="date" min={from||undefined} value={through} onChange={e=>setThrough(e.target.value)}/></label><div className="row-actions span-2"><button className="primary" disabled={busy}>Apply dates</button><button type="button" className="secondary" onClick={()=>recent(7)}>Last 7 days</button><button type="button" className="secondary" onClick={()=>recent(21)}>Last 21 days</button><button type="button" className="secondary" onClick={()=>{setFrom("");setThrough("");applyRange("","");}}>All dates</button></div></form><p className="muted">Arrival cohort: {data.reporting_filter?.from_date||"first record"} to {data.reporting_filter?.to_date||"latest record"}, Africa/Harare. Historical measures use those visits; waiting-now counts remain live.</p>{busy&&<p role="status">Updating report…</p>}{error&&<p role="alert" className="error">{error}</p>}</article><section className="metric-grid spaced"><Metric label="Visits in period" value={data.visits_total} note={`${data.completed_visits} completed`} /><Metric label="Mean wait" value={data.waiting.mean == null ? "—" : Math.round(data.waiting.mean)} note="minutes across started stages" /><Metric label="P90 wait" value={data.waiting.p90 == null ? "—" : Math.round(data.waiting.p90)} note="minutes; tail remains visible" /><Metric label="Active visits" value={data.active_visits} note="active within selected arrival cohort" /></section><article className="panel"><div className="panel-head"><div><p className="eyebrow">Measured demo timestamps</p><h2>P90 wait by service point</h2></div><a className="secondary button" href={`${API_URL}/api/v1/analytics/export?${query}`} target="_blank">Export CSV</a><a className="secondary button" href={`${API_URL}/api/v1/analytics/export?format=json&${query}`} target="_blank">JSON</a><a className="secondary button" href={`${API_URL}/api/v1/analytics/export?format=svg&${query}`} target="_blank">Chart SVG</a></div><div className="bars">{data.service_points.map((point: any) => <div key={point.name}><span>{point.name}</span><div><i style={{ width: `${((point.waiting.p90 || 0) / max) * 100}%` }} /></div><strong>{point.waiting.p90 ?? "—"} min</strong></div>)}</div><div className="callout">Waiting = service start − queued time. Cancelled and never-started episodes are excluded. Results are synthetic/demo measurements.</div></article><section className="metric-grid spaced"><Metric label="Arrival to first provider" value={data.arrival_to_provider_minutes.mean ?? "—"} note="mean minutes, includes prior stages"/><Metric label="Total visit duration" value={data.total_visit_minutes.mean ?? "—"} note="mean minutes, completed visits"/><Metric label="Reviewed model overrides" value={data.model_review.overrides} note={`${data.model_review.reviewed} model reviews`}/></section><article className="panel spaced"><h2>Throughput, service time & queue snapshot</h2><div className="table-wrap"><table><thead><tr><th>Stage</th><th>Completed</th><th>Waiting now</th><th>Mean service (min)</th><th>Long waits</th></tr></thead><tbody>{data.service_points.map((p:any)=><tr key={p.name}><td>{p.name}</td><td>{p.completed}</td><td>{p.eligible_waiting_now}</td><td>{p.service.mean ?? "—"}</td><td>{p.long_wait_count}</td></tr>)}</tbody></table></div><p>Recorded staffed-room utilisation is available under Staff & rooms. No staffing history is inferred before schedules were recorded.</p><h3>Daily arrival cohorts</h3><div className="table-wrap"><table><thead><tr><th>Arrival date</th><th>Arrivals</th><th>Completed from that cohort</th></tr></thead><tbody>{data.daily_activity?.map((day:any)=><tr key={day.day}><td>{day.day}</td><td>{day.arrivals}</td><td>{day.completed}</td></tr>)}</tbody></table></div><h3>Arrivals by local hour</h3><div className="bars">{data.arrivals_by_hour.filter((h:any)=>h.arrivals>0).map((h:any)=><div key={h.hour}><span>{String(h.hour).padStart(2,"0")}:00</span><div><i style={{width:`${h.arrivals/Math.max(1,...data.arrivals_by_hour.map((v:any)=>v.arrivals))*100}%`}}/></div><strong>{h.arrivals}</strong></div>)}</div><details><summary>Methods, provenance & limitations</summary><pre>{JSON.stringify({period:data.observation_period,dataset_hash:data.dataset_hash,policy:data.policy_version,definitions:data.definitions,timestamp_basis:data.timestamp_basis},null,2)}</pre></details></article></>;
}

function Simulation() {
  const [advanced,setAdvanced]=useState("{}");
  const [scenarioName,setScenarioName]=useState("Morning arrivals"),[rate,setRate]=useState(12),[duration,setDuration]=useState(12),[reps,setReps]=useState(10),[saved,setSaved]=useState<any[]>([]);
  const loadSaved=useCallback(()=>api<any[]>("/api/v1/simulations").then(setSaved),[]);
  useEffect(()=>{loadSaved().catch(e=>setError(e.message));},[loadSaved]);
  function preset(kind:string){setScenarioName(kind);setHighLoad(false);setCount(150);setReps(10);setServers(2);setDuration(12);setRate(kind==="Afternoon surge"?24:12);setAdvanced(kind==="Consultation outage"?JSON.stringify({outage:{stage:"consultation",start_minute:60,duration_minutes:60,available_servers:1}},null,2):"{}");}
  const [count, setCount] = useState(300); const [seed, setSeed] = useState(2026); const [servers, setServers] = useState(2); const [highLoad, setHighLoad] = useState(false); const [result, setResult] = useState<any>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function run(event: FormEvent) { event.preventDefault(); setBusy(true); setError(""); try { const queued = await api<{id: string; job_id: string}>("/api/v1/simulations", { method: "POST", body: JSON.stringify({ name: scenarioName, seed, patient_count: count, replications: reps, consultation_servers: servers, arrival_rate_per_hour: rate, mean_service_minutes: duration, high_load: highLoad, ...JSON.parse(advanced) }) }); await waitForJob(queued.job_id); setResult(await api(`/api/v1/simulations/${queued.id}`));await loadSaved(); } catch (e) { setError(e instanceof Error ? e.message : "Simulation failed"); } finally { setBusy(false); } }
  return <section className="two-column form-layout"><article className="panel"><div className="panel-head"><div><p className="eyebrow">Common random numbers</p><h2>Scenario parameters</h2></div><span className="badge synthetic">Synthetic</span></div><div className="row-actions spaced">{["Morning arrivals","Afternoon surge","Consultation outage"].map(name=><button key={name} className="secondary" disabled={busy} onClick={()=>preset(name)}>{name}</button>)}</div><form onSubmit={run} className="form-grid"><label className="span-2">Scenario name<input value={scenarioName} onChange={e=>setScenarioName(e.target.value)} required maxLength={120}/></label><label>Patients<input type="number" min={1} max={5000} value={count} onChange={(e) => setCount(Number(e.target.value))} /></label><label>Seed<input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></label><label>Consultation servers<input type="number" min={0} max={20} value={servers} onChange={(e) => setServers(Number(e.target.value))} /></label><label className="checkbox"><input type="checkbox" checked={highLoad} onChange={(e) => setHighLoad(e.target.checked)} /> High-load scenario</label><label>Arrivals per hour<input type="number" min={1} max={200} value={rate} onChange={e=>setRate(Number(e.target.value))}/></label><label>Mean consultation minutes<input type="number" min={1} max={120} value={duration} onChange={e=>setDuration(Number(e.target.value))}/></label><label>Paired replications<input type="number" min={1} max={50} value={reps} onChange={e=>setReps(Number(e.target.value))}/></label><details className="span-2"><summary>Advanced reproducible scenario</summary><label>Scenario JSON overrides<textarea rows={7} value={advanced} onChange={e=>setAdvanced(e.target.value)}/></label><small>Supported: replications, arrival_rate_per_hour, mean_service_minutes, urgency_mix (5 probabilities), pharmacy_probability, stage_capacities, stage_means, hourly_rates, arrival_pattern, service_tail, outage (stage, start_minute, duration_minutes, available_servers).</small></details>{error && <div className="error span-2">{error}</div>}<button className="primary span-2" disabled={busy}>{busy ? "Running paired replications…" : "Compare FCFS, urgency-first & hybrid"}</button></form></article><article className="panel"><div className="panel-head"><div><p className="eyebrow">Primary outcome</p><h2>Waiting-time comparison</h2></div>{result && <div className="row-actions">{["csv","json","svg"].map(format=><a key={format} className="secondary button" href={`${API_URL}/api/v1/simulations/${result.id}/export?format=${format}`} target="_blank">{format.toUpperCase()}</a>)}</div>}</div><label>Saved comparisons<select value={result?.id||""} onChange={async e=>{if(!e.target.value)return;try{setResult(await api(`/api/v1/simulations/${e.target.value}`));}catch(err){setError(String(err));}}}><option value="">Select a completed comparison</option>{saved.filter(run=>run.status==="COMPLETED").map(run=><option key={run.id} value={run.id}>{run.name} · {run.replications} paired runs · {formatTime(run.started_at)}</option>)}</select></label>{result ? <><p className="warning-text">{result.results.research_label}</p><div className="policy-results">{Object.entries(result.results.policies).map(([name, item]: any) => <div key={name}><strong>{name.replace("_", " ")}</strong><span>{item.waiting_minutes.mean ?? "—"}<small> mean min</small></span><p>P90 {item.waiting_minutes.p90 ?? "—"} · utilisation {Math.round(item.utilisation_mean * 100)}%</p></div>)}</div><div className={`callout ${result.results.comparison.hybrid_improved_mean_wait ? "" : "caution"}`}>Hybrid − FCFS: {result.results.comparison.absolute_mean_difference_minutes ?? "not calculable"} minutes. {result.results.comparison.hybrid_improved_mean_wait ? "Hybrid improved this simulated mean." : "Hybrid did not improve this simulated mean; the loss is retained."}</div><details><summary>Paired confidence interval, seeds & stage metrics</summary><pre>{JSON.stringify(result.results,null,2)}</pre></details></> : <Empty text="Run a scenario to compare identical synthetic arrivals across all policies." />}</article></section>;
}


function Admin({ points, user, onDone, setNotice }: { points: ServicePoint[]; user:User; onDone: () => Promise<void>; setNotice: (x: Notice) => void }) {
  const ask=useActionDialog();
  async function update(point: ServicePoint) { const response=await ask({title:`Availability: ${point.name}`,fields:[{name:"capacity",label:"Capacity",type:"number",value:String(point.capacity),min:0,max:20,required:true},reasonField]});if(!response)return;const capacity=response.capacity,reason=response.reason;const state=Number(capacity)===0?"UNAVAILABLE":"AVAILABLE"; try { await api(`/api/v1/service-points/${point.id}/availability`, { method: "POST", body: JSON.stringify({ capacity: Number(capacity), outage_state: state, reason, version: point.version }) }); await onDone(); setNotice({ kind: "success", text: `${point.name} availability updated and audited.` }); } catch (e) { setNotice({ kind: "error", text: e instanceof Error ? e.message : "Update failed" }); } }
  async function configure(point:ServicePoint) {
    const response=await ask({title:"Configure routing & hours",fields:[{name:"name",label:"Service name",value:point.name,required:true},{name:"open",label:"Opening time",type:"time",value:String(point.operating_hours?.open||"08:00"),required:true},{name:"close",label:"Closing time",type:"time",value:String(point.operating_hours?.close||"17:00"),required:true},{name:"routes",label:"Permitted onward services",type:"checks",value:point.allowed_routes.join(","),options:choices(["consultation","laboratory","pharmacy","discharge"])},reasonField]});if(!response)return;
    try {await api(`/api/v1/admin/service-points/${point.id}/configuration`,{method:"POST",body:JSON.stringify({name:response.name,operating_hours:{open:response.open,close:response.close},allowed_routes:response.routes?response.routes.split(","):[],version:point.version,reason:response.reason})});await onDone();setNotice({kind:"success",text:"Service point configuration saved."});}
    catch(e){setNotice({kind:"error",text:e instanceof Error?e.message:"Configuration failed"});}
  }
  return <article className="panel"><div className="panel-head"><div><p className="eyebrow">Auditable configuration</p><h2>Service points</h2></div></div><div className="admin-list">{points.map((point) => <div key={point.id}><div><strong>{point.name}</strong><p>{point.type} · capacity {point.capacity}</p><small>{point.outage_state}{point.outage_reason ? ` · ${point.outage_reason}` : ""}</small></div><button className="secondary" onClick={() => update(point)}>Change availability</button>{user.roles.includes("ADMIN") && <button className="secondary" onClick={()=>configure(point)}>Configure routing & hours</button>}</div>)}</div><div className="callout caution">Pending entries are never silently discarded. Capacity zero pauses ordinary calls; rerouting requires an explicit audited transfer.</div></article>;
}

function Audit() {
  const [items,setItems]=useState<any[]>([]),[error,setError]=useState(""),[busy,setBusy]=useState(false),[more,setMore]=useState(false);
  const [action,setAction]=useState(""),[actor,setActor]=useState(""),[reason,setReason]=useState("");
  async function load(append=false) {
    setBusy(true);setError("");
    const query=new URLSearchParams();if(action)query.set("action",action);if(actor)query.set("actor_id",actor);if(reason)query.set("reason",reason);
    if(append&&items.length)query.set("cursor",items.at(-1).id);
    try {const rows=await api<any[]>(`/api/v1/audit?${query}`);setItems(previous=>append?[...previous,...rows]:rows);setMore(rows.length===250);}
    catch(e){setError(e instanceof Error?e.message:"Audit history could not be loaded");}finally{setBusy(false);}
  }
  useEffect(()=>{load();},[]);
  return <article className="panel"><div className="panel-head"><h2>Audit history</h2><span className="count">{items.length}</span></div>
    <form className="form-grid" onSubmit={e=>{e.preventDefault();load();}}><label>Action<input value={action} onChange={e=>setAction(e.target.value)} placeholder="e.g. clinician.override"/></label><label>Actor ID<input value={actor} onChange={e=>setActor(e.target.value)} placeholder="Optional staff UUID"/></label><label>Reason contains<input value={reason} onChange={e=>setReason(e.target.value)}/></label><button className="secondary" disabled={busy}>Filter audit history</button></form>
    {error&&<p role="alert" className="error">{error}</p>}{busy&&<p role="status">Loading audit events…</p>}
    <div className="audit-list">{items.map(item=><div key={item.id}><span className="audit-dot"/><div><strong>{item.action}</strong><p>{item.object_type} · {item.object_id.slice(0,12)}…</p><small>{formatTime(item.occurred_at)} · actor {item.actor_id||"system"} · correlation {item.correlation_id}{item.reason?` · ${item.reason}`:""}</small><details><summary>Non-sensitive change metadata</summary><pre>{JSON.stringify(item.metadata,null,2)}</pre></details></div></div>)}</div>
    {!busy&&!error&&!items.length&&<Empty text="No matching audited commands."/>}{more&&<button className="secondary" disabled={busy} onClick={()=>load(true)}>Load older events</button>}
  </article>;

}

function Help() { return <section className="two-column"><article className="panel prose"><p className="eyebrow">Operating boundary</p><h2>What Hutano Flow does</h2><ul className="check-list"><li>Tracks synthetic outpatient journeys and timestamps</li><li>Ranks only clinician-confirmed urgency categories</li><li>Shows plain-language queue factors and long-wait warnings</li><li>Records overrides, model reviews and state changes</li><li>Compares policies through reproducible simulation</li></ul></article><article className="panel prose"><p className="eyebrow">What it never does</p><h2>Clinical safety limits</h2><ul className="cross-list"><li>No diagnosis, treatment or prescribing</li><li>No autonomous urgency assignment</li><li>No certified emergency triage</li><li>No real patient data in the demo</li><li>No claim of clinical or legal approval</li></ul><a className="patient-link" href="/status">Open privacy-safe patient token view →</a></article></section>; }

function Empty({ text }: { text: string }) { return <div className="empty"><span>○</span><p>{text}</p></div>; }
function Loading() { return <div className="center compact"><div className="spinner" /><p>Loading database metrics…</p></div>; }

