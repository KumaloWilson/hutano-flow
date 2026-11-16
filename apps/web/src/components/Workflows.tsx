"use client";
import { FormEvent, useEffect, useState } from "react";
import { API_URL, api, formatTime, waitForJob } from "@/lib/api";
import { User, Visit } from "@/lib/types";
import { canOperateService } from "@/lib/permissions";
import { useActionDialog, choices, reasonField } from "./ActionDialog";

const clinical = (user: User) => user.roles.some((r) => ["CLINICIAN", "TRIAGE_NURSE"].includes(r));
const message = (error: unknown) => error instanceof Error ? error.message : "Request failed";

export function JourneyConsole({ visits, user, refresh, focusVisitId }: { visits: Visit[]; user: User; refresh: () => Promise<void>; focusVisitId?: string }) {
  const ask=useActionDialog();
  const [selected, setSelected] = useState(focusVisitId || "");
  useEffect(()=>{if(focusVisitId)setSelected(focusVisitId);},[focusVisitId]);
  const [error, setError] = useState("");
  const visit = visits.find((v) => v.id === selected) || visits[0];
  async function command(episode: any, action: string) {
    const response=await ask({title:action.replaceAll("_"," "),description:"This is an explicit staff action. Existing history remains preserved.",fields:[reasonField,...(action==="TRANSFER"?[{name:"next",label:"Next service",type:"select" as const,options:choices(["consultation","pharmacy","laboratory","discharge"])}]:[])]});if(!response)return;const reason=response.reason;
    try {
      if (action === "TRANSFER") {
        const next = response.next;
        if (!next) return;
        await api(`/api/v1/episodes/${episode.id}/transfer`, {method:"POST", body:JSON.stringify({version:episode.version, next_service_type:next, reason})});
      } else if (action === "RESUME") {
        await api(`/api/v1/episodes/${episode.id}/start`, {method:"POST", body:JSON.stringify({version:episode.version})});
      } else {
        await api(`/api/v1/episodes/${episode.id}/state`, {method:"POST", body:JSON.stringify({action, version:episode.version, reason})});
      }
      setError(""); await refresh();
    } catch (e) { setError(message(e)); }
  }
  async function reassess(action: string) {
    if (!visit) return;
    const response=await ask({title:"Clinician reassessment",description:"Only your confirmed category changes priority. This is not a model decision.",fields:[{name:"urgency",label:"Confirmed category",type:"select",options:choices(["P1","P2","P3","P4","P5"])},reasonField]});if(!response)return;const {urgency,reason}=response;
    try { await api(`/api/v1/visits/${visit.id}/reassess`,{method:"POST",body:JSON.stringify({version:visit.version, configured_urgency:urgency,reason,action})}); await refresh();setError(""); }
    catch(e){setError(message(e));}
  }
  async function correct(episode: any) {
    const response=await ask({title:"Append timestamp correction",description:"Original timestamps remain immutable. Time is entered in your device timezone.",fields:[{name:"field",label:"Timestamp field",type:"select",options:choices(["queued_at","called_at","started_at","ended_at"])},{name:"time",label:"Corrected time",type:"datetime-local",required:true},reasonField]});if(!response)return;const {field,reason}=response;const value=new Date(response.time).toISOString();
    try { await api(`/api/v1/episodes/${episode.id}/corrections`,{method:"POST",body:JSON.stringify({version:episode.version, previous_correction_id:episode.corrections?.at(-1)?.id || null, timestamps:{[field]:value},reason})});await refresh();setError(""); }
    catch(e){setError(message(e));}
  }
  return <article className="panel"><h2>Journey timeline</h2><p>Earlier stages remain preserved as new service episodes are added.</p>
    <label>Visit<select value={visit?.id || ""} onChange={(e) => setSelected(e.target.value)}>{visits.map(v => <option key={v.id} value={v.id}>{v.public_token} · {v.patient?.pseudonym || v.status}</option>)}</select></label>
    {error && <p role="alert" className="error">{error}</p>}
    {visit ? <><p className="cluster"><span className={`badge code ${visit.status.toLowerCase()}`}>{visit.status.replaceAll("_"," ")}</span><span className="token">{visit.public_token}</span><span className="muted">Arrived {formatTime(visit.arrival_at)}</span>{visit.entry_mode==="RETROSPECTIVE"&&<span className="badge retrospective">Paper record</span>}</p>
      {clinical(user) && ["ACTIVE","ESCALATION_REQUIRED"].includes(visit.status) && <div className="row-actions">{visit.status === "ESCALATION_REQUIRED" ? <button className="primary" onClick={()=>reassess("RESOLVE_ESCALATION")}>Clinician: resolve escalation</button> : <><button className="secondary" onClick={()=>reassess("REASSESS")}>Change confirmed priority</button><button className="secondary" onClick={()=>reassess("ESCALATE")}>Flag for clinician escalation</button></>}</div>}<ol className="timeline">{visit.episodes.map(ep => <li key={ep.id} data-status={ep.status}><h3>{ep.sequence_no}. {ep.service_point} <span className={`badge code ${ep.status.toLowerCase()}`}>{ep.status.replaceAll("_"," ")}</span>{(ep.missed_calls??0)>0&&<span className="badge attention">Missed {ep.missed_calls}×</span>}</h3>
        <dl><dt>Queued</dt><dd>{formatTime(ep.queued_at)}</dd><dt>Called</dt><dd>{formatTime(ep.called_at)}</dd><dt>Started</dt><dd>{formatTime(ep.started_at)}</dd><dt>Ended</dt><dd>{formatTime(ep.ended_at)}</dd></dl>
        {canOperateService(user,ep.service_type) && <div className="row-actions">
          {ep.status === "COMPLETED" && clinical(user) && <button className="secondary" onClick={()=>correct(ep)}>Audited timestamp correction</button>}{ep.corrections?.length ? <details><summary>Preserved corrections ({ep.corrections.length})</summary><pre>{JSON.stringify(ep.corrections,null,2)}</pre></details> : null}{ep.status === "IN_SERVICE" && <button className="secondary" onClick={() => command(ep,"PAUSE")}>Pause service</button>}
          {ep.status === "PAUSED" && <button className="primary" onClick={() => command(ep,"RESUME")}>Resume service</button>}
          {["WAITING", "CALLED"].includes(ep.status) && <button className="secondary" onClick={() => command(ep,"NO_SHOW")}>Record no-show</button>}
          {["WAITING", "CALLED", "PAUSED"].includes(ep.status) && <><button className="secondary" onClick={() => command(ep,"CANCEL")}>Cancel stage</button><button className="secondary" onClick={() => command(ep,"TRANSFER")}>Transfer stage</button></>}
          {ep.status === "NO_SHOW" && <button className="secondary" onClick={() => command(ep,"REOPEN_WAITING")}>Reopen waiting</button>}
        </div>}</li>)}</ol></> : <p>No journeys yet.</p>}
  </article>;
}

