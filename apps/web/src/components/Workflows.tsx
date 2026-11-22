"use client";
import { FormEvent, useEffect, useState } from "react";
import { API_URL, api, formatTime, waitForJob } from "@/lib/api";
import { User, Visit } from "@/lib/types";
import { canOperateService } from "@/lib/permissions";
import { useActionDialog, choices, reasonField, serviceChoices } from "./ActionDialog";

const clinical = (user: User) => user.roles.some((r) => ["CLINICIAN", "TRIAGE_NURSE"].includes(r));
const message = (error: unknown) => error instanceof Error ? error.message : "Request failed";

export function JourneyConsole({ visits, user, refresh, focusVisitId }: { visits: Visit[]; user: User; refresh: () => Promise<void>; focusVisitId?: string }) {
  const ask=useActionDialog();
  const [selected, setSelected] = useState(focusVisitId || "");
  useEffect(()=>{if(focusVisitId)setSelected(focusVisitId);},[focusVisitId]);
  const [error, setError] = useState("");
  const visit = visits.find((v) => v.id === selected) || visits[0];
  async function command(episode: any, action: string) {
    const response=await ask({title:action.replaceAll("_"," "),description:"This is an explicit staff action. Existing history remains preserved.",fields:[reasonField,...(action==="TRANSFER"?[{name:"next",label:"Next service",type:"select" as const,options:serviceChoices(["consultation","pharmacy","laboratory","discharge"])}]:[])]});if(!response)return;const reason=response.reason;
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
const FEATURE_NAMES: Record<string,string> = {age_band:"Age band",visit_type:"Visit type",arrival_mode:"Arrival",hour:"Arrival hour",temperature:"Temperature",pulse:"Pulse",respiratory_rate:"Respiratory rate",oxygen_saturation:"Oxygen saturation",systolic_pressure:"Systolic pressure",diastolic_pressure:"Diastolic pressure"};
const FEATURE_UNITS: Record<string,string> = {temperature:"°C",pulse:"beats/min",respiratory_rate:"breaths/min",oxygen_saturation:"%",systolic_pressure:"mmHg",diastolic_pressure:"mmHg"};

/** Research advisory (proposal Objective 2): inputs come from the visit record and the
 *  vitals typed in the triage form; the clinician sees what was used and why. */
export function AdvisoryPanel({visitId, observations, onDecision}: {visitId?: string; observations?: Record<string,string>; onDecision: (v: Decision) => void}) {
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setResult(null); setError(""); }, [visitId]);
  async function infer(event: FormEvent) {
    event.preventDefault(); if (!visitId) return;
    setBusy(true); setError(""); onDecision(null);
    const typed = Object.fromEntries(Object.entries(observations || {}).filter(([,v]) => v !== "").map(([k,v]) => [k, Number(v)]));
    try {
      const answer:any = await api(`/api/v1/visits/${visitId}/recommendation`,{method:"POST",body:JSON.stringify({observations:typed})});
      setResult(answer);
      // An abstention has nothing to accept; it is still linked to the assessment, as before, without a button.
      if (answer?.available && !answer.suggestion && answer.id) onDecision({id:answer.id, decision:"REJECT"});
    }
    catch(e) { setError(message(e)); } finally { setBusy(false); }
  }
  const plain = result?.plain_language;
  return <article className="panel advisory"><div className="split"><h2 style={{margin:0}}>Research advisory</h2><span className="badge attention">Experimental</span></div>
    <p className="warning-text" style={{marginTop:8}}>EXPERIMENTAL — NOT VALIDATED FOR PATIENT CARE</p>
    <p className="muted" style={{fontSize:".88rem"}}>Reads the registration details and the vital signs recorded for this visit, including any typed in the form but not yet saved. Missing vital signs are shown as not recorded, never assumed normal. You decide the category.</p>
    <form onSubmit={infer}><button className="secondary wide" disabled={!visitId || busy}>{busy ? "Computing…" : "Request advisory explanation"}</button></form>
    {error && <p className="error" role="alert">{error}</p>}
    {result && <div className="advisory-result">{result.available ? <>
      {result.suggestion ? <div className="split"><strong style={{fontSize:"1.05rem"}}>Suggests <span className="urgency" data-level={result.suggestion}>{result.suggestion}</span></strong><span className="mono muted" title="Calibrated on synthetic data; not a probability of clinical correctness">{result.confidence>=.995?">99":Math.round(result.confidence*100)}% model confidence</span></div>
        : <strong>No suggestion — clinician assessment only</strong>}
      {plain && <><p style={{margin:"10px 0 6px"}}>{plain.headline}</p>
        {!!plain.opposing?.length && <p className="muted" style={{margin:"0 0 6px",fontSize:".86rem"}}>Pointing the other way: {plain.opposing.join("; ")}.</p>}
        <p className="privacy-note" style={{margin:0}}>{plain.caveat}</p></>}
      {!result.suggestion && !!result.reasons?.length && <ul style={{margin:"8px 0 0"}}>{result.reasons.map((r:string)=><li key={r}>{r}</li>)}</ul>}
      {!!result.inputs?.length && <details><summary>Inputs used ({result.inputs.filter((i:any)=>i.value!=null).length} of {result.inputs.length} recorded)</summary>
        <div className="table-wrap"><table><thead><tr><th>Input</th><th>Value</th><th>Source</th></tr></thead><tbody>{result.inputs.map((i:any)=><tr key={i.feature}><td>{FEATURE_NAMES[i.feature]||i.feature}</td><td className="mono">{i.value==null?"Not recorded":`${String(i.value).replaceAll("_"," ")} ${FEATURE_UNITS[i.feature]||""}`}</td><td>{i.source}</td></tr>)}</tbody></table></div></details>}
      {result.suggestion && <details><summary>Technical explanation</summary><p className="muted" style={{fontSize:".82rem"}}>{result.explanation_method}</p>
        <ul>{result.factors?.map((f:any)=><li key={f.feature} className="mono" style={{fontSize:".8rem"}}>{f.feature}: {f.logit_contribution.toFixed(3)}</li>)}</ul>
        {result.contrastive && <p className="mono" style={{fontSize:".8rem"}}>{result.contrastive.predicted_class} vs {result.contrastive.alternative_class}: log-probability ratio {result.contrastive.calibrated_log_probability_ratio.toFixed(3)}</p>}
        <p className="muted" style={{fontSize:".8rem"}}>Model {result.model_version}</p></details>}
      {result.suggestion && <div className="row-actions" style={{marginTop:10}}><button className="secondary" onClick={()=>onDecision({id:result.id, suggestion:result.suggestion, decision:"ACCEPT"})}>Accept suggestion for confirmation</button><button className="secondary" onClick={()=>onDecision({id:result.id, decision:"REJECT"})}>Reject suggestion</button></div>}
      {result.suggestion && <small>Accepting only pre-fills the category. You must still press Confirm assessment.</small>}</> : <><p style={{margin:0}}><strong>{result.message}</strong></p>{result.how_to_enable && <p className="muted" style={{margin:"6px 0 0",fontSize:".88rem"}}>{result.how_to_enable} Triage works normally without it.</p>}</>}</div>}
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

function Likert({name,label,points}:{name:string;label:string;points:number}){
  return <fieldset className="likert"><legend>{label}</legend><div className="likert-scale">{Array.from({length:points},(_,i)=>i+1).map(v=><label key={v} className="likert-point"><input type="radio" name={name} value={v}/><span>{v}</span></label>)}</div></fieldset>;
}

export function FeedbackPanel(){
  const [notice,setNotice]=useState("");
  const [report,setReport]=useState<any>(null);
  const [instruments,setInstruments]=useState<any>(null);
  useEffect(()=>{api("/api/v1/research/instruments").then(setInstruments).catch(()=>undefined);},[]);
  async function loadSummary(){try{setReport(await api("/api/v1/research/feedback/summary"));}catch(e){setNotice(message(e));}}
  async function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();const form=event.currentTarget,f=new FormData(form);
    const numbers=(prefix:string,n:number)=>Array.from({length:n},(_,i)=>Number(f.get(`${prefix}${i}`)));
    const response:any={completed:f.get("completed")==="yes",duration_seconds:Number(f.get("duration")),errors:Number(f.get("errors")),comments:f.get("comments"),trust_rating:Number(f.get("trust_rating"))};
    const answered=(prefix:string,n:number)=>Array.from({length:n},(_,i)=>f.get(`${prefix}${i}`)).filter(Boolean).length;
    const sus=answered("sus",10),tam=answered("pu",4)+answered("peou",4);
    if(sus&&sus<10){setNotice(`Answer all ten SUS items (${sus} answered) or none.`);return;}
    if(tam&&tam<8){setNotice(`Answer all eight acceptance items (${tam} answered) or none.`);return;}
    if(sus)response.sus=numbers("sus",10);
    if(tam)response.tam={perceived_usefulness:numbers("pu",4),perceived_ease_of_use:numbers("peou",4)};
    try{await api("/api/v1/research/feedback",{method:"POST",body:JSON.stringify({role_group:f.get("role_group"),task_id:f.get("task_id"),consent_ref:f.get("consent_ref"),response})});setNotice("Consented research feedback recorded.");form.reset();await loadSummary();}catch(e){setNotice(message(e));}}
  const a=report?.acceptance;
  return <article className="panel spaced"><h2>Usability session</h2><p className="muted">Record one task attempt per form, with a pseudonymous consent reference. Include unsuccessful tasks and critical comments. Complete the questionnaires once per participant, after their tasks.</p>
    <form onSubmit={submit} className="stack"><div className="form-grid"><label>Role group<input name="role_group" required minLength={2}/></label><label>Task<select name="task_id">{["register","find_patient","triage","call_next","override","complete_visit","check_token","read_analytics"].map(t=><option key={t}>{t}</option>)}</select></label><label>Consent reference<input name="consent_ref" required minLength={3}/></label><label>Completed<select name="completed"><option value="yes">Yes</option><option value="no">No</option></select></label><label>Duration (seconds)<input name="duration" type="number" min={0} required/></label><label>Error count<input name="errors" type="number" min={0} required/></label><label>Descriptive trust rating<select name="trust_rating"><option value="1">1 · Low</option><option value="2">2</option><option value="3">3</option><option value="4">4</option><option value="5">5 · High</option></select></label><label className="span-2">Comments<textarea name="comments" maxLength={2000}/></label></div>
      {instruments&&<details><summary>System Usability Scale — 10 items, 1 strongly disagree to 5 strongly agree</summary><p className="muted" style={{fontSize:".82rem"}}>{instruments.sus.source}. Answer all ten or none.</p>{instruments.sus.items.map((item:string,i:number)=><Likert key={i} name={`sus${i}`} label={`${i+1}. ${item}`} points={5}/>)}</details>}
      {instruments&&<details><summary>Acceptance (TAM) — 8 items, 1 strongly disagree to 7 strongly agree</summary><p className="muted" style={{fontSize:".82rem"}}>{instruments.tam.source}.</p><h3>Perceived usefulness</h3>{instruments.tam.items.perceived_usefulness.map((item:string,i:number)=><Likert key={i} name={`pu${i}`} label={item} points={7}/>)}<h3>Perceived ease of use</h3>{instruments.tam.items.perceived_ease_of_use.map((item:string,i:number)=><Likert key={i} name={`peou${i}`} label={item} points={7}/>)}</details>}
      <button className="primary">Record feedback</button></form>
    {notice&&<p role="status" className="callout">{notice}</p>}<button className="secondary" onClick={loadSummary}>Load aggregate task & acceptance summary</button>
    {a&&<section className="metric-grid spaced"><article className="metric"><p>Mean SUS</p><strong>{a.sus.mean??"—"}</strong><small>n={a.sus.n}{a.sus.ci95?` · 95% CI ${a.sus.ci95[0]}–${a.sus.ci95[1]}`:""} · average ≈ 68</small></article><article className="metric"><p>Perceived usefulness</p><strong>{a.tam.perceived_usefulness.mean??"—"}</strong><small>of 7 · α {a.tam.perceived_usefulness.cronbach_alpha?.toFixed(2)??"n/a"}</small></article><article className="metric"><p>Perceived ease of use</p><strong>{a.tam.perceived_ease_of_use.mean??"—"}</strong><small>of 7 · α {a.tam.perceived_ease_of_use.cronbach_alpha?.toFixed(2)??"n/a"}</small></article><article className="metric"><p>Tasks completed</p><strong>{report.tasks_completed}/{report.tasks_observed}</strong><small>observed attempts</small></article></section>}
    {report&&<details><summary>Full summary</summary><pre>{JSON.stringify(report,null,2)}</pre></details>}
    <small>SUS uses standard scoring. TAM wording is adapted and needs piloting. Small samples are descriptive only.</small></article>;
}

