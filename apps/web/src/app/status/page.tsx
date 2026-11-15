"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ServiceWorker } from "@/components/ServiceWorker";

export default function StatusPage() {
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeToken, setActiveToken] = useState("");
  const [lastSync, setLastSync] = useState("");
  async function lookup(value: string) {
    const result = await api("/api/v1/patient-status/lookup", { method: "POST", body: JSON.stringify({ token: value }) });
    setStatus(result); setLastSync(new Date().toLocaleTimeString()); setError("");
  }
  useEffect(() => {
    if (!activeToken) return;
    const timer = setInterval(() => { lookup(activeToken).catch(() => setError("Connection unavailable — status may be out of date. Retrying automatically.")); }, 10000);
    return () => clearInterval(timer);
  }, [activeToken]);
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); setError(""); setStatus(null); setActiveToken(""); try { await lookup(token); setActiveToken(token); } catch (e) { setError(e instanceof Error ? e.message : "Token not found"); } finally { setBusy(false); } }
  return <main className="status-shell"><ServiceWorker /><a href="/" className="back-link">← Staff sign in</a><section className="status-card"><div className="brand-mark">HF</div><p className="eyebrow">Private queue check</p><h1>Where am I in the queue?</h1><p>Enter the full private token on your receipt. Your health details and priority are never shown here.</p><form onSubmit={submit}><label>Private status token<input value={token} onChange={(e) => setToken(e.target.value)} minLength={20} autoComplete="off" required placeholder="A-001.full-private-token" /></label><button className="primary wide" disabled={busy}>{busy ? "Checking…" : "Check status"}</button></form>{error && <div className="error" role="alert">{error}</div>}{lastSync && <p role="status">Last successful sync: {lastSync} · Updates every 10 seconds</p>}{status && <div className="patient-result"><span className="token large">{status.token}</span><p>Current stage</p><h2>{status.stage}</h2><span className={`badge ${String(status.status).toLowerCase()}`}>{String(status.status).replaceAll("_", " ")}</span><div className="position"><strong>{status.people_ahead ?? "—"}</strong><span>people approximately ahead at this stage</span></div>{status.estimated_wait ? <p className="estimate">Estimated range: <strong>{status.estimated_wait.minimum_minutes}–{status.estimated_wait.maximum_minutes} minutes</strong><small>{status.estimated_wait.warning}</small></p> : <p className="estimate">Estimate unavailable</p>}</div>}<small className="privacy-note">This page does not display your name, condition, age, urgency, model output, or anyone else in the queue.</small></section></main>;
}

