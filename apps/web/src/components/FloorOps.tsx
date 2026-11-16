"use client";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, errorText, formatClock, formatTime } from "@/lib/api";
import type { QueueEntry, ServicePoint, User } from "@/lib/types";
import { useActionDialog } from "./ActionDialog";
import { Icon } from "./ui/Icon";
import { Empty, Loading, StatusChip, Ticket } from "./ui/primitives";
import { printScoped, type Notice } from "./FrontDesk";

type CloseItem = { visit_id: string; public_token: string; visit_status: string; stage: string; episode_status: string | null; waiting_since: string; arrived_on: string; blocking: boolean; blocking_reason: string | null };
type Preview = { local_date: string; timezone: string; already_closed: boolean; closure: null | { closed_at: string; reason: string; closed_by: string; summary: { closed_unseen: number; kept_open: number } }; open_count: number; blocking_count: number; items: CloseItem[]; policy: string };

export function DayClose({ setNotice, onDone }: { setNotice: (n: Notice) => void; onDone: () => Promise<void> }) {
  const ask = useActionDialog();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [keep, setKeep] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("End of clinic day");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const data = await api<Preview>("/api/v1/operations/day-close");
    setPreview(data);
    setKeep(new Set(data.items.filter((i) => i.blocking).map((i) => i.visit_id)));
  }, []);
  useEffect(() => { load().catch((e) => setError(errorText(e))); }, [load]);
  if (error && !preview) return <p className="error" role="alert">{error}</p>;
  if (!preview) return <Loading text="Reviewing open visits…" />;
  const closing = preview.items.filter((i) => !keep.has(i.visit_id));
  function toggle(id: string) { setKeep((prev) => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; }); }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!preview) return;
    const confirm = await ask({ title: `Close ${preview.local_date}?`, description: `${closing.length} unseen visit(s) will be recorded as left without service; ${keep.size} stay open. History is preserved; nothing is deleted.`, submit: "Close the day" });
    if (!confirm) return;
    setBusy(true);
    try {
      const result = await api<{ closed_unseen: number; kept_open: number }>("/api/v1/operations/day-close", { method: "POST", body: JSON.stringify({ local_date: preview.local_date, reason, keep_open: [...keep], expected_open_count: preview.open_count }) });
      setNotice({ kind: "success", text: `Day closed: ${result.closed_unseen} recorded as left without service, ${result.kept_open} kept open.` });
      await Promise.all([load(), onDone()]);
    } catch (e) { setNotice({ kind: "error", text: errorText(e) }); await load().catch(() => undefined); }
    finally { setBusy(false); }
  }
  if (preview.already_closed && preview.closure) return <article className="panel">
    <div className="panel-head"><div><h2>{preview.local_date} is closed</h2><p className="muted">Closed {formatTime(preview.closure.closed_at)} by {preview.closure.closed_by} — “{preview.closure.reason}”.</p></div><StatusChip status="COMPLETED" label="Closed" /></div>
    <div className="close-summary"><div><small>Recorded as left without service</small><strong>{preview.closure.summary.closed_unseen}</strong></div><div><small>Kept open</small><strong>{preview.closure.summary.kept_open}</strong></div><div><small>Open now</small><strong>{preview.open_count}</strong></div></div>
    <p className="muted">A closure is permanent and appears in the audit log. Visits that arrive later in the day stay in the queue as usual.</p>
  </article>;
  return <section className="two-column form-layout">
    <article className="panel">
      <div className="panel-head"><div><h2>Open visits on {preview.local_date}</h2><p className="muted">{preview.policy}</p></div><span className="count">{preview.open_count}</span></div>
      {preview.items.length ? <ul className="close-list">{preview.items.map((item) => {
        const kept = keep.has(item.visit_id);
        return <li key={item.visit_id} className={item.blocking ? "blocking" : kept ? "kept" : ""}>
          <Ticket token={item.public_token} />
          <div><strong style={{ fontWeight: 550 }}>{item.stage}</strong> <StatusChip status={item.episode_status || item.visit_status} /><br /><small>Waiting since {formatClock(item.waiting_since)}{item.arrived_on !== preview.local_date ? ` · arrived ${item.arrived_on}` : ""}{item.blocking_reason ? ` · ${item.blocking_reason}` : ""}</small></div>
          <label className="checkbox" style={{ minHeight: 36 }}><input type="checkbox" checked={kept} onChange={() => toggle(item.visit_id)} />Keep open</label>
        </li>;
      })}</ul> : <Empty text="No open visits. You can close the day with nothing outstanding." />}
    </article>
    <article className="panel">
      <h2>Close the day</h2>
      <div className="close-summary"><div><small>Will be recorded unseen</small><strong>{closing.length}</strong></div><div><small>Stay open</small><strong>{keep.size}</strong></div></div>
      <p className="muted">Patients still in service must be finished or kept open. Unseen patients are not deleted — they leave the queue so tomorrow starts clean and wait times stay accurate.</p>
      <form onSubmit={submit}>
        <label>Reason (recorded in the audit log)<textarea value={reason} onChange={(e) => setReason(e.target.value)} minLength={5} maxLength={240} required /></label>
        <button className="primary wide large" disabled={busy || closing.some((i) => i.blocking)}><Icon name="moon" />{busy ? "Closing…" : `Close ${preview.local_date}`}</button>
      </form>
    </article>
  </section>;
}

