"use client";
import { FormEvent, useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";
import type { Visit } from "@/lib/types";
import { useActionDialog } from "./ActionDialog";
import { ObservationInputs } from "./PatientWorkspace";
import { AdvisoryPanel } from "./Workflows";
import { Empty, Ticket, Wait } from "./ui/primitives";
import type { Notice } from "./FrontDesk";

const waited = (visit: Visit) => {
  const triage = visit.episodes.find((e) => e.service_type === "triage" && e.status === "WAITING");
  const since = triage?.queued_at || visit.registered_at || visit.arrival_at;
  return Math.max(0, Math.floor((Date.now() - new Date(since).getTime()) / 60000));
};

export function Triage({ visits, onDone, setNotice }: { visits: Visit[]; onDone: () => Promise<void>; setNotice: (x: Notice) => void }) {
  const ask = useActionDialog();
  const awaiting = visits.filter((item) => item.status === "AWAITING_TRIAGE").sort((a, b) => waited(b) - waited(a));
  const [selected, setSelected] = useState("");
  const [urgency, setUrgency] = useState("P3");
  const [reason, setReason] = useState("");
  const [escalation, setEscalation] = useState(false);
  const [observations, setObservations] = useState<Record<string, string>>({});
  const [recommendation, setRecommendation] = useState<{ id: string; suggestion?: string; decision: string } | null>(null);
  const visit = awaiting.find((item) => item.id === selected) || awaiting[0];
  useEffect(() => { setRecommendation(null); setUrgency("P3"); setObservations({}); setReason(""); setEscalation(false); }, [visit?.id]);

  async function submit(event: FormEvent) {
    event.preventDefault(); if (!visit) return;
    if (!await ask({ title: `Confirm ${urgency} for ${visit.public_token}`, description: "This records your clinician assessment, not an autonomous AI decision.", submit: "Confirm clinician assessment" })) return;
    try {
      await api(`/api/v1/visits/${visit.id}/triage`, { method: "POST", body: JSON.stringify({ configured_urgency: urgency, reason: reason || null, observations: Object.fromEntries(Object.entries(observations).map(([k, v]) => [k, v === "" ? null : Number(v)])), escalation_required: escalation, recommendation_id: recommendation?.id || null, recommendation_decision: recommendation?.decision || "NO_MODEL", version: visit.version }) });
      await onDone(); setReason("");
      setNotice({ kind: "success", text: escalation ? "Escalation alert recorded for clinician-directed handling." : "Clinician urgency confirmed; consultation queue updated." });
    } catch (error) { setNotice({ kind: "error", text: errorText(error, "Triage failed") }); }
  }

  return <section className="two-column form-layout">
    <article className="panel">
      <div className="panel-head"><div><h2>Assessment</h2><p className="muted">Longest-waiting first. Only your confirmed category affects queue order.</p></div><span className="count" aria-label={`${awaiting.length} waiting for triage`}>{awaiting.length}</span></div>
      {awaiting.length ? <form onSubmit={submit} className="form-grid">
        <label className="span-2">Visit<select value={visit?.id || ""} onChange={(e) => setSelected(e.target.value)}>{awaiting.map((item) => <option key={item.id} value={item.id}>{item.public_token} · {item.patient?.pseudonym || "Synthetic patient"} · waiting {waited(item)} min</option>)}</select></label>
        <label>Clinician-confirmed urgency<select value={urgency} onChange={(e) => setUrgency(e.target.value)}>{["P1", "P2", "P3", "P4", "P5"].map((item) => <option key={item}>{item}</option>)}</select><span className="form-hint">Neutral research categories; P1 is called first.</span></label>
        <label className="checkbox"><input type="checkbox" checked={escalation} onChange={(e) => setEscalation(e.target.checked)} /> Escalation required</label>
        <label className="span-2">Assessment rationale<textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="Operational or clinical rationale (no diagnosis required)" rows={3} /></label>
        <ObservationInputs values={observations} onChange={setObservations} />
        <button className="primary large span-2">Confirm assessment</button>
      </form> : <Empty text="No one is waiting for triage. New registrations appear here automatically." />}
    </article>
    <div className="stack">
      {awaiting.length > 0 && <article className="panel">
        <div className="panel-head" style={{ marginBottom: 8 }}><h2>Waiting for triage</h2></div>
        <div className="up-next">{awaiting.slice(0, 8).map((item) => <div className="next-row" key={item.id}>
          <Ticket token={item.public_token} />
          <div><strong style={{ fontWeight: 550 }}>{item.patient?.pseudonym || "Synthetic patient"}</strong></div>
          <Wait minutes={waited(item)} long={waited(item) >= 60} />
          <button type="button" className={item.id === visit?.id ? "primary small" : "secondary small"} aria-pressed={item.id === visit?.id} onClick={() => setSelected(item.id)}>{item.id === visit?.id ? "Assessing" : "Assess"}</button>
        </div>)}</div>
      </article>}
      <AdvisoryPanel visitId={visit?.id} observations={observations} onDecision={(value) => { setRecommendation(value); if (value?.decision === "ACCEPT" && value.suggestion) setUrgency(value.suggestion); }} />
    </div>
  </section>;
}
