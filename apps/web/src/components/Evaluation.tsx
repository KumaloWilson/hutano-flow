"use client";
import { useEffect, useState } from "react";
import { API_URL, api, errorText, formatTime } from "@/lib/api";
import { Loading, StatusChip } from "./ui/primitives";
import { Icon } from "./ui/Icon";
import { BaselineReport, FeedbackPanel } from "./Workflows";

type Requirement = { requirement: string; met: boolean; note?: string };
type Objective = { id: string; objective: string; research_question: string; proposal_refs: string[]; status: string; evidence?: any; requirements: Requirement[]; outside_system?: string[] };
type Report = { generated_at: string; research_label: string; objectives: Objective[]; limitations: string[] };

const STATUS: Record<string, { chip: string; label: string }> = {
  evidence: { chip: "COMPLETED", label: "Evidence available" }, partial: { chip: "ATTENTION", label: "Partial evidence" }, missing: { chip: "UNKNOWN", label: "No evidence yet" },
};
const n = (v: any, d = 1) => (v == null ? "—" : Number(v).toFixed(d));
const p = (v: any) => (v == null ? "—" : v < .001 ? "<0.001" : Number(v).toFixed(3));

function Requirements({ items }: { items: Requirement[] }) {
  return <ul className="req-list">{items.map((item) => <li key={item.requirement} className={item.met ? "" : "unmet"}>
    <span>{item.requirement}{item.note && <small className="muted">{item.note}</small>}</span>
  </li>)}</ul>;
}

function ObjectiveEvidence({ objective }: { objective: Objective }) {
  const e = objective.evidence;
  if (!e) return <p className="muted">No evidence recorded yet.</p>;
  if (objective.id === "O1") return <BaselineReport report={{ ...e, stages: Object.fromEntries(Object.keys(e.stage_waits || {}).map((k) => [k, { waiting_minutes: e.stage_waits[k], service_minutes: e.stage_service[k] }])),
    journeys: e.dataset?.journeys, days_observed: e.dataset?.days_observed, littles_law: e.littles_law }} />;
  if (objective.id === "O2") return <section className="metric-grid">
    <article className="metric"><p>Macro-F1</p><strong>{n(e.macro_f1, 2)}</strong><small>majority {n(e.comparators_macro_f1?.majority, 2)} · forest {n(e.comparators_macro_f1?.random_forest, 2)}</small></article>
    <article className="metric metric-alert"><p>Under-triage</p><strong>{e.under_triage?.count ?? "—"}</strong><small>{e.under_triage?.rate != null ? `${n(e.under_triage.rate * 100)}% of held-out cases` : ""} · vs {e.label_source?.toLowerCase()} labels</small></article>
    <article className="metric"><p>Suggestion coverage</p><strong>{e.coverage_at_threshold != null ? `${Math.round(e.coverage_at_threshold * 100)}%` : "—"}</strong><small>abstains on the rest · risk {e.selective_risk != null ? `${Math.round(e.selective_risk * 100)}%` : "—"}</small></article>
    <article className="metric"><p>Calibration error</p><strong>{n(e.expected_calibration_error, 3)}</strong><small>expected calibration error</small></article>
    <div className="span-2" style={{ gridColumn: "1 / -1" }}><p className="muted" style={{ fontSize: ".86rem" }}>Model {e.model_version} · {e.feature_schema} · inputs: {(e.inputs || []).map((x: string) => x.replaceAll("_", " ")).join(", ")}. {e.explanation}.</p></div>
  </section>;
  if (objective.id === "O3") return <section className="metric-grid">
    <article className="metric"><p>Visits tracked</p><strong>{e.visits_tracked}</strong><small>{e.queue_state_transitions} queue state transitions</small></article>
    <article className="metric"><p>Clinician overrides</p><strong>{e.clinician_overrides}</strong><small>each with a logged reason</small></article>
    <article className="metric"><p>Reassessments</p><strong>{e.clinician_reassessments}</strong><small>including long-wait reviews</small></article>
    <article className="metric"><p>Waiting-room displays</p><strong>{e.active_waiting_room_displays}</strong><small>active</small></article>
  </section>;
  const waits = Object.entries(e.waiting_time_existing_vs_system || {}) as [string, any][];
  const sim = e.simulation || {}, acc = e.usability_and_acceptance;
  return <div className="stack">
    <h3 style={{ margin: 0 }}>Waiting time: existing process vs system</h3>
    {waits.length ? <div className="table-wrap" style={{ margin: 0 }}><table><thead><tr><th>Stage</th><th>Baseline median (n)</th><th>System median (n)</th><th>Mann–Whitney p</th><th>Rank-biserial r</th></tr></thead>
      <tbody>{waits.map(([stage, w]) => <tr key={stage}><td style={{ textTransform: "capitalize" }}>{stage}</td><td className="mono">{n(w.baseline_median)} ({w.baseline_n})</td><td className="mono">{n(w.system_median)} ({w.system_n})</td><td className="mono">{w.test ? p(w.p_value) : "—"}</td><td className="mono">{w.test ? `${n(w.rank_biserial, 2)}` : <small>{w.note}</small>}</td></tr>)}</tbody></table></div> : <p className="muted">Import a baseline and record system activity to compare.</p>}
    <h3 style={{ margin: 0 }}>Simulation</h3>
    {sim.run_id ? <><p style={{ margin: 0 }}>{sim.calibrated_from_baseline ? <><StatusChip status={sim.reproduces_baseline ? "COMPLETED" : "ATTENTION"} label={sim.reproduces_baseline ? "Reproduces baseline" : "Does not reproduce baseline"} /> Calibrated from the measured baseline, {sim.replications} simulated days.</> : "Not calibrated from a baseline — run a calibrated comparison in the Simulation lab."}</p>
      <div className="table-wrap" style={{ margin: 0 }}><table><thead><tr><th>Policy</th><th>Mean journey wait</th><th>Δ vs FCFS (95% CI)</th><th>Wilcoxon p</th><th>P1 consult wait</th><th>P5 95th pct wait</th></tr></thead>
        <tbody>{Object.entries(sim.mean_journey_wait || {}).map(([policy, mean]: [string, any]) => { const t = sim.paired_vs_fcfs?.[policy]; const b = sim.bottom_of_queue?.[policy]; return <tr key={policy}><td>{policy.replaceAll("_", " ").toLowerCase()}</td><td className="mono">{n(mean)}</td><td className="mono">{t ? `${n(t.mean_difference, 2)} (${t.ci95 ? `${n(t.ci95[0], 2)}, ${n(t.ci95[1], 2)}` : "—"})` : "reference"}</td><td className="mono">{t ? p(t.wilcoxon_p_value) : "—"}</td><td className="mono">{n(b?.P1_mean_consultation_wait)}</td><td className="mono">{n(b?.P5_p95_wait)}</td></tr>; })}</tbody></table></div></> : <p className="muted">No completed simulation yet.</p>}
    <h3 style={{ margin: 0 }}>Usability and acceptance</h3>
    <section className="metric-grid">
      <article className="metric"><p>Mean SUS</p><strong>{acc.sus.mean ?? "—"}</strong><small>n={acc.sus.n}{acc.sus.ci95 ? ` · 95% CI ${acc.sus.ci95[0]}–${acc.sus.ci95[1]}` : ""}</small></article>
      <article className="metric"><p>Perceived usefulness</p><strong>{acc.tam.perceived_usefulness.mean ?? "—"}</strong><small>of 7 · n={acc.tam.perceived_usefulness.n}</small></article>
      <article className="metric"><p>Perceived ease of use</p><strong>{acc.tam.perceived_ease_of_use.mean ?? "—"}</strong><small>of 7 · n={acc.tam.perceived_ease_of_use.n}</small></article>
      <article className="metric"><p>PU–PEOU correlation</p><strong>{acc.tam.pu_peou_correlation ? n(acc.tam.pu_peou_correlation.spearman_rho, 2) : "—"}</strong><small>Spearman ρ{acc.tam.pu_peou_correlation ? `, p ${p(acc.tam.pu_peou_correlation.p_value)}` : " (needs 5+)"}</small></article>
    </section>
  </div>;
}

