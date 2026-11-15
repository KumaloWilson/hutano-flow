"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, API_URL, formatTime } from "@/lib/api";
import type { AdjudicationResponse, CaseResponse, OperationsStudyConfig, ProtocolDetail, ProtocolResponse, ResearchRunQueued, StudyRunResponse, TrialResponse, WorkbenchOverview } from "@/lib/generated";
import "./research-workbench.css";

// API envelopes come from OpenAPI; engine-specific metrics remain versioned JSON.
// These types do not grant access: every endpoint independently checks roles.
type RecordValue = Record<string, unknown>;
type Dataset = { id: string; name: string; row_count: number; schema: RecordValue };
type Model = { id: string; version: string; status: string; dataset_id?: string; metrics: RecordValue };
type OperationsConfig = Required<OperationsStudyConfig>;
type Protocol = ProtocolResponse;
type Overview = Omit<WorkbenchOverview, "datasets" | "models"> & { datasets: Dataset[]; models: Model[] };
type StudyCase = CaseResponse;
type Advisory = { suggestion?: string | null; confidence?: number | null; abstained?: boolean; reasons?: string[]; warning?: string; factors?: unknown; contrastive?: unknown };
type Trial = Omit<TrialResponse, "advisory"> & { advisory: Advisory | null };
type Run = Pick<StudyRunResponse, "id" | "status"> & Partial<Omit<StudyRunResponse, "id" | "status">>;
type Detail = Omit<ProtocolDetail, "trials"> & { trials: Trial[] };
type Adjudication = AdjudicationResponse;
const ROOT = "/api/v1/research/workbench";
const LABELS = ["P1", "P2", "P3", "P4", "P5"];
const OPERATIONS: OperationsConfig = { seed: 2026, training_days: 40, test_days: 12, arrivals_per_day: 50, replications: 10, shift_strength: 1, missing_rate: 0 };
const record = (value: unknown): RecordValue => value && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {};
const rows = (value: unknown): RecordValue[] => Array.isArray(value) ? value.map(record) : [];
const number = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value : null;
const text = (value: unknown) => value == null ? "Not available" : typeof value === "object" ? JSON.stringify(value) : String(value);
const decimal = (value: unknown, digits = 2) => number(value)?.toFixed(digits) ?? "—";
const percent = (value: unknown) => number(value) == null ? "—" : `${decimal(Number(value) * 100, 1)}%`;
const title = (value: string) => value.replaceAll("_", " ");
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Research action failed. Refresh and try again.";