type Decision = {id: string; suggestion?: string; decision: string} | null;
export function AdvisoryPanel({visitId, onDecision}: {visitId?: string; onDecision: (v: Decision) => void}) {
  const [features, setFeatures] = useState<Record<string, string>>({});
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setResult(null); setFeatures({}); }, [visitId]);
  async function infer(event: FormEvent) {
    event.preventDefault(); if (!visitId) return;
    setBusy(true); setError(""); onDecision(null);
    const values = Object.fromEntries(Object.entries(features).map(([k,v]) => [k, v === "" ? null : ["hour","recorded_measurement"].includes(k) ? Number(v) : v]));
    try { setResult(await api(`/api/v1/visits/${visitId}/recommendation`,{method:"POST",body:JSON.stringify({features:values})})); }
    catch(e) { setError(message(e)); } finally { setBusy(false); }
  }
  function field(name: string, options?: string[]) { return <label key={name}>{name.replaceAll("_", " ")}{options ? <select value={features[name] || ""} onChange={e=>setFeatures({...features,[name]:e.target.value})}><option value="">Not recorded</option>{options.map(o=><option key={o}>{o}</option>)}</select> : <input type="number" step="any" value={features[name] || ""} onChange={e=>setFeatures({...features,[name]:e.target.value})}/>}</label>; }
  return <article className="panel advisory"><p className="eyebrow">Research advisory</p><h2>Clinician assessment required</h2><p className="warning-text">EXPERIMENTAL — NOT VALIDATED FOR PATIENT CARE</p>
    <p>No validated clinical model is available. A reviewed synthetic demonstration model may be enabled by the administrator.</p>
    <form onSubmit={infer}>{field("age_band",["child","adult","older_adult"])}{field("visit_type",["new","follow_up","referral"])}{field("arrival_mode",["walk_in","referred"])}{field("hour")}{field("recorded_measurement")}
      <small>Recorded measurement is a dimensionless synthetic training feature, not a clinical threshold.</small>
      <button className="secondary wide" disabled={!visitId || busy}>{busy ? "Computing…" : "Request advisory explanation"}</button>
    </form>{error && <p className="error" role="alert">{error}</p>}
    {result && <div className="advisory-result">{result.available ? <><strong>{result.suggestion || "Abstained — clinician review required"}</strong><p>{result.model_version}</p><p>Confidence: {result.confidence == null ? "Unavailable" : `${Math.round(result.confidence*100)}%`}</p>
      <ul>{result.factors?.map((f:any)=><li key={f.feature}>{f.feature}: {f.logit_contribution.toFixed(3)} logit contribution</li>)}{result.reasons?.map((r:string)=><li key={r}>{r}</li>)}</ul>
      <p>{result.explanation_method}</p>
      <div className="row-actions">{result.suggestion && <button className="secondary" onClick={()=>onDecision({id:result.id, suggestion:result.suggestion, decision:"ACCEPT"})}>Accept suggestion for confirmation</button>}<button className="secondary" onClick={()=>onDecision({id:result.id, decision:"REJECT"})}>Reject suggestion</button></div>
      <small>Acceptance selects a proposed category. The clinician must still press Confirm assessment.</small></> : <p>{result.message}</p>}</div>}
  </article>;
}

