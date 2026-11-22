"use client";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api, errorText, formatClock } from "@/lib/api";
import type { Visit } from "@/lib/types";
import { Icon } from "./ui/Icon";
import { Empty } from "./ui/primitives";
import { QrCode } from "./ui/QrCode";

export type Notice = { kind: "success" | "error"; text: string } | null;
type Match = { id: string; pseudonym: string | null; age_band: string | null; sex: string | null; created_at: string };

/** Print only the receipt: a body class scopes the print stylesheet, then is removed. */
export function printScoped(kind: "receipt" | "downtime") {
  document.body.classList.add(`printing-${kind}`);
  const done = () => { document.body.classList.remove(`printing-${kind}`); window.removeEventListener("afterprint", done); };
  window.addEventListener("afterprint", done);
  window.print();
  setTimeout(done, 1500);
}

export function Receipt({ visit, next = "Triage", onNotice }: { visit: Visit | null; next?: string; onNotice: (n: Notice) => void }) {
  const [origin, setOrigin] = useState("");
  useEffect(() => setOrigin(window.location.origin), []);
  if (!visit) return <article className="panel receipt"><p className="eyebrow">Queue receipt</p><Empty icon="qr" text="After registration the patient's ticket and private QR code appear here, ready to print." /></article>;
  const secret = visit.opaque_status_token || "";
  const link = `${origin}/status#t=${encodeURIComponent(secret)}`;
  async function copy() {
    try {
      if (!navigator.clipboard) throw new Error("Select and copy the token manually on this connection.");
      await navigator.clipboard.writeText(secret);
      onNotice({ kind: "success", text: "Private token copied." });
    } catch (e) { onNotice({ kind: "error", text: errorText(e, "Select and copy the token manually.") }); }
  }
  return <article className="panel receipt" aria-labelledby="receipt-title">
    <div className="split"><p className="eyebrow" id="receipt-title">Queue receipt · {formatClock(visit.arrival_at)}</p><span className="badge synthetic">Synthetic</span></div>
    <div className="receipt-ticket">
      <div>
        <small>Your ticket</small>
        <div className="receipt-token">{visit.public_token}</div>
        <p style={{ margin: "8px 0 0" }}>Next: <strong>{next}</strong>. Watch the screen for your number.</p>
      </div>
      {secret && <div className="receipt-qr"><QrCode value={link} label={`QR code to check the status of ticket ${visit.public_token}`} /></div>}
    </div>
    <p className="privacy-note">Scan the code to check your place in the queue. It shows your stage and position only — never your name or health details.</p>
    <label>Opaque status token<textarea readOnly value={secret} rows={2} className="mono" onFocus={(e) => e.currentTarget.select()} /></label>
    <div className="row-actions no-print">
      <button className="primary" onClick={() => printScoped("receipt")}><Icon name="printer" />Print receipt</button>
      <button className="secondary" onClick={copy}>Copy private token</button>
    </div>
    <small className="no-print">Shown once. Only the full private token can retrieve status. Hand the printed receipt to the patient.</small>
  </article>;
}

/** People already in the clinic whose registration has not been completed at the desk. */
function WaitingAtDesk({ visits, onDone, setNotice }: { visits: Visit[]; onDone: () => Promise<void>; setNotice: (x: Notice) => void }) {
  const [busy, setBusy] = useState("");
  const waiting = visits.filter((v) => v.status === "REGISTERING");
  async function complete(visit: Visit) {
    setBusy(visit.id);
    try {
      await api(`/api/v1/visits/${visit.id}/register`, { method: "POST", body: JSON.stringify({ version: visit.version }) });
      await onDone();
      setNotice({ kind: "success", text: `${visit.public_token} registered. ${visit.patient?.pseudonym || "The patient"} is now waiting for triage.` });
    } catch (e) { setNotice({ kind: "error", text: errorText(e, "Registration could not be completed") }); }
    finally { setBusy(""); }
  }
  return <article className="panel spaced" aria-label="Waiting at the front desk">
    <h2>Waiting at the front desk</h2>
    {waiting.length ? <div className="up-next">{waiting.map((v) => <div className="next-row" key={v.id}>
      <span className="mono">{v.public_token}</span>
      <div><strong style={{ fontWeight: 550 }}>{v.patient?.pseudonym || "Synthetic patient"}</strong><small className="muted"> · arrived {formatClock(v.arrival_at)}</small></div>
      <button type="button" className="primary small" disabled={!!busy} onClick={() => complete(v)}>{busy === v.id ? "Registering…" : "Complete registration"}</button>
    </div>)}</div> : <p className="muted">Nobody is waiting at the desk.</p>}
  </article>;
}