function HourBars({rows,valueKey,unit}:{rows:any[];valueKey:string;unit:string}){
  const max=Math.max(1e-9,...rows.map(r=>r[valueKey]));
  return <div className="bars hour-bars">{rows.map(r=><div key={r.hour}><span>{String(r.hour).padStart(2,"0")}:00</span><div><i style={{width:`${r[valueKey]/max*100}%`}}/></div><strong>{Number(r[valueKey]).toFixed(1)} {unit}</strong></div>)}</div>;
}

export function BaselineReport({report}:{report:any}){
  if(!report?.stages)return null;
  const little=report.littles_law;
  return <div className="stack" style={{marginTop:12}}>
    <section className="metric-grid">
      <article className="metric"><p>Journeys measured</p><strong>{report.journeys}</strong><small>{report.days_observed} days observed</small></article>
      <article className="metric"><p>Arrival to provider</p><strong>{Math.round(report.arrival_to_provider_minutes?.mean??0)}</strong><small>mean minutes</small></article>
      <article className="metric metric-alert"><p>Bottleneck</p><strong style={{fontSize:"1.25rem",textTransform:"capitalize",overflowWrap:"anywhere",fontFamily:"var(--font-ui)",fontWeight:600}}>{report.bottleneck_stage||"—"}</strong><small>longest mean wait</small></article>
      <article className="metric"><p>Time spent waiting</p><strong>{report.time_share?.waiting==null?"—":`${Math.round(report.time_share.waiting*100)}%`}</strong><small>of summed visit time</small></article>
    </section>
    <div className="two-column">
      <div><h3>Arrivals by hour</h3><p className="muted" style={{fontSize:".84rem"}}>{report.morning_arrival_share!=null&&`${Math.round(report.morning_arrival_share*100)}% arrive before noon.`}</p>{report.arrivals_by_hour&&<HourBars rows={report.arrivals_by_hour} valueKey="mean_arrivals_per_day" unit="/day"/>}</div>
      <div><h3>Queue length by hour · {report.bottleneck_stage}</h3><p className="muted" style={{fontSize:".84rem"}}>Mean people waiting, from snapshots every {little?.snapshot_interval_minutes} minutes.</p>{report.queue_length_by_hour?.[report.bottleneck_stage]&&<HourBars rows={report.queue_length_by_hour[report.bottleneck_stage]} valueKey="mean_waiting" unit=""/>}</div>
    </div>
    <h3>Waiting and service at each point</h3>
    <div className="table-wrap"><table><thead><tr><th>Stage</th><th>Mean wait</th><th>P90 wait</th><th>Mean service</th><th>Little&apos;s Law L / λW</th></tr></thead><tbody>{Object.entries(report.stages).map(([stage,v]:[string,any])=>{const l=little?.stages?.[stage];return <tr key={stage}><td style={{textTransform:"capitalize"}}>{stage}</td><td className="mono">{v.waiting_minutes.mean?.toFixed(1)}</td><td className="mono">{v.waiting_minutes.p90?.toFixed(1)}</td><td className="mono">{v.service_minutes.mean?.toFixed(1)}</td><td className="mono">{l?(l.assessable?`${l.ratio} ${l.consistent?"✓":"⚠"}`:"queue too short to assess"):"—"}</td></tr>;})}</tbody></table></div>
    {little&&<p className="muted" style={{fontSize:".8rem"}}>{little.method}</p>}
  </div>;
}