export function ResearchConsole({user}: {user:User}) {
  const ask=useActionDialog();
  const [datasets,setDatasets]=useState<any[]>([]), [models,setModels]=useState<any[]>([]), [jobs,setJobs]=useState<any[]>([]);
  const [selected,setSelected]=useState(""), [error,setError]=useState(""), [busy,setBusy]=useState(false), [expanded,setExpanded]=useState("");
  async function load() { const [d,m,j]=await Promise.all([api<any[]>("/api/v1/research/datasets"),api<any[]>("/api/v1/research/models"),api<any[]>("/api/v1/research/jobs")]);setDatasets(d.filter(item=>item.source_type==="SYNTHETIC"));setModels(m);setJobs(j); }
  useEffect(()=>{load().catch(e=>setError(message(e)));},[]);
  async function train() { setBusy(true);setError("");try {const j=await api<{job_id:string}>("/api/v1/research/models/train",{method:"POST",body:JSON.stringify({dataset_id:selected||datasets[0]?.id,seed:2026})});await load();await waitForJob(j.job_id);await load();} catch(e){setError(message(e));}finally{setBusy(false);} }
  async function upload(event:FormEvent<HTMLFormElement>) {event.preventDefault();setBusy(true);try{const f=new FormData(event.currentTarget);f.append("source_type","SYNTHETIC");f.append("synthetic_flag","true");await api("/api/v1/research/datasets/import",{method:"POST",body:f});await load();setError("");}catch(e){setError(message(e));}finally{setBusy(false);} }
  async function lifecycle(id:string, action:string) {const response=await ask({title:`${action} research model`,fields:[reasonField]});if(!response)return;const reason=response.reason;try{await api(`/api/v1/research/models/${id}/lifecycle`,{method:"POST",body:JSON.stringify({action,reason})});await load();}catch(e){setError(message(e));}}
  return <><div className="warning-card"><strong>EXPERIMENTAL — NOT VALIDATED FOR PATIENT CARE</strong><p>Dataset hashes, split strategy, comparison models and adverse results are retained. All supplied targets are synthetic.</p></div>
    {error&&<p className="error" role="alert">{error}</p>}<section className="two-column"><article className="panel"><h2>Dataset manager</h2>
      <label>Training dataset<select value={selected||datasets[0]?.id||""} onChange={e=>setSelected(e.target.value)}>{datasets.map(d=><option key={d.id} value={d.id}>{d.name} ({d.row_count} rows)</option>)}</select></label>
      {datasets.map(d=><details key={d.id}><summary>{d.name}</summary><p>{d.row_count} rows · {d.source_type}</p><small>SHA-256 {d.dataset_hash}</small><pre>{JSON.stringify(d.schema,null,2)}</pre></details>)}
      <form onSubmit={upload}><h3>Import synthetic CSV</h3><label>Dataset name<input name="name" minLength={3} required/></label><label>Provenance / permission note<textarea name="consent_basis_note" minLength={10} required/></label><label>CSV file<input name="file" type="file" accept=".csv,text/csv" required/></label><p>Required: age_band, visit_type, arrival_mode, hour, recorded_measurement, urgency, service_minutes, observed_at. Unknown columns and identifiers are rejected.</p><button className="secondary" disabled={busy}>Validate and import</button></form>
    </article><article className="panel"><h2>Model registry</h2><button className="primary" disabled={busy||!datasets.length} onClick={train}>{busy?"Research job running…":"Train selected dataset"}</button>
      {!models.length&&<p>No trained model yet. Manual clinical assessment remains available.</p>}
      {models.map(m=><div className="model-card" key={m.id}><div><strong>{m.version}</strong><p>{m.status} · {m.active?"Enabled for synthetic advisory":"Disabled"}</p></div><div className="model-metrics"><span>Macro F1<strong>{m.metrics.macro_f1?.toFixed(3)}</strong></span><span>Under-triage vs synthetic<strong>{m.metrics.under_triage_against_synthetic_label_count}</strong></span><span>Low-confidence cases<strong>{m.metrics.low_confidence_requires_review_count}</strong></span></div>
        <button className="secondary" onClick={()=>setExpanded(expanded===m.id?"":m.id)}>Metrics & confusion matrix</button>
        {user.roles.includes("ADMIN")&&<div className="row-actions"><button className="secondary" onClick={()=>lifecycle(m.id,m.active?"DISABLE":"ACTIVATE")}>{m.active?"Disable advisory":"Activate reviewed advisory"}</button><button className="secondary" onClick={()=>lifecycle(m.id,"RETIRE")}>Retire</button></div>}
        {expanded===m.id&&<section className="span-2"><p>Rows: reference; columns: model prediction</p><table><thead><tr><th>Reference</th>{m.metrics.labels.map((l:string)=><th key={l}>{l}</th>)}</tr></thead><tbody>{m.metrics.confusion_matrix.map((row:number[],i:number)=><tr key={i}><th>{m.metrics.labels[i]}</th>{row.map((v,j)=><td key={j}>{v}</td>)}</tr>)}</tbody></table><details open><summary>Evaluation and limitations</summary><pre>{JSON.stringify(m.metrics,null,2)}</pre></details></section>}
      </div>)}
    </article></section><article className="panel spaced"><h2>Recent research jobs</h2><button className="secondary" onClick={()=>load().catch(e=>setError(message(e)))}>Refresh jobs</button>{jobs.map(j=><p key={j.id}>{j.type} · {j.status} · {formatTime(j.created_at)} {j.error || ""} {j.type==="SIMULATION"&&j.status==="COMPLETED"&&<a href={`${API_URL}/api/v1/simulations/${j.result_ref}/export`} target="_blank">Download report</a>}</p>)}</article></>;
}