export function Registration({ onDone, setNotice, visits = [] }: { onDone: () => Promise<void>; setNotice: (x: Notice) => void; visits?: Visit[] }) {
  const [name, setName] = useState("");
  const [ageBand, setAgeBand] = useState("adult");
  const [sex, setSex] = useState("not_recorded");
  const [visitType, setVisitType] = useState("walk_in");
  const [pharmacy, setPharmacy] = useState(true);
  const [matches, setMatches] = useState<Match[]>([]);
  const [existing, setExisting] = useState<Match | null>(null);
  const [created, setCreated] = useState<Visit | null>(null);
  const [busy, setBusy] = useState(false);
  const draft = useRef<{ patient?: { id: string }; visit?: Visit }>({});
  const nameField = useRef<HTMLInputElement>(null);

  // Search as the receptionist types, so returning patients are reused rather than duplicated.
  useEffect(() => {
    if (existing || name.trim().length < 2) { setMatches([]); return; }
    const timer = setTimeout(() => {
      api<Match[]>(`/api/v1/patients?q=${encodeURIComponent(name.trim())}`).then((rows) => setMatches(rows.slice(0, 5))).catch(() => setMatches([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [name, existing]);

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setCreated(null);
    try {
      const patient = draft.current.patient || (existing ? { id: existing.id } : await api<{ id: string }>("/api/v1/patients", { method: "POST", body: JSON.stringify({ pseudonym: name || null, age_band: ageBand, sex, synthetic_flag: true }) }));
      draft.current.patient = patient;
      const visit = draft.current.visit || await api<Visit>("/api/v1/visits", { method: "POST", body: JSON.stringify({ patient_id: patient.id, visit_type: visitType, planned_services: ["triage", "consultation", ...(pharmacy ? ["pharmacy"] : [])] }) });
      draft.current.visit = visit;
      const registered = await api<{ version: number }>(`/api/v1/visits/${visit.id}/register`, { method: "POST", body: JSON.stringify({ version: visit.version }) });
      setCreated({ ...visit, status: "AWAITING_TRIAGE", version: registered.version });
      setName(""); setExisting(null); setMatches([]); draft.current = {};
      await onDone();
      setNotice({ kind: "success", text: "Synthetic visit registered and queued for triage." });
      nameField.current?.focus();
    } catch (error) { setNotice({ kind: "error", text: errorText(error, "Registration failed") }); }
    finally { setBusy(false); }
  }

  return <><section className="two-column form-layout">
    <article className="panel">
      <div className="panel-head"><div><h2>Register an arrival</h2><p className="muted">Type a name to find a returning patient. No national ID, phone or address is collected.</p></div><span className="badge synthetic">Synthetic only</span></div>
      <form onSubmit={submit} className="form-grid">
        <label className="span-2">Pseudonym or internal ID (for search)
          <input ref={nameField} value={existing ? (existing.pseudonym || existing.id) : name} onChange={(e) => { setExisting(null); setName(e.target.value); }} placeholder="e.g. Tadiwa Moyo (fictional)" maxLength={120} autoComplete="off" readOnly={!!existing} />
        </label>
        {existing && <div className="span-2 callout" style={{ margin: 0, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <span><strong>Returning patient</strong> · {existing.age_band || "age not recorded"} · registered {formatClock(existing.created_at)}</span>
          <button type="button" className="ghost small" onClick={() => setExisting(null)}>Not this person</button>
        </div>}
        {!existing && matches.length > 0 && <div className="span-2" role="listbox" aria-label="Possible returning patients" style={{ display: "grid", gap: 6 }}>
          <small>Possible matches — choose one to avoid a duplicate record</small>
          {matches.map((m) => <button type="button" key={m.id} role="option" aria-selected="false" className="secondary" style={{ justifyContent: "space-between" }} onClick={() => { setExisting(m); setMatches([]); }}>
            <span>{m.pseudonym || "Synthetic patient"}</span><small className="mono">{m.age_band || "—"} · {m.id.slice(0, 8)}</small>
          </button>)}
        </div>}
        {!existing && <>
          <label>Age band<select value={ageBand} onChange={(e) => setAgeBand(e.target.value)}><option value="child">Child</option><option value="adult">Adult</option><option value="older_adult">Older adult</option></select></label>
          <label>Recorded sex<select value={sex} onChange={(e) => setSex(e.target.value)}><option value="not_recorded">Not recorded</option><option value="female">Female</option><option value="male">Male</option></select></label>
        </>}
        <label>Visit type<select value={visitType} onChange={(e) => setVisitType(e.target.value)}><option value="walk_in">Walk-in</option><option value="follow_up">Follow-up</option><option value="referral">Referral</option></select></label>
        <label className="checkbox"><input type="checkbox" checked={pharmacy} onChange={(e) => setPharmacy(e.target.checked)} />Plan pharmacy after consultation</label>
        <button className="primary large span-2" disabled={busy}>{busy ? "Creating visit…" : "Create visit and complete registration"}</button>
      </form>
    </article>
    <Receipt visit={created} onNotice={setNotice} />
  </section><WaitingAtDesk visits={visits} onDone={onDone} setNotice={setNotice} /></>;
}