type Stage = { service_type: string; queued_at: string; started_at: string; ended_at: string };
const SERVICES = ["registration", "triage", "consultation", "pharmacy", "laboratory"];
const iso = (local: string) => (local ? new Date(local).toISOString() : null);

export function Downtime({ user, points, setNotice, onDone }: { user: User; points: ServicePoint[]; setNotice: (n: Notice) => void; onDone: () => Promise<void> }) {
  const [queues, setQueues] = useState<Record<string, QueueEntry[]>>({});
  const [printedAt, setPrintedAt] = useState<Date | null>(null);
  const canBackEnter = user.roles.some((r) => ["ADMIN", "RECEPTIONIST"].includes(r));
  const shown = points.filter((p) => p.type !== "discharge");
  useEffect(() => {
    Promise.all(shown.map(async (p) => [p.id, (await api<{ entries: QueueEntry[] }>(`/api/v1/service-points/${p.id}/queue`)).entries] as const))
      .then((pairs) => setQueues(Object.fromEntries(pairs))).catch(() => undefined);
  }, [points]); // eslint-disable-line react-hooks/exhaustive-deps
  function print() { setPrintedAt(new Date()); setTimeout(() => printScoped("downtime"), 50); }
  return <>
    <article className="panel">
      <div className="panel-head"><div><h2>If the system goes down</h2><p className="muted">Keep seeing patients on paper, then enter the paper records here when the system is back.</p></div>
        <button className="primary" onClick={print}><Icon name="printer" />Print downtime sheet</button></div>
      <ol className="prose" style={{ margin: 0, paddingLeft: "1.2em" }}>
        <li>Print the sheet now (it lists today&apos;s queues in their current order) and keep blank copies at reception.</li>
        <li>During an outage, write each arrival&apos;s time, ticket and stage times on the sheet. Clinicians keep deciding priority as usual.</li>
        <li>When the system returns, check the live queues first. Nothing typed offline is sent later.</li>
        <li>Back-enter each paper record below. These visits are labelled <span className="badge retrospective">Paper record</span> in reports.</li>
      </ol>
    </article>
    {canBackEnter && <BackEntry setNotice={setNotice} onDone={onDone} />}
    <section className="downtime-sheet print-only" aria-hidden="true">
      <h1>Hutano Flow — downtime sheet</h1>
      <p>Printed {printedAt ? formatTime(printedAt.toISOString()) : ""}. Queue order as last known. Fictional demonstration data.</p>
      {shown.map((p) => <div key={p.id}><h2>{p.name}</h2><table><thead><tr><th>#</th><th>Ticket</th><th>Category</th><th>Waiting (min)</th><th>Called</th><th>Started</th><th>Ended</th></tr></thead>
        <tbody>{(queues[p.id] || []).map((e) => <tr key={e.queue_entry_id}><td>{e.recommended_order}</td><td>{e.public_token}</td><td>{e.confirmed_urgency || ""}</td><td>{e.waiting_minutes}</td><td /><td /><td /></tr>)}</tbody></table></div>)}
      <h2>New arrivals during the outage</h2>
      <table className="paper-rows"><thead><tr><th>Paper #</th><th>Ticket</th><th>Arrived</th><th>Registration</th><th>Triage</th><th>Consultation</th><th>Pharmacy</th><th>Outcome</th></tr></thead>
        <tbody>{Array.from({ length: 18 }, (_, i) => <tr key={i}><td>{i + 1}</td><td /><td /><td /><td /><td /><td /><td /></tr>)}</tbody></table>
    </section>
  </>;
}