export function ReviewPanel({user}:{user:User}) {
  const ask=useActionDialog();
  const [models,setModels]=useState<any[]>([]),[policies,setPolicies]=useState<any[]>([]),[error,setError]=useState("");
  async function load(){const [m,p]=await Promise.all([api<any[]>("/api/v1/models/reviewable"),api<any[]>("/api/v1/queue/policies")]);setModels(m);setPolicies(p);}
  useEffect(()=>{if(clinical(user))load().catch(e=>setError(message(e)));},[user]);
  if(!clinical(user))return null;
  async function review(id:string,kind:string){const response=await ask({title:"Review for synthetic demonstration",fields:[reasonField]});if(!response)return;const reason=response.reason;try{await api(kind==="model"?`/api/v1/research/models/${id}/lifecycle`:`/api/v1/queue/policies/${id}/approve`,{method:"POST",body:JSON.stringify(kind==="model"?{action:"REVIEW",reason}:{reason})});await load();}catch(e){setError(message(e));}}
  return <article className="panel spaced"><h2>Clinician research review</h2><p>Review authorises synthetic demonstrations only. It is not clinical validation.</p>{error&&<p className="error">{error}</p>}{policies.map(p=><details key={p.id}><summary>Policy {p.version} · {p.active?"active":"inactive"}</summary><pre>{JSON.stringify(p.config,null,2)}</pre>{!p.active&&<button className="secondary" onClick={()=>review(p.id,"policy")}>Approve and activate demo policy</button>}</details>)}{models.map(m=><details key={m.id}><summary>Model {m.version} · {m.status}</summary><pre>{JSON.stringify(m.metrics,null,2)}</pre>{m.status==="EXPERIMENTAL"&&<button className="secondary" onClick={()=>review(m.id,"model")}>Record clinician research review</button>}</details>)}</article>;
}