export function Evaluation() {
  const [report, setReport] = useState<Report | null>(null), [error, setError] = useState("");
  const load = () => api<Report>("/api/v1/research/evaluation").then(setReport).catch((e) => setError(errorText(e)));
  useEffect(() => { load(); }, []);
  if (!report) return error ? <p className="error" role="alert">{error}</p> : <Loading text="Assembling evidence…" />;
  return <>
    <div className="warning-card"><strong>{report.research_label}</strong><p>Generated {formatTime(report.generated_at)}. Each objective lists what the proposal requires, what the system holds as evidence, and what still has to happen outside the software.</p></div>
    <nav className="cluster" aria-label="Objectives" style={{ marginBottom: 16 }}>{report.objectives.map((o) => <a key={o.id} href={`#${o.id}`} className="button secondary small"><span className="mono">{o.id}</span><StatusChip status={STATUS[o.status].chip} label={STATUS[o.status].label} /></a>)}
      <button className="ghost small" onClick={load}><Icon name="refresh" />Refresh</button>
      <a className="button ghost small" href={`${API_URL}/api/v1/research/evaluation`} target="_blank" rel="noreferrer"><Icon name="download" />JSON</a></nav>
    <div className="stack">{report.objectives.map((o) => <article key={o.id} id={o.id} className="panel objective">
      <header><div><p className="eyebrow mono">{o.id} · Objective</p><h2>{o.objective}</h2><p className="muted" style={{ margin: 0 }}><em>Research question:</em> {o.research_question}</p></div><StatusChip status={STATUS[o.status].chip} label={STATUS[o.status].label} /></header>
      <p className="refs">Proposal: {o.proposal_refs.join(" · ")}</p>
      <div className="two-column" style={{ alignItems: "start" }}>
        <div><h3>What the proposal requires</h3><Requirements items={o.requirements} />{o.outside_system && <><h3 style={{ marginTop: 14 }}>Outside the software</h3><ul className="prose" style={{ margin: 0 }}>{o.outside_system.map((x) => <li key={x}>{x}</li>)}</ul></>}</div>
        <div><h3>Evidence held</h3><ObjectiveEvidence objective={o} /></div>
      </div>
    </article>)}</div>
    <article className="panel spaced"><h2>Limitations</h2><ul className="prose">{report.limitations.map((x) => <li key={x}>{x}</li>)}</ul></article>
    <FeedbackPanel />
  </>;
}