export function ResearchWorkbench({ roles }: { roles: string[] }) {
  const research = roles.some(role => ["RESEARCHER", "ADMIN"].includes(role));
  const reviewer = roles.some(role => ["CLINICIAN", "TRIAGE_NURSE"].includes(role));
  const [overview, setOverview] = useState<Overview | null>(null);
  const [selected, setSelected] = useState("");
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const [detail, setDetail] = useState<Detail | null>(null);
  const [monitor, setMonitor] = useState<RecordValue | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadOverview = useCallback(async () => {
    const result = await api<Overview>(`${ROOT}/overview`);
    setOverview(result);
    return result;
  }, []);
  const loadDetail = useCallback(async (id: string) => {
    const result = await api<Detail>(`${ROOT}/protocols/${id}`);
    if (selectedRef.current === id) setDetail(result);
    if (research) {
      const report = await api<RecordValue>(`${ROOT}/protocols/${id}/monitor`);
      if (selectedRef.current === id) setMonitor(report);
    }
  }, [research]);

  useEffect(() => {
    let active = true;
    loadOverview().catch(e => { if (active) setError(errorMessage(e)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [loadOverview]);
  useEffect(() => {
    setDetail(null); setMonitor(null); setRun(null); setError("");
    if (!selected) return;
    loadDetail(selected).catch(e => setError(errorMessage(e)));
    const timer = window.setInterval(() => { loadDetail(selected).catch(e => setError(errorMessage(e))); }, 10000);
    return () => window.clearInterval(timer);
  }, [selected, loadDetail]);
  useEffect(() => {
    if (!run || !["QUEUED", "RUNNING", "PENDING"].includes(run.status)) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const updated = await api<Run>(`${ROOT}/runs/${run.id}`);
        if (active) {
          setRun(updated);
          if (!["QUEUED", "RUNNING", "PENDING"].includes(updated.status)) await loadDetail(selected);
        }
      } catch (e) { if (active) setError(errorMessage(e)); }
    }, 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [run?.id, run?.status, selected, loadDetail]);

  async function action(work: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function refresh() {
    await action(async () => {
      await loadOverview();
      if (selected) await loadDetail(selected);
      setNotice("Research records refreshed from the server.");
    });
  }
  async function created(protocol: Protocol) {
    await loadOverview();
    selectedRef.current = protocol.id;
    setSelected(protocol.id);
    setNotice("Immutable research protocol saved. It does not change any clinical queue or activate a model.");
  }
  async function queueOperations() {
    if (!selected) return;
    await action(async () => {
      const queued = await api<ResearchRunQueued>(`${ROOT}/protocols/${selected}/operations`, { method: "POST", body: "{}" });
      setRun({ id: queued.run_id, status: queued.status });
      await loadDetail(selected);
      setNotice(`Operations study queued (${queued.job_id.slice(0, 8)}). Its durable worker continues if you leave this page.`);
    });
  }

  if (!research && !reviewer) return <article className="panel"><h2>Research workbench</h2><p>Your role does not have access to this research workspace.</p></article>;
  return <div className="research-workbench">
    <article className="panel">
      <div className="panel-head"><div><p className="eyebrow">Evidence before claims</p><h2>AI research workbench</h2></div><button className="secondary" disabled={busy || loading} onClick={refresh}>Refresh research records</button></div>
      <p>Freeze a study protocol, preserve independent case reviews, evaluate advisory uncertainty, and compare resource plans on held-out synthetic days.</p>
      <p className="callout caution">Research prototype — not for clinical use. Synthetic labels and simulated waits do not establish clinical accuracy or real-world benefit. No action here changes a patient’s priority, staffing or model activation.</p>
      {overview?.warning && <p className="warning-text">{overview.warning}</p>}
      {notice && <p className="callout" role="status">{notice}</p>}
      {error && <p className="callout caution" role="alert">{error}</p>}
      {loading ? <p role="status">Loading research records…</p> : overview && <label>Saved research protocol<select aria-label="Saved research protocol" value={selected} onChange={e => setSelected(e.target.value)}><option value="">Choose a protocol</option>{overview.protocols.map(p => <option key={p.id} value={p.id}>{p.name} · {title(p.design)}</option>)}</select></label>}
      {!loading && overview?.protocols.length === 0 && <p>No protocols have been saved. {research ? "Define a synthetic study below." : "Ask a researcher to prepare a synthetic study before reviewing cases."}</p>}
    </article>

    {research && overview && <>
      <details className="panel spaced" open={!selected}>
        <summary>Define a new immutable protocol</summary>
        <ProtocolForm overview={overview} busy={busy} action={action} created={created} />
      </details>
      <DatasetEvidence overview={overview} />
      <CalibrationEvidence models={overview.models} />
    </>}

    {selected && !detail && <p role="status" className="panel spaced">Loading the saved protocol…</p>}
    {detail && <>
      <article className="panel spaced">
        <div className="panel-head"><div><p className="eyebrow">Immutable protocol</p><h2>{detail.protocol.name}</h2></div>{research && <ExportLinks path={`/protocols/${detail.protocol.id}/export`} />}</div>
        <p>{detail.protocol.question}</p><p>{title(detail.protocol.design)} · {detail.protocol.case_count} synthetic cases · saved {formatTime(detail.protocol.created_at)}</p>
        <p className="hash">SHA-256 {detail.protocol.config_hash}</p>
        <p>Independent reviews are kept separate from participant decisions. Acceptance of a suggestion is not treated as ground truth. A saved protocol is not ethics approval or evidence that a human study has taken place.</p>
        {research && <StudyEvidence summary={detail.summary} />}
      </article>

      {reviewer && <>
        <BlindedReviews key={`reviews-${selected}`} cases={detail.cases} busy={busy} action={action} changed={() => loadDetail(selected)} />
        <ParticipantTrial key={`trials-${selected}`} protocol={detail.protocol} trials={detail.trials} busy={busy} action={action} changed={() => loadDetail(selected)} />
      </>}

      {research && <>
        <article className="panel spaced">
          <div className="panel-head"><div><p className="eyebrow">Supporting human-factors analysis</p><h2>Shadow monitoring & study evidence</h2></div></div>
          <p>Only recorded, consented synthetic-case responses appear here. Empty denominators are not zero error. Differences across arms are descriptive unless the study design and sample size justify inference.</p>
          {monitor ? <MonitoringEvidence report={monitor} /> : <p>Loading study monitoring…</p>}
        </article>
        <article className="panel spaced">
          <div className="panel-head"><div><p className="eyebrow">Supporting consultation-stage experiment</p><h2>Waiting uncertainty & forecast-informed planning</h2></div></div>
          <p>Evaluate the saved configuration using separated development, calibration and evaluation data. Compare fixed rooms, pooling, historical-average planning and forecast-informed planning under the same staffing budget. The original whole-journey FCFS / urgency / hybrid study remains the primary Objective 4 experiment.</p>
          <SummaryTable value={detail.protocol.operations_config} caption="Frozen operations study settings" />
          <button className="primary" disabled={busy} onClick={queueOperations}>Run saved operations study</button>
          <h3>Durable study runs</h3>
          {!detail.runs.length && <p>No operations runs yet. Running a study does not change the facility’s live resource schedule.</p>}
          <div className="rw-run-list">{detail.runs.map(item => <div className="rw-run" key={item.id}><div><strong>{item.id.slice(0, 8)}</strong><p>{item.status} · {formatTime(item.created_at)}</p>{item.error && <p className="warning-text">{item.error}</p>}</div><button className="secondary" disabled={busy} onClick={() => action(async () => { setRun(await api<Run>(`${ROOT}/runs/${item.id}`)); })}>Inspect run {item.id.slice(0, 8)}</button></div>)}</div>
        </article>
        {run && <OperationsEvidence run={run} />}
      </>}
    </>}
  </div>;
}

function ProtocolForm({ overview, busy, action, created }: { overview: Overview; busy: boolean; action: (work: () => Promise<void>) => Promise<void>; created: (protocol: Protocol) => Promise<void> }) {
  const [datasetId, setDatasetId] = useState(overview.datasets[0]?.id ?? "");
  const [modelId, setModelId] = useState("");
  const [design, setDesign] = useState("MANUAL_ONLY");
  const [config, setConfig] = useState<OperationsConfig>({ ...OPERATIONS });
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    await action(async () => {
      const protocol = await api<Protocol>(`${ROOT}/protocols`, { method: "POST", body: JSON.stringify({ name: String(values.get("name")).trim(), question: String(values.get("question")).trim(), dataset_id: datasetId, model_id: modelId || null, design, case_count: Number(values.get("cases")), seed: config.seed, operations_config: config }) });
      await created(protocol);
    });
  }
  const field = (key: keyof OperationsConfig, label: string, minimum: number, maximum: number, step = 1) => <label key={key}>{label}<input required type="number" min={minimum} max={maximum} step={step} value={config[key]} onChange={e => setConfig({ ...config, [key]: Number(e.target.value) })} /></label>;
  return <form onSubmit={submit} className="form-grid rw-protocol-form">
    <p className="span-2">Freeze the research question and configuration before collecting responses. Revisions are new protocols; existing responses are never silently relabelled. Use coded consent references, not participant names.</p>
    <label className="span-2">Protocol name<input name="name" minLength={5} maxLength={120} required defaultValue="Synthetic advisory reliability and waiting-time study" /></label>
    <label className="span-2">Research question<textarea name="question" required minLength={15} maxLength={1000} defaultValue="Does calibrated advisory uncertainty support appropriate independent decisions, and does forecast-informed planning reduce simulated waiting beyond pooling and historical-average planning?" /></label>
    <label>Synthetic source dataset<select aria-label="Synthetic source dataset" required value={datasetId} onChange={e => { setDatasetId(e.target.value); setModelId(""); setDesign("MANUAL_ONLY"); }}><option value="">Choose a dataset</option>{overview.datasets.map(d => <option value={d.id} key={d.id}>{d.name} · {d.row_count} rows</option>)}</select></label>
    <label>Frozen advisory model<select aria-label="Frozen advisory model" value={modelId} onChange={e => { setModelId(e.target.value); if (!e.target.value) setDesign("MANUAL_ONLY"); }}><option value="">No advisory model · manual-only</option>{overview.models.filter(m => !m.dataset_id || m.dataset_id === datasetId).map(m => <option value={m.id} key={m.id} disabled={m.status !== "REVIEWED"}>{m.version} · {m.status}</option>)}</select></label>
    <p className="span-2 rw-muted">Advisory studies require a clinician-reviewed model trained on the selected dataset. Training and review stay in the existing AI research and clinician review workflows; this form never activates a model.</p>
    <label>Human study design<select aria-label="Human study design" value={design} onChange={e => setDesign(e.target.value)}><option value="MANUAL_ONLY">Manual-only independent assessment</option><option value="COUNTERBALANCED" disabled={!modelId}>Counterbalanced manual / advisory / explanation</option><option value="SHADOW" disabled={!modelId}>Shadow · reveal only after decision</option></select></label>
    <label>Cases reserved for this protocol<input name="cases" type="number" min={6} max={100} defaultValue={24} required /></label>
    <fieldset className="span-2"><legend>Frozen operations and robustness configuration</legend><div className="form-grid">
      {field("seed", "Study random seed", 0, 1000000000)}
      {field("training_days", "Synthetic development days", 28, 90)}
      {field("test_days", "Held-out synthetic evaluation days", 4, 30)}
      {field("arrivals_per_day", "Mean synthetic arrivals / day", 20, 150)}
      {field("replications", "Paired operational replications", 2, 40)}
      {field("shift_strength", "Synthetic distribution shift strength", 0, 2, .1)}
      {field("missing_rate", "Synthetic missing-feature fraction", 0, .5, .05)}
    </div><p>These are experimental assumptions, not measured facility conditions. Select replication count and precision targets before final analysis; increasing runs does not guarantee an improvement.</p></fieldset>
    <button className="primary span-2" disabled={busy || !datasetId}>Save immutable research protocol</button>
    {!overview.datasets.length && <p className="span-2">Create or import an approved synthetic dataset in AI research before saving a protocol.</p>}
  </form>;
}

function DatasetEvidence({ overview }: { overview: Overview }) {
  const [selectedId, setSelectedId] = useState("");
  const dataset = overview.datasets.find(d => d.id === selectedId) ?? overview.datasets[0];
  const schema = record(overview.feature_schema);
  const features = record(schema.metadata ?? schema.feature_metadata ?? schema.features ?? schema);
  return <details className="panel spaced"><summary>Dataset provenance & feature definitions</summary>
    <p>Recorded measurement is a dimensionless generated proxy. It is not a pulse, temperature or other clinical measurement. Missing values remain missing; the workbench does not invent normal observations.</p>
    <div className="table-wrap"><table><caption>Versioned synthetic feature dictionary</caption><thead><tr><th>Feature</th><th>Definition / allowed values</th><th>Unit</th><th>Available at prediction</th></tr></thead><tbody>{Object.entries(features).filter(([, value]) => value && typeof value === "object" && !Array.isArray(value)).map(([key, value]) => { const item = record(value); return <tr key={key}><th scope="row">{title(key)}</th><td>{text(item.definition ?? item.description ?? item.meaning ?? item.values ?? title(key))}</td><td>{item.unit == null ? "Categorical / unitless" : text(item.unit)}</td><td>{text(item.available_at ?? item.prediction_time_availability)}</td></tr>; })}</tbody></table></div>
    {dataset && <><label>Inspect dataset quality<select aria-label="Inspect dataset quality" value={dataset.id} onChange={e => setSelectedId(e.target.value)}>{overview.datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label><p>{dataset.row_count} rows · synthetic labels, not independently validated clinical labels.</p><SummaryTable value={dataset.schema} caption="Dataset quality and provenance" /></>}
    <JsonDetails title="Full feature schema" value={overview.feature_schema} />
  </details>;
}

function CalibrationEvidence({ models }: { models: Model[] }) {
  const [selectedId, setSelectedId] = useState("");
  const model = models.find(m => m.id === selectedId) ?? models[0];
  const reliability = record(model?.metrics.reliability_research);
  const raw = record(reliability.raw ?? reliability.uncalibrated ?? reliability.raw_test);
  const calibrated = record(reliability.calibrated ?? reliability.calibrated_test);
  return <details className="panel spaced"><summary>Calibration, selective prediction & model diagnostics</summary>
    {!model ? <p>No trained model yet. The AI research screen can train a local synthetic classifier; the operational queue works without it.</p> : <>
      <label>Inspect research model<select aria-label="Inspect research model" value={model.id} onChange={e => setSelectedId(e.target.value)}>{models.map(m => <option key={m.id} value={m.id}>{m.version}</option>)}</select></label>
      <p className="warning-text">Synthetic-label agreement only. Calibrated probabilities and abstention are not clinical safety guarantees.</p>
      {!Object.keys(reliability).length ? <p>This model predates the separated reliability study. Train a new synthetic model to obtain calibration, risk–coverage and robustness evidence; old artifacts remain unchanged.</p> : <>
        <SummaryTable value={reliability} caption="Reliability protocol and partitions" scalarsOnly />
        {(Object.keys(raw).length > 0 || Object.keys(calibrated).length > 0) && <div className="table-wrap"><table><caption>Untouched evaluation probabilities</caption><thead><tr><th>Probability version</th><th>Log loss</th><th>Multiclass Brier score</th><th>Calibration error</th></tr></thead><tbody>{[["Uncalibrated", raw], ["Calibrated", calibrated]].map(([label, value]) => { const item = value as RecordValue; return <tr key={String(label)}><th scope="row">{String(label)}</th><td>{decimal(item.log_loss)}</td><td>{decimal(item.brier_score ?? item.multiclass_brier_score)}</td><td>{decimal(item.expected_calibration_error ?? item.ece)}</td></tr>; })}</tbody></table></div>}
        <ReliabilityCurves metrics={reliability} />
        <ReliabilityStudyTables metrics={reliability} />
        <JsonDetails title="Full calibration, learning-curve and robustness evidence" value={reliability} />
      </>}
      <JsonDetails title="Complete versioned model report" value={model.metrics} />
    </>}
  </details>;
}

function ReliabilityCurves({ metrics }: { metrics: RecordValue }) {
  const source = record(metrics.risk_coverage ?? metrics.risk_coverage_curves);
  const raw = rows(record(metrics.raw_risk_coverage).overall ?? source.raw ?? source.uncalibrated ?? metrics.raw_risk_coverage);
  const calibrated = rows(source.overall ?? source.calibrated ?? metrics.calibrated_risk_coverage);
  if (!raw.length && !calibrated.length) return null;
  const series = [{ name: "Uncalibrated", data: raw, color: "#9a5e19", dashed: true }, { name: "Calibrated", data: calibrated, color: "#1f5c4d", dashed: false }];
  const risk = (row: RecordValue) => number(row.risk ?? row.error_rate ?? row.selective_error);
  return <section className="rw-chart"><h3>Risk–coverage trade-off</h3><p>Coverage is the fraction receiving a suggestion; risk is disagreement among those suggestions. Every case still requires independent judgement.</p>
    <svg viewBox="0 0 620 260" role="img" aria-label="Synthetic-label error rate against fraction receiving a suggestion"><line x1="55" x2="595" y1="215" y2="215" stroke="#607068" /><line x1="55" x2="55" y1="20" y2="215" stroke="#607068" /><text x="12" y="25">100%</text><text x="20" y="215">0%</text><text x="55" y="236">0%</text><text x="560" y="236">100%</text><text x="240" y="257">Suggestion coverage</text>{series.map(s => <path key={s.name} d={s.data.filter(r => number(r.coverage) !== null && risk(r) !== null).sort((a, b) => Number(a.coverage) - Number(b.coverage)).map((r, index) => `${index ? "L" : "M"}${55 + Number(r.coverage) * 540},${215 - Number(risk(r)) * 195}`).join(" ")} fill="none" stroke={s.color} strokeWidth="3" strokeDasharray={s.dashed ? "7 5" : undefined} />)}</svg>
    <p>Solid green: calibrated. Dashed amber: uncalibrated. Exact values and empty denominators are retained below.</p>
    <details><summary>Risk–coverage values</summary><div className="table-wrap"><table><thead><tr><th>Version</th><th>Threshold</th><th>Coverage</th><th>Error among suggestions</th><th>Suggestions</th></tr></thead><tbody>{series.flatMap(s => s.data.map((r, i) => <tr key={`${s.name}-${i}`}><th scope="row">{s.name}</th><td>{decimal(r.threshold)}</td><td>{percent(r.coverage)}</td><td>{percent(risk(r))}</td><td>{text(r.accepted_n ?? r.accepted ?? r.accepted_count)}</td></tr>))}</tbody></table></div></details>
  </section>;
}

function ReliabilityStudyTables({ metrics }: { metrics: RecordValue }) {
  const partitions = record(metrics.partitions);
  const selected = record(metrics.selected_threshold_test);
  const threshold = record(metrics.threshold_selection);
  const learning = rows(metrics.learning_curves);
  const stress = rows(record(metrics.stress_tests).scenarios);
  const stability = rows(record(metrics.explanation_stability).perturbations);
  const monitoring = rows(record(metrics.monitoring_challenge).scenarios);
  const interval = (value: unknown) => Array.isArray(value) ? value.map(v => percent(v)).join(" to ") : "Not estimable";
  return <>
    <p className="callout">Selected advisory threshold {decimal(threshold.threshold)}; held-out suggestion coverage {percent(selected.coverage)} (95% interval {interval(selected.coverage_ci95)}), synthetic-label error among suggestions {percent(selected.risk)} (95% interval {interval(selected.risk_ci95)}). {text(selected.accepted_n)} suggestions from {text(selected.n)} evaluated cases. Withholding a suggestion is not withholding clinician review.</p>
    <div className="table-wrap"><table><caption>Separated chronological partitions</caption><thead><tr><th>Partition</th><th>Rows</th><th>Start</th><th>End</th></tr></thead><tbody>{Object.entries(partitions).map(([key, value]) => { const item = record(value); return <tr key={key}><th scope="row">{title(key)}</th><td>{text(item.rows)}</td><td>{text(item.start)}</td><td>{text(item.end)}</td></tr>; })}</tbody></table></div>
    {learning.length > 0 && <div className="table-wrap"><table><caption>Learning curves · fixed development evaluation set</caption><thead><tr><th>Fit rows</th><th>Evaluation rows</th><th>Macro-F1</th><th>Accuracy</th><th>Accuracy 95% interval</th></tr></thead><tbody>{learning.map((row, index) => <tr key={index}><td>{text(row.fit_rows)}</td><td>{text(row.evaluation_rows)}</td><td>{decimal(row.macro_f1)}</td><td>{percent(row.accuracy)}</td><td>{interval(row.accuracy_ci95)}</td></tr>)}</tbody></table></div>}
    {stress.length > 0 && <div className="table-wrap"><table><caption>Deliberately shifted synthetic evaluation inputs</caption><thead><tr><th>Scenario</th><th>Suggestion coverage</th><th>Selective error</th><th>Input guard flags</th><th>Full classifier error</th></tr></thead><tbody>{stress.map((row, index) => <tr key={index}><th scope="row">{title(text(row.scenario))}</th><td>{percent(row.coverage)}</td><td>{percent(row.risk)}</td><td>{percent(row.input_guard_flag_rate)}</td><td>{percent(row.full_classifier_error_rate)}</td></tr>)}</tbody></table></div>}
    {stability.length > 0 && <div className="table-wrap"><table><caption>Explanation stability under declared perturbations</caption><thead><tr><th>Perturbed feature</th><th>Label agreement</th><th>Abstention agreement</th><th>Mean probability change</th></tr></thead><tbody>{stability.map((row, index) => <tr key={index}><th scope="row">{text(row.field)}</th><td>{percent(row.predicted_label_agreement)}</td><td>{percent(row.abstention_decision_agreement)}</td><td>{decimal(row.mean_absolute_confidence_change, 4)}</td></tr>)}</tbody></table></div>}
    {monitoring.length > 0 && <div className="table-wrap"><table><caption>Offline monitoring challenge · false alarms and missed detections retained</caption><thead><tr><th>Scenario</th><th>Input false-alarm fraction</th><th>Delayed-error false-alarm fraction</th><th>Input detections / replications</th><th>Mean input delay (windows)</th><th>Delayed-error detections / replications</th></tr></thead><tbody>{monitoring.map((row, index) => <tr key={index}><th scope="row">{title(text(row.scenario))}</th><td>{percent(row.input_false_alarm_fraction)}</td><td>{percent(row.delayed_error_false_alarm_fraction)}</td><td>{text(row.input_detections)} / {text(row.replications)}</td><td>{decimal(row.mean_input_delay_windows)}</td><td>{text(row.delayed_error_detections)} / {text(row.replications)}</td></tr>)}</tbody></table></div>}
    <p>Learning curves use development data; final test data must not drive model or threshold changes. Stability does not establish causal explanations or clinical usefulness. Monitoring alarms are evaluated offline, not automatic activation or clinical safety gates.</p>
  </>;
}

function BlindedReviews({ cases, busy, action, changed }: { cases: StudyCase[]; busy: boolean; action: (work: () => Promise<void>) => Promise<void>; changed: () => Promise<void> }) {
  const [selectedId, setSelectedId] = useState("");
  const selected = cases.find(c => c.id === selectedId) ?? cases[0];
  const [adjudication, setAdjudication] = useState<Adjudication | null>(null);
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>, kind: "reviews" | "adjudication") {
    event.preventDefault(); if (!selected) return;
    const values = new FormData(event.currentTarget);
    await action(async () => {
      await api(`${ROOT}/cases/${selected.id}/${kind}`, { method: "POST", body: JSON.stringify({ label: values.get("label"), reason: String(values.get("reason")).trim() }) });
      setMessage(kind === "reviews" ? "Your independent review is saved. Other reviews and model suggestions were not revealed." : "Two-reviewer consensus saved; original independent reviews are preserved.");
      setAdjudication(null);
      await changed();
    });
  }
  return <article className="panel spaced">
    <p className="eyebrow">Independent reference review</p><h2>Blinded synthetic-case review</h2>
    <p>Assess the displayed synthetic features without seeing the source label, another reviewer’s answer or the model. Reviews are immutable. Cases you review are excluded from your own participant trials.</p>
    {message && <p className="callout" role="status">{message}</p>}
    {!selected ? <p>No synthetic cases are available in this protocol.</p> : <>
      <label>Blinded case<select aria-label="Blinded case" value={selected.id} disabled={busy} onChange={e => { setSelectedId(e.target.value); setAdjudication(null); setMessage(""); }}>{cases.map(c => <option key={c.id} value={c.id}>Case {c.ordinal} · {c.review_count} independent reviews{c.own_review ? " · reviewed by you" : ""}{c.adjudicated ? " · adjudicated" : ""}</option>)}</select></label>
      <FeatureValues features={selected.features} />
      {selected.own_review ? <p className="callout">Your saved review: {selected.own_review.label}. {selected.own_review.reason}</p> : !selected.adjudicated && selected.review_count < 2 ? <LabelForm key={selected.id} onSubmit={event => submit(event, "reviews")} disabled={busy} prefix="Independent review" submit="Save blinded independent review" /> : <p>The two blinded reference reviews are complete.</p>}
      <h3>Two-reviewer consensus</h3><p>After both blinded reviews are saved, either original reviewer can inspect the pair and record a reasoned consensus. This is not independent third-rater adjudication or a clinical gold standard.</p>
      {selected.adjudicated ? <p>Reference consensus has already been recorded.</p> : <button className="secondary" disabled={busy || selected.review_count < 2 || !selected.own_review} onClick={() => action(async () => { setAdjudication(await api<Adjudication>(`${ROOT}/cases/${selected.id}/adjudication`)); })}>Open two-reviewer consensus</button>}
      {adjudication && <section className="rw-adjudication"><h3>Review evidence for case {selected.ordinal}</h3><ol>{adjudication.reviews.map((review, index) => <li key={index}><strong>Review {index + 1}: {review.label}</strong><p>{review.reason}</p></li>)}</ol>{adjudication.adjudication ? <p>Saved reference: {adjudication.adjudication.label} · {adjudication.adjudication.reason}</p> : <LabelForm onSubmit={event => submit(event, "adjudication")} disabled={busy} prefix="Consensus reference" submit="Save two-reviewer consensus" />}</section>}
    </>}
  </article>;
}

function ParticipantTrial({ protocol, trials, busy, action, changed }: { protocol: Protocol; trials: Trial[]; busy: boolean; action: (work: () => Promise<void>) => Promise<void>; changed: () => Promise<void> }) {
  const [trial, setTrial] = useState<Trial | null>(() => trials.find(t => t.status === "STARTED") ?? null);
  const [consented, setConsented] = useState(false);
  const [consent, setConsent] = useState("");
  useEffect(() => { const active = trials.find(t => t.status === "STARTED"); if (active) setTrial(previous => previous?.id === active.id ? previous : active); }, [trials]);
  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await action(async () => { setTrial(await api<Trial>(`${ROOT}/protocols/${protocol.id}/trials/start`, { method: "POST", body: JSON.stringify({ consented, consent_ref: consent.trim() }) })); await changed(); });
  }
  async function complete(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!trial) return;
    const values = new FormData(event.currentTarget);
    await action(async () => {
      const result = await api<Trial>(`${ROOT}/trials/${trial.id}/complete`, { method: "POST", body: JSON.stringify({ label: values.get("label"), reason: String(values.get("reason")).trim(), understands_authority: values.get("authority") === "yes", trust_rating: Number(values.get("trust")) }) });
      setTrial(result); await changed();
    });
  }
  const visibleAdvice = trial?.advisory && (["ADVISORY", "EXPLANATION"].includes(trial.arm) || trial.status === "COMPLETED");
  return <article className="panel spaced">
    <p className="eyebrow">Consented synthetic exercise</p><h2>Independent participant trial</h2>
    <p>Use this only with the study’s agreed consent process. A coded consent reference is not consent approval. Assignment is server-controlled; do not rehearse the same case in reference review and a participant trial.</p>
    {(!trial || trial.status === "COMPLETED") && <form onSubmit={start} className="form-grid"><label>Participant consent reference<input value={consent} onChange={e => setConsent(e.target.value)} minLength={5} maxLength={160} required placeholder="Coded record, not a participant name" /></label><label className="rw-checkbox"><input type="checkbox" checked={consented} onChange={e => setConsented(e.target.checked)} required />The participant has consented to this synthetic exercise</label><button className="primary span-2" disabled={busy || !consented}>{trial ? "Start next assigned trial" : "Start assigned participant trial"}</button></form>}
    {trial && <section className="rw-trial" aria-label="Assigned participant case">
      <p><span className="badge">{trial.arm}</span> Case {trial.ordinal} · {trial.status} · started {formatTime(trial.started_at)}</p>
      <FeatureValues features={trial.features} />
      {!visibleAdvice && <p className="callout">{trial.arm === "SHADOW" ? "Shadow mode: the model output is hidden until your independent decision has been saved." : "Manual assessment: no advisory output is shown."}</p>}
      {visibleAdvice && <AdvisoryEvidence advisory={trial.advisory!} explanation={trial.arm === "EXPLANATION" || trial.status === "COMPLETED"} />}
      {trial.status === "STARTED" ? <form key={trial.id} onSubmit={complete} className="form-grid"><label>Participant final label<select aria-label="Participant final label" name="label" defaultValue="" required><option value="" disabled>Choose independently</option>{LABELS.map(label => <option key={label}>{label}</option>)}</select></label><label>Self-reported trust rating<select aria-label="Self-reported trust rating" name="trust" defaultValue="" required><option value="" disabled>Choose a response</option>{[1, 2, 3, 4, 5].map(value => <option key={value} value={value}>{value} · {value === 1 ? "very low" : value === 5 ? "very high" : "intermediate"}</option>)}</select></label><label className="span-2">Participant decision rationale<textarea name="reason" minLength={5} maxLength={500} required /></label><label className="span-2">Does the human retain final decision authority?<select aria-label="Does the human retain final decision authority?" name="authority" defaultValue="" required><option value="" disabled>Record the participant’s response</option><option value="yes">Yes</option><option value="no">No / unsure</option></select></label><button className="primary span-2" disabled={busy}>Save independent trial decision</button></form> : <p className="callout" role="status">Decision saved: {trial.final_label}. Recorded task time: {decimal(trial.elapsed_seconds, 1)} seconds. Time includes any pause or interruption; it is not automatically a measure of clinical efficiency.</p>}
    </section>}
    <p>{trials.filter(t => t.status === "COMPLETED").length} completed responses recorded for you in this protocol. These are not an independent clinical validation cohort.</p>
  </article>;
}

function AdvisoryEvidence({ advisory, explanation }: { advisory: Advisory; explanation: boolean }) {
  return <section className="rw-advisory"><h3>Experimental advisory</h3><p>{advisory.abstained ? "Suggestion withheld — independent review required" : `Suggested synthetic label: ${advisory.suggestion ?? "unavailable"}`}</p><p>Model probability: {percent(advisory.confidence)}. Not a clinical safety certificate.</p><p className="warning-text">{advisory.warning || "EXPERIMENTAL — NOT VALIDATED FOR PATIENT CARE"}</p>{advisory.reasons?.length ? <ul>{advisory.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul> : null}{explanation && <><ExplanationValues value={advisory.factors} heading="Local model contributions" /><ExplanationValues value={advisory.contrastive} heading="Why this synthetic category rather than the alternative?" /></>}</section>;
}

function ExplanationValues({ value, heading }: { value: unknown; heading: string }) {
  if (value == null) return <p>No {heading.toLowerCase()} available for this artifact.</p>;
  if (Array.isArray(value)) return <section><h4>{heading}</h4><div className="table-wrap"><table><thead><tr><th>Feature</th><th>Contribution / evidence</th></tr></thead><tbody>{value.map((item, index) => { const factor = record(item); return <tr key={index}><th scope="row">{text(factor.feature ?? factor.name ?? index + 1)}</th><td>{text(factor.contribution ?? factor.logit_contribution ?? factor.logit_difference_contribution ?? factor.value ?? item)}</td></tr>; })}</tbody></table></div></section>;
  const item = record(value);
  return <section><h4>{heading}</h4><SummaryTable value={item} caption={heading} scalarsOnly />{Array.isArray(item.factors) && <ExplanationValues value={item.factors} heading="Contributions to the between-class logit difference" />}</section>;
}

function StudyEvidence({ summary }: { summary: RecordValue }) {
  const arms = rows(summary.arms);
  const confusion = Array.isArray(summary.pair_confusion_matrix) ? summary.pair_confusion_matrix as number[][] : [];
  return <>
    <SummaryTable value={summary} caption="Recorded review and study progress" scalarsOnly />
    {number(summary.paired_cases) !== null && Number(summary.paired_cases) > 0 && <div className="table-wrap"><table><caption>First blinded reviewer × second blinded reviewer · counts</caption><thead><tr><th>First / second</th>{LABELS.map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{confusion.map((values, index) => <tr key={index}><th scope="row">{LABELS[index]}</th>{values.map((value, column) => <td key={column}>{value}</td>)}</tr>)}</tbody></table></div>}
    {arms.length ? <>
      <div className="table-wrap"><table><caption>Descriptive participant outcomes by assigned arm</caption><thead><tr><th>Arm</th><th>Responses</th><th>Participants</th><th>Mean elapsed seconds</th><th>Authority comprehension</th><th>Mean trust (1–5)</th></tr></thead><tbody>{arms.map(arm => <tr key={text(arm.arm)}><th scope="row">{text(arm.arm)}</th><td>{text(arm.n)}</td><td>{text(arm.participants)}</td><td>{decimal(arm.mean_elapsed_seconds)}</td><td>{percent(arm.authority_comprehension_rate)}</td><td>{decimal(arm.mean_trust_rating)}</td></tr>)}</tbody></table></div>
      <div className="table-wrap"><table><caption>Reference-source-specific agreement · never pooled as clinical accuracy</caption><thead><tr><th>Arm</th><th>Reference source</th><th>Responses</th><th>Agreement</th><th>Incorrect suggestions</th><th>Incorrect suggestions rejected</th></tr></thead><tbody>{arms.flatMap(arm => Object.entries(record(arm.references)).map(([source, value]) => { const ref = record(value); return <tr key={`${text(arm.arm)}-${source}`}><th scope="row">{text(arm.arm)}</th><td>{title(source)}</td><td>{text(ref.n)}</td><td>{percent(ref.agreement)}</td><td>{text(ref.incorrect_suggestions)}</td><td>{text(ref.incorrect_suggestions_rejected)}</td></tr>; }))}</tbody></table></div>
    </> : <p>No completed participant responses. Software verification fixtures must not be described as recruited participants or completed fieldwork.</p>}
    <JsonDetails title="Study denominators and methodological limitations" value={summary} />
  </>;
}

function MonitoringEvidence({ report }: { report: RecordValue }) {
  const windows = rows(report.windows);
  const drift = record(report.categorical_drift);
  return <>
    <SummaryTable value={report} caption="Recorded monitoring denominators" scalarsOnly />
    <div className="table-wrap"><table><caption>Observed shadow missingness and categorical input change</caption><thead><tr><th>Feature</th><th>Missing fraction</th><th>Total variation from fit data</th></tr></thead><tbody>{Object.entries(record(report.missingness)).map(([field, fraction]) => <tr key={field}><th scope="row">{title(field)}</th><td>{percent(fraction)}</td><td>{decimal(record(drift[field]).total_variation)}</td></tr>)}</tbody></table></div>
    {windows.length > 0 && <div className="table-wrap"><table><caption>Non-overlapping shadow completion windows</caption><thead><tr><th>First response index</th><th>Responses</th><th>Suggestion coverage</th><th>Agreement with pre-reveal assessment</th><th>Raw label agreement</th></tr></thead><tbody>{windows.map((window, index) => <tr key={index}><td>{text(window.start_index)}</td><td>{text(window.n)}</td><td>{percent(window.suggestion_coverage)}</td><td>{percent(window.agreement_with_pre_reveal_assessment)}</td><td>{percent(window.raw_prediction_agreement)}</td></tr>)}</tbody></table></div>}
    <JsonDetails title="Agreement, delayed outcomes, missingness and monitoring details" value={report} />
    <p>Input drift and performance drift are different. Monitoring does not retrain or activate a model. Small samples and unavailable references must remain visible.</p>
  </>;
}

function OperationsEvidence({ run }: { run: Run }) {
  const [scenario, setScenario] = useState("");
  const result = run.results;
  if (!result || !Object.keys(result).length) return <article className="panel spaced"><h2>Operations study {run.id.slice(0, 8)}</h2><p role="status">{run.status}{["RUNNING", "QUEUED", "PENDING"].includes(run.status) ? " · checking durable worker progress…" : ""}</p>{run.error && <p role="alert" className="callout caution">{run.error}</p>}</article>;
  const wait = record(result.wait_prediction);
  const planning = record(result.resource_planning);
  const evaluation = record(wait.test);
  const slices = rows(wait.slices);
  const scenarios = rows(planning.sensitivities);
  const selected = scenarios.find(item => item.scenario === scenario) ?? scenarios[0] ?? {};
  const policies = record(selected.policies);
  const paired = record(selected.paired_comparisons);
  const forecast = record(planning.forecast);
  const ci = (value: unknown) => Array.isArray(value) ? value.map(v => decimal(v)).join(" to ") : "Not estimable";
  return <article className="panel spaced">
    <div className="panel-head"><div><p className="eyebrow">{text(result.engine_version)}</p><h2>Held-out operations study results</h2></div><ExportLinks path={`/runs/${run.id}/export`} /></div>
    <p className="warning-text">Synthetic research only. More accurate estimates do not by themselves reduce waiting. Plans are evaluated proposals, never automatic staff or patient-priority changes.</p>
    <h3>Direct waiting-time prediction</h3>
    <p>{text(wait.target)}</p>
    <div className="table-wrap"><table><caption>Waiting predictions evaluated against realised synthetic waits</caption><thead><tr><th>Estimator</th><th>Wait MAE (min)</th><th>Interval coverage</th><th>Mean width (min)</th><th>Evaluation cases</th></tr></thead><tbody><tr><th scope="row">{title(text(wait.selected_estimator))}</th><td>{decimal(evaluation.mae_minutes)}</td><td>{percent(evaluation.interval_coverage)}</td><td>{decimal(evaluation.mean_interval_width_minutes)}</td><td>{text(evaluation.rows)}</td></tr><tr><th scope="row">Queue-workload baseline</th><td>{decimal(evaluation.baseline_mae_minutes)}</td><td>Not estimated</td><td>Not estimated</td><td>{text(evaluation.rows)}</td></tr></tbody></table></div>
    <p>Nominal interval coverage {percent(wait.nominal_interval_coverage)}; measured coverage above is not a guarantee under temporal shift. Prediction accuracy covers started cases; unfinished arrivals are retained separately.</p>
    <SummaryTable value={record(wait.all_arrival_outcomes)} caption="All-arrival outcomes · including unfinished cases" />
    {slices.length > 0 && <details><summary>Waiting prediction performance by synthetic condition</summary><div className="table-wrap"><table><thead><tr><th>Slice</th><th>Value</th><th>Cases</th><th>MAE (min)</th><th>Baseline MAE (min)</th><th>Coverage</th></tr></thead><tbody>{slices.map((item, index) => <tr key={index}><th scope="row">{title(text(item.slice))}</th><td>{text(item.value)}</td><td>{text(item.rows)}</td><td>{decimal(item.mae_minutes)}</td><td>{decimal(item.baseline_mae_minutes)}</td><td>{percent(item.interval_coverage)}</td></tr>)}</tbody></table></div></details>}
    <SummaryTable value={wait} caption="Waiting prediction evaluation design" scalarsOnly />
    <h3>Equal-budget resource planning</h3>
    <p>Held-out hourly demand MAE {decimal(forecast.test_mae_arrivals_per_hour)} arrivals, historical-hour baseline {decimal(forecast.historical_hourly_baseline_mae)}. Tested on {text(forecast.heldout_test_days)} held-out synthetic days.</p>
    {scenarios.length > 0 && <label>Planning sensitivity scenario<select aria-label="Planning sensitivity scenario" value={text(selected.scenario)} onChange={event => setScenario(event.target.value)}>{scenarios.map(item => <option value={text(item.scenario)} key={text(item.scenario)}>{title(text(item.scenario))}</option>)}</select></label>}
    {Object.keys(policies).length > 0 && <div className="table-wrap"><table><caption>Common synthetic inputs across operational comparators</caption><thead><tr><th>Policy</th><th>Mean completed wait (min)</th><th>Mean run P90 (min)</th><th>Completed / run</th><th>Unserved / run</th><th>All-arrival accumulated wait (min)</th><th>All constraints valid</th></tr></thead><tbody>{Object.entries(policies).map(([key, value]) => { const item = record(value); return <tr key={key}><th scope="row">{title(key)}</th><td>{decimal(item.mean_wait_minutes)}</td><td>{decimal(item.mean_replication_p90_minutes)}</td><td>{decimal(item.completed_mean)}</td><td>{decimal(item.unserved_mean)}</td><td>{decimal(item.mean_all_arrival_accumulated_wait_minutes)}</td><td>{item.all_constraints_valid === true ? "Yes" : item.all_constraints_valid === false ? "No — inspect evidence" : "Not available"}</td></tr>; })}</tbody></table></div>}
    <p>Completed-only mean and P90 exclude unfinished cases. All-arrival accumulated wait ends at service start or the observation horizon and includes never-started cases. These are consultation-stage supporting outcomes, not whole-journey effects.</p>
    {Object.keys(paired).length > 0 && <div className="table-wrap"><table><caption>Paired differences in all-arrival accumulated waiting · minutes</caption><thead><tr><th>Contrast</th><th>Mean difference</th><th>Paired 95% interval</th><th>Pairs</th><th>Interval half-width</th></tr></thead><tbody>{Object.entries(paired).map(([key, value]) => { const item = record(value); return <tr key={key}><th scope="row">{title(key)}</th><td>{decimal(item.mean_difference_minutes)}</td><td>{ci(item.paired_95_ci)}</td><td>{text(item.pairs)}</td><td>{decimal(item.half_width_minutes)}</td></tr>; })}</tbody></table></div>}
    <p>Negative differences favour the first named policy. An interval spanning zero does not establish a reduction. Inspect all demand/outage scenarios and unserved counts, not just favourable means.</p>
    <SummaryTable value={planning} caption="Planning protocol and paired comparisons" scalarsOnly />
    <JsonDetails title="Full waiting prediction evidence and robustness slices" value={wait} />
    <JsonDetails title="Full paired planning results, constraints and uncertainty" value={planning} />
    <JsonDetails title="Methods, provenance and reproducibility package" value={result} />
  </article>;
}

function FeatureValues({ features }: { features: RecordValue }) {
  return <><dl className="rw-features">{Object.entries(features).map(([key, value]) => <div key={key}><dt>{title(key)}</dt><dd>{value == null ? "Missing — not assumed normal" : text(value)}{key === "recorded_measurement" && <small>Dimensionless synthetic proxy, not a clinical vital sign</small>}</dd></div>)}</dl><p className="rw-muted">Neutral P1–P5 research labels do not implement or certify a clinical triage protocol.</p></>;
}

function LabelForm({ onSubmit, disabled, prefix, submit }: { onSubmit: (event: FormEvent<HTMLFormElement>) => void; disabled: boolean; prefix: string; submit: string }) {
  return <form onSubmit={onSubmit} className="form-grid"><label>{prefix} label<select aria-label={`${prefix} label`} name="label" defaultValue="" required><option value="" disabled>Choose a label</option>{LABELS.map(label => <option key={label}>{label}</option>)}</select></label><label>{prefix} rationale<textarea name="reason" required minLength={5} maxLength={500} /></label><button className="primary span-2" disabled={disabled}>{submit}</button></form>;
}

function ExportLinks({ path }: { path: string }) {
  return <div className="row-actions">{["json", "csv"].map(format => <a className="secondary button" key={format} href={`${API_URL}${ROOT}${path}?format=${format}`} target="_blank" rel="noreferrer">Export {format.toUpperCase()}</a>)}</div>;
}

function SummaryTable({ value, caption, scalarsOnly = false }: { value: RecordValue | OperationsConfig; caption: string; scalarsOnly?: boolean }) {
  const entries = Object.entries(value).filter(([, item]) => !scalarsOnly || item === null || typeof item !== "object");
  if (!entries.length) return null;
  return <div className="table-wrap"><table className="rw-summary"><caption>{caption}</caption><tbody>{entries.map(([key, item]) => <tr key={key}><th scope="row">{title(key)}</th><td>{text(item)}</td></tr>)}</tbody></table></div>;
}

function JsonDetails({ title: heading, value }: { title: string; value: unknown }) {
  return <details className="rw-json"><summary>{heading}</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;
}