export function AdminConsole({user}:{user:User}) {
  const ask=useActionDialog();
  const [users,setUsers]=useState<any[]>([]),[error,setError]=useState("");
  async function load(){setUsers(await api<any[]>("/api/v1/admin/users"));}
  useEffect(()=>{if(user.roles.includes("ADMIN"))load().catch(e=>setError(message(e)));},[user]);
  if(!user.roles.includes("ADMIN"))return null;
  async function create(event:FormEvent<HTMLFormElement>){event.preventDefault();const f=new FormData(event.currentTarget);const formEl=event.currentTarget;try{await api("/api/v1/admin/users",{method:"POST",body:JSON.stringify({email:f.get("email"),display_name:f.get("display_name"),password:f.get("password"),roles:[f.get("role")]})});formEl.reset();await load();setError("Account created with a temporary password.");}catch(e){setError(message(e));}}
  async function access(target:any){const response=await ask({title:"Edit account access",description:"Saving revokes existing sessions.",fields:[{name:"roles",label:"Assigned roles",type:"checks",value:target.roles.join(","),options:choices(["RECEPTIONIST","TRIAGE_NURSE","CLINICIAN","SERVICE_PROVIDER","PHARMACY","MANAGER","RESEARCHER","ADMIN"])},{name:"status",label:"Account status",type:"select",value:target.active?"ACTIVE":"DISABLED",options:choices(["ACTIVE","DISABLED"])}]});if(!response)return;const roles=response.roles,active=response.status==="ACTIVE";try{await api(`/api/v1/admin/users/${target.id}`,{method:"POST",body:JSON.stringify({roles:roles.split(",").map(r=>r.trim()),active})});await load();}catch(e){setError(message(e));}}
  async function reset(target:any){const response=await ask({title:`Reset password for ${target.display_name}`,description:"Give them the temporary password in person. They must choose their own at next sign-in; all their sessions end now.",fields:[{name:"password",label:"Temporary password (12+ characters)",type:"text",required:true,min:12,max:128},reasonField],submit:"Set temporary password"});if(!response)return;try{await api(`/api/v1/admin/users/${target.id}/password`,{method:"POST",body:JSON.stringify({temporary_password:response.password,reason:response.reason})});await load();setError(`Temporary password set for ${target.display_name}. Account unlocked.`);}catch(e){setError(message(e));}}
  async function policy(event:FormEvent<HTMLFormElement>){event.preventDefault();const f=new FormData(event.currentTarget);try{await api("/api/v1/queue/policies",{method:"POST",body:JSON.stringify({mode:f.get("mode"),waiting_weight:Number(f.get("waiting_weight")),long_wait_warning_minutes:Number(f.get("warning")),reason:f.get("reason")})});setError("Policy proposed. A clinician must review it in Help & safety before activation.");}catch(e){setError(message(e));}}
  return <section className="two-column spaced"><article className="panel"><h2>Staff access</h2>{error&&<p role="status" className="callout">{error}</p>}<div className="admin-list">{users.map(u=><div key={u.id}><div><strong>{u.display_name}</strong><p className="muted" style={{fontSize:".84rem"}}>{u.email} · {u.roles.join(", ").replaceAll("_"," ").toLowerCase()}</p></div>{!u.active&&<span className="badge cancelled">Disabled</span>}{u.locked&&<span className="badge locked">Locked</span>}{u.must_change_password&&<span className="badge attention">Temporary password</span>}{u.id!==user.id&&<><button className="secondary small" onClick={()=>access(u)}>{u.locked?"Unlock / edit access":"Edit access"}</button><button className="ghost small" onClick={()=>reset(u)}>Reset password</button></>}</div>)}</div>
    <form onSubmit={create}><h3 style={{marginTop:18}}>Create account</h3><p className="muted" style={{fontSize:".85rem"}}>The password you set is temporary; the person chooses their own at first sign-in.</p><label>Email<input name="email" type="email" required/></label><label>Display name<input name="display_name" minLength={2} required/></label><label>Temporary password<input name="password" type="text" minLength={12} required autoComplete="off"/></label><label>Role<select name="role">{["RECEPTIONIST","TRIAGE_NURSE","CLINICIAN","SERVICE_PROVIDER","PHARMACY","MANAGER","RESEARCHER","ADMIN"].map(r=><option key={r}>{r}</option>)}</select></label><button className="primary">Create account</button></form></article>
    <article className="panel"><h2>Queue policy proposal</h2><form onSubmit={policy}><label>Policy<select name="mode"><option>HYBRID</option><option>FCFS</option><option>URGENCY_FIRST</option></select></label><label>Within-group ageing weight<input name="waiting_weight" type="number" min={0} max={10} step=".1" defaultValue={.25}/></label><label>Long-wait warning (minutes)<input name="warning" type="number" min={1} max={1440} defaultValue={60}/></label><label>Reason<textarea name="reason" minLength={5} required/></label><p>Urgency groups remain protected. Capacity pauses service and does not penalise longer consultations.</p><button className="primary">Submit for clinician review</button></form></article></section>;
}