function BackEntry({ setNotice, onDone }: { setNotice: (n: Notice) => void; onDone: () => Promise<void> }) {
  const [patients, setPatients] = useState<{ id: string; pseudonym: string | null }[]>([]);
  const [query, setQuery] = useState("");
  const [patient, setPatient] = useState("");
  const [stages, setStages] = useState<Stage[]>([{ service_type: "registration", queued_at: "", started_at: "", ended_at: "" }]);
  const [busy, setBusy] = useState(false);
  useEffect(() => { const t = setTimeout(() => { api<{ id: string; pseudonym: string | null }[]>(`/api/v1/patients${query ? `?q=${encodeURIComponent(query)}` : ""}`).then(setPatients).catch(() => undefined); }, 250); return () => clearTimeout(t); }, [query]);
  const update = (index: number, field: keyof Stage, value: string) => setStages((prev) => prev.map((s, i) => (i === index ? { ...s, [field]: value } : s)));
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formEl = event.currentTarget;
    const form = new FormData(formEl);
    setBusy(true);
    try {
      const payload = {
        patient_id: patient, arrival_at: iso(String(form.get("arrival"))), visit_type: form.get("visit_type"), paper_reference: form.get("paper"), reason: form.get("reason"), outcome: form.get("outcome"),
        stages: stages.map((s) => ({ service_type: s.service_type, queued_at: iso(s.queued_at), started_at: iso(s.started_at), ended_at: iso(s.ended_at) })),
      };
      const result = await api<{ public_token: string }>("/api/v1/operations/retrospective-visits", { method: "POST", body: JSON.stringify(payload) });
      setNotice({ kind: "success", text: `Paper record entered as ${result.public_token}.` });
      formEl.reset();
      setStages([{ service_type: "registration", queued_at: "", started_at: "", ended_at: "" }]);
      await onDone();
    } catch (e) { setNotice({ kind: "error", text: errorText(e) }); } finally { setBusy(false); }
  }
  return <article className="panel spaced">
    <div className="panel-head"><div><h2>Enter a paper record</h2><p className="muted">Times are in this device&apos;s local time. Each stage must start after the previous one ended.</p></div></div>
    <form onSubmit={submit} className="form-grid">
      <label>Find patient<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Pseudonym" /></label>
      <label>Patient<select value={patient} onChange={(e) => setPatient(e.target.value)} required><option value="">Choose…</option>{patients.map((p) => <option key={p.id} value={p.id}>{p.pseudonym || "Synthetic patient"} · {p.id.slice(0, 8)}</option>)}</select></label>
      <label>Arrived<input type="datetime-local" name="arrival" required /></label>
      <label>Paper reference<input name="paper" required minLength={3} maxLength={80} placeholder="e.g. Sheet 14/11 #3" /></label>
      <label>Visit type<select name="visit_type"><option value="walk_in">Walk-in</option><option value="follow_up">Follow-up</option><option value="referral">Referral</option></select></label>
      <label>Outcome<select name="outcome"><option value="COMPLETED">Completed</option><option value="LEFT_WITHOUT_SERVICE">Left without service</option></select></label>
      <fieldset className="span-2"><legend>Stages from the paper sheet</legend>
        <div className="stack">{stages.map((s, i) => <div key={i} className="form-grid" style={{ gridTemplateColumns: "1.1fr repeat(3, 1fr) auto" }}>
          <label>Stage<select value={s.service_type} onChange={(e) => update(i, "service_type", e.target.value)}>{SERVICES.map((v) => <option key={v} value={v}>{v[0].toUpperCase() + v.slice(1)}</option>)}</select></label>
          <label>Queued<input type="datetime-local" value={s.queued_at} onChange={(e) => update(i, "queued_at", e.target.value)} required /></label>
          <label>Started<input type="datetime-local" value={s.started_at} onChange={(e) => update(i, "started_at", e.target.value)} /></label>
          <label>Ended<input type="datetime-local" value={s.ended_at} onChange={(e) => update(i, "ended_at", e.target.value)} /></label>
          <button type="button" className="ghost icon-button" aria-label={`Remove stage ${i + 1}`} disabled={stages.length === 1} onClick={() => setStages((prev) => prev.filter((_, j) => j !== i))}><Icon name="x" /></button>
        </div>)}</div>
        <button type="button" className="secondary small" style={{ marginTop: 10 }} disabled={stages.length >= 8} onClick={() => setStages((prev) => [...prev, { service_type: SERVICES[Math.min(prev.length, SERVICES.length - 1)], queued_at: prev.at(-1)?.ended_at || "", started_at: "", ended_at: "" }])}><Icon name="plus" />Add stage</button>
      </fieldset>
      <label className="span-2">Why this is being back-entered<textarea name="reason" required minLength={5} maxLength={240} defaultValue="System outage; transcribed from paper downtime sheet" /></label>
      <button className="primary span-2" disabled={busy || !patient}>{busy ? "Saving…" : "Save paper record"}</button>
    </form>
  </article>;
}