export function BaselinePanel(){
  const [report,setReport]=useState<any>(null),[error,setError]=useState("");
  const [saved,setSaved]=useState<any[]>([]);
  async function loadSaved(){try{setSaved((await api<any[]>("/api/v1/research/datasets")).filter(d=>d.source_type==="SYNTHETIC_BASELINE"));}catch(e){setError(message(e));}}
  useEffect(()=>{loadSaved();},[]);
  async function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();const data=new FormData(event.currentTarget);try{setReport(await api("/api/v1/research/baseline/import",{method:"POST",body:data}));setError("");await loadSaved();}catch(e){setError(message(e));}}
  return <article className="panel spaced"><h2>Anonymous baseline timing import</h2><p>Import a synthetic time-motion CSV. Fieldwork targets remain 300 completed journeys across three weeks, subject to separate approval.</p><form onSubmit={submit} className="form-grid"><label>Name<input name="name" minLength={3} required/></label><label>Provenance<input name="provenance" minLength={5} required/></label><label className="span-2">CSV<input type="file" name="file" accept=".csv,text/csv" required/></label><label className="span-2">Column mapping (source name to standard name, JSON)<input name="column_mapping" defaultValue="{}"/></label><label>Import action<select name="preview_only"><option value="true">Validate and preview</option><option value="false">Register validated dataset</option></select></label><button className="primary">Process baseline</button></form><p>Columns: journey_no, stage, arrived_at, queued_at, started_at, ended_at. Timestamps require an explicit UTC offset. <a href={`${API_URL}/api/v1/research/baseline/synthetic-example?days=15`}>Download a synthetic example</a> (15 walk-in days, FCFS).</p>{error&&<p className="error">{error}</p>}{report&&<><BaselineReport report={report}/><details><summary>Full report</summary><pre>{JSON.stringify({...report,wait_samples:undefined,arrival_to_provider_sample:undefined},null,2)}</pre></details></>}{saved.map(d=><details key={d.id}><summary>Stored baseline: {d.name}</summary><small>SHA-256 {d.dataset_hash}</small><BaselineReport report={d.schema.report}/></details>)}</article>;
}