export function FeedbackPanel(){
  const [notice,setNotice]=useState("");
  const [report,setReport]=useState<any>(null);
  async function loadSummary(){try{setReport(await api("/api/v1/research/feedback/summary"));}catch(e){setNotice(message(e));}}
  async function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();const f=new FormData(event.currentTarget);try{await api("/api/v1/research/feedback",{method:"POST",body:JSON.stringify({role_group:f.get("role_group"),task_id:f.get("task_id"),consent_ref:f.get("consent_ref"),response:{completed:f.get("completed")==="yes",duration_seconds:Number(f.get("duration")),errors:Number(f.get("errors")),comments:f.get("comments"),trust_rating:Number(f.get("trust_rating"))}})});setNotice("Consented research feedback recorded.");await loadSummary();}catch(e){setNotice(message(e));}}
  return <article className="panel spaced"><h2>Usability task observation</h2><p>Use a pseudonymous consent reference. Include unsuccessful tasks and critical comments.</p><form onSubmit={submit} className="form-grid"><label>Role group<input name="role_group" required minLength={2}/></label><label>Task<select name="task_id">{["register","find_patient","triage","call_next","override","complete_visit","check_token","read_analytics"].map(t=><option key={t}>{t}</option>)}</select></label><label>Consent reference<input name="consent_ref" required minLength={3}/></label><label>Completed<select name="completed"><option value="yes">Yes</option><option value="no">No</option></select></label><label>Duration (seconds)<input name="duration" type="number" min={0} required/></label><label>Error count<input name="errors" type="number" min={0} required/></label><label>Descriptive trust rating<select name="trust_rating"><option value="1">1 · Low</option><option value="2">2</option><option value="3">3</option><option value="4">4</option><option value="5">5 · High</option></select></label><label className="span-2">Comments<textarea name="comments" maxLength={2000}/></label><button className="primary">Record feedback</button></form>{notice&&<p role="status">{notice}</p>}<button className="secondary" onClick={loadSummary}>Load aggregate task & trust summary</button>{report&&<pre>{JSON.stringify(report,null,2)}</pre>}<small>This descriptive trust question is not a validated questionnaire or benchmark.</small></article>;
}

export function BaselinePanel(){
  const [report,setReport]=useState<any>(null),[error,setError]=useState("");
  const [saved,setSaved]=useState<any[]>([]);
  async function loadSaved(){try{setSaved((await api<any[]>("/api/v1/research/datasets")).filter(d=>d.source_type==="SYNTHETIC_BASELINE"));}catch(e){setError(message(e));}}
  useEffect(()=>{loadSaved();},[]);
  async function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();const data=new FormData(event.currentTarget);try{setReport(await api("/api/v1/research/baseline/import",{method:"POST",body:data}));setError("");await loadSaved();}catch(e){setError(message(e));}}
  return <article className="panel spaced"><h2>Anonymous baseline timing import</h2><p>Import a synthetic time-motion CSV. Fieldwork targets remain 300 completed journeys across three weeks, subject to separate approval.</p><form onSubmit={submit} className="form-grid"><label>Name<input name="name" minLength={3} required/></label><label>Provenance<input name="provenance" minLength={5} required/></label><label className="span-2">CSV<input type="file" name="file" accept=".csv,text/csv" required/></label><label className="span-2">Column mapping (source name to standard name, JSON)<input name="column_mapping" defaultValue="{}"/></label><label>Import action<select name="preview_only"><option value="true">Validate and preview</option><option value="false">Register validated dataset</option></select></label><button className="primary">Process baseline</button></form><p>Columns: journey_no, stage, arrived_at, queued_at, started_at, ended_at. Timestamps require an explicit UTC offset.</p>{error&&<p className="error">{error}</p>}{report&&<pre>{JSON.stringify(report,null,2)}</pre>}{saved.map(d=><details key={d.id}><summary>Stored baseline: {d.name}</summary><small>SHA-256 {d.dataset_hash}</small><pre>{JSON.stringify(d.schema.report,null,2)}</pre></details>)}</article>;
}
