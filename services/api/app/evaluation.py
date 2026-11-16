"""Evaluation aligned to the proposal's four objectives (Chapter 1 §1.2–1.3, §1.10; ADR-036).

* Usability and acceptance instruments: the System Usability Scale (Brooke, 1996) with its
  standard scoring, and short perceived-usefulness / perceived-ease-of-use scales adapted
  from the Technology Acceptance Model (Davis, 1989).
* An evaluation report that gathers, per objective and research question, the evidence the
  system holds, states what is missing, and applies the inferential tests the proposal names.

Everything shipped here is synthetic. The report says so on every section; it demonstrates
the evaluation method and must not be presented as findings about a real facility.
"""
from __future__ import annotations

import math
from datetime import timezone

import numpy as np
from scipy.stats import mannwhitneyu, spearmanr, t as student_t
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (AuditEvent, Dataset, DisplayScreen, ModelVersion, QueueStateEvent, ResearchFeedback, ServiceEpisode,
                        ServicePoint, SimulationRun, TriageAssessment, Visit, utcnow)

SUS_ITEMS = [
    "I think that I would like to use this system frequently.",
    "I found the system unnecessarily complex.",
    "I thought the system was easy to use.",
    "I think that I would need the support of a technical person to be able to use this system.",
    "I found the various functions in this system were well integrated.",
    "I thought there was too much inconsistency in this system.",
    "I would imagine that most people would learn to use this system very quickly.",
    "I found the system very cumbersome to use.",
    "I felt very confident using the system.",
    "I needed to learn a lot of things before I could get going with this system.",
]
# Adapted from Davis (1989) for queue work. Wording is adapted and must be piloted/validated.
TAM_ITEMS = {
    "perceived_usefulness": [
        "Using Hutano Flow would help me move patients through the queue more quickly.",
        "Using Hutano Flow would improve how I prioritise patients.",
        "Using Hutano Flow would make my work at this service point easier.",
        "I would find Hutano Flow useful in my job.",
    ],
    "perceived_ease_of_use": [
        "Learning to operate Hutano Flow would be easy for me.",
        "I would find it easy to get Hutano Flow to do what I need it to do.",
        "My interaction with Hutano Flow would be clear and understandable.",
        "I would find Hutano Flow easy to use.",
    ],
}
SUS_AVERAGE = 68.0  # widely cited average SUS score across studies (Sauro, 2011)


def validate_sus(values) -> list[int]:
    if not isinstance(values, list) or len(values) != 10 or any(not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 5 for v in values):
        raise ValueError("SUS needs ten responses, each an integer 1–5")
    return values


def validate_tam(value) -> dict:
    if not isinstance(value, dict) or set(value) != set(TAM_ITEMS):
        raise ValueError("TAM needs perceived_usefulness and perceived_ease_of_use responses")
    for construct, items in TAM_ITEMS.items():
        answers = value[construct]
        if not isinstance(answers, list) or len(answers) != len(items) or any(not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 7 for v in answers):
            raise ValueError(f"{construct} needs {len(items)} responses, each an integer 1–7")
    return value


def sus_score(values: list[int]) -> float:
    """Standard SUS scoring: odd items (score − 1), even items (5 − score), sum × 2.5 → 0–100."""
    return sum((v - 1) if index % 2 == 0 else (5 - v) for index, v in enumerate(values)) * 2.5


def cronbach_alpha(rows: list[list[int]]) -> float | None:
    if len(rows) < 3:
        return None
    matrix = np.asarray(rows, dtype=float)
    k = matrix.shape[1]
    total = matrix.sum(axis=1).var(ddof=1)
    if total == 0:
        return None
    return float(k / (k - 1) * (1 - matrix.var(axis=0, ddof=1).sum() / total))


def describe(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None}
    array = np.asarray(values, dtype=float)
    result = {"n": len(array), "mean": round(float(array.mean()), 2), "median": round(float(np.median(array)), 2),
              "minimum": round(float(array.min()), 2), "maximum": round(float(array.max()), 2)}
    if len(array) > 1:
        sd = float(array.std(ddof=1))
        margin = float(student_t.ppf(.975, len(array) - 1) * sd / math.sqrt(len(array)))
        result.update(sd=round(sd, 2), ci95=[round(result["mean"] - margin, 2), round(result["mean"] + margin, 2)])
    return result


def acceptance_summary(rows: list[ResearchFeedback]) -> dict:
    sus = [sus_score(r.response_json["sus"]) for r in rows if "sus" in r.response_json]
    sus_items = [r.response_json["sus"] for r in rows if "sus" in r.response_json]
    tam_rows = [r.response_json["tam"] for r in rows if "tam" in r.response_json]
    tam = {}
    for construct in TAM_ITEMS:
        answers = [row[construct] for row in tam_rows]
        tam[construct] = {**describe([float(np.mean(a)) for a in answers]), "cronbach_alpha": cronbach_alpha(answers),
                          "scale": "1 (strongly disagree) – 7 (strongly agree)"}
    correlation = None
    if len(tam_rows) >= 5:
        pu = [np.mean(row["perceived_usefulness"]) for row in tam_rows]
        peou = [np.mean(row["perceived_ease_of_use"]) for row in tam_rows]
        if len(set(pu)) > 1 and len(set(peou)) > 1:
            rho, p = spearmanr(pu, peou)
            correlation = {"spearman_rho": round(float(rho), 3), "p_value": round(float(p), 4), "n": len(tam_rows)}
    by_role = {}
    for row in rows:
        if "sus" in row.response_json:
            by_role.setdefault(row.role_group, []).append(sus_score(row.response_json["sus"]))
    return {
        "sus": {**describe(sus), "alpha": cronbach_alpha([[(v - 1) if i % 2 == 0 else (5 - v) for i, v in enumerate(items)] for items in sus_items]),
                "benchmark": f"{SUS_AVERAGE:g} is the commonly cited average; above it suggests better-than-average perceived usability",
                "by_role": {role: describe(values) for role, values in by_role.items()},
                "instrument": "System Usability Scale (Brooke, 1996), standard wording and scoring"},
        "tam": {**tam, "pu_peou_correlation": correlation,
                "instrument": "Perceived usefulness and ease of use adapted from Davis (1989); adapted wording needs piloting"},
        "notes": ["Convenience sample in controlled sessions; descriptive, with confidence intervals",
                  "Cronbach's alpha needs at least three respondents and is unstable in small samples"],
    }


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def system_wait_samples(db: Session, facility_id) -> dict[str, list[float]]:
    from app.services.analytics import effective_time
    rows = db.scalars(select(ServiceEpisode).where(ServiceEpisode.facility_id == facility_id, ServiceEpisode.started_at.is_not(None),
                                                   ServiceEpisode.queued_at.is_not(None))).all()
    samples: dict[str, list[float]] = {}
    for episode in rows:
        if episode.status in {"CANCELLED", "NO_SHOW", "TRANSFERRED"}:
            continue
        wait = (effective_time(episode, "started_at") - effective_time(episode, "queued_at")).total_seconds() / 60
        samples.setdefault(episode.service_point.type, []).append(max(0.0, wait))
    return samples


def compare_waits(baseline: list[float], system: list[float]) -> dict:
    """Two independent samples, skewed waits: Mann–Whitney U with rank-biserial effect size."""
    result = {"baseline_n": len(baseline), "system_n": len(system),
              "baseline_median": round(float(np.median(baseline)), 2) if baseline else None,
              "system_median": round(float(np.median(system)), 2) if system else None}
    if len(baseline) < 10 or len(system) < 10:
        return {**result, "test": None, "note": "At least 10 observations per group are needed for a test"}
    statistic, p = mannwhitneyu(system, baseline, alternative="two-sided")
    effect = 1 - 2 * statistic / (len(system) * len(baseline))
    return {**result, "test": "Mann–Whitney U (two-sided)", "u_statistic": float(statistic), "p_value": round(float(p), 5),
            "rank_biserial": round(float(effect), 3),
            "effect_direction": "system waits tend to be shorter" if effect > 0 else "system waits tend to be longer" if effect < 0 else "no difference",
            "effect_size_note": "Rank-biserial r: positive means shorter waits with the system"}


def _status(ok: bool, partial: bool = False) -> str:
    return "evidence" if ok else "partial" if partial else "missing"


def evaluation_report(db: Session, facility_id) -> dict:
    from app.ml.pipeline import FEATURES, SCHEMA_VERSION
    baseline = db.scalar(select(Dataset).where(Dataset.facility_id == facility_id, Dataset.source_type == "SYNTHETIC_BASELINE")
                         .order_by(Dataset.created_at.desc()))
    report = (baseline.schema_json or {}).get("report", {}) if baseline else {}

    # ---------------- Objective 1 / RQ1: current practice, waiting times, bottlenecks
    o1 = {"id": "O1", "objective": "Assess current patient queue-management practices and quantify waiting times and bottlenecks.",
          "research_question": "What patient queue-management practices, waiting-time patterns and bottlenecks currently exist?",
          "proposal_refs": ["§1.2.2(1)", "§1.7 measures", "§1.10 time-and-motion", "§2.1.1 Little's Law"],
          "status": _status(bool(report.get("simulation_inputs")), bool(report))}
    if report:
        o1["evidence"] = {"dataset": {"name": baseline.name, "hash": baseline.dataset_hash, "journeys": report.get("journeys"),
                                      "days_observed": report.get("days_observed"), "provenance": baseline.consent_basis_note},
                          "total_visit_minutes": report.get("total_visit_minutes"), "arrival_to_provider_minutes": report.get("arrival_to_provider_minutes"),
                          "stage_waits": {k: v.get("waiting_minutes") for k, v in report.get("stages", {}).items()},
                          "stage_service": {k: v.get("service_minutes") for k, v in report.get("stages", {}).items()},
                          "bottleneck_stage": report.get("bottleneck_stage"), "time_share": report.get("time_share"),
                          "morning_arrival_share": report.get("morning_arrival_share"), "arrivals_by_hour": report.get("arrivals_by_hour"),
                          "queue_length_by_hour": report.get("queue_length_by_hour"), "littles_law": report.get("littles_law")}
    o1["requirements"] = [
        {"requirement": "Waiting and service time at each service point", "met": bool(report)},
        {"requirement": "Total visit duration and arrival-to-provider time", "met": bool(report)},
        {"requirement": "Arrival distribution by hour and queue length by hour", "met": "arrivals_by_hour" in report},
        {"requirement": "Little's Law sense-check of baseline measurements", "met": "littles_law" in report},
        {"requirement": "Bottleneck identification", "met": "bottleneck_stage" in report},
    ]
    o1["outside_system"] = ["Semi-structured interviews with 8–12 staff are analysed thematically outside the software.",
                            "A real baseline needs institutional and ethical approval; the shipped baseline is synthetic."]

    # ---------------- Objective 2 / RQ2: explainable advisory model from routine data
    model = db.scalar(select(ModelVersion).where(ModelVersion.facility_id == facility_id).order_by(ModelVersion.active.desc(), ModelVersion.created_at.desc()))
    metrics = model.metrics_json if model else {}
    schema = metrics.get("feature_schema", {})
    v3 = schema.get("version") == SCHEMA_VERSION
    o2 = {"id": "O2", "objective": "Develop an explainable AI-assisted model for recommending patient priority using routinely collected clinical and operational data.",
          "research_question": "How can routinely collected clinical and operational data be used to develop an explainable AI-assisted model?",
          "proposal_refs": ["§1.2.2(2)", "§1.8 missing data and proxy labels", "§1.10 two targets", "§2.1.3 Miller", "Gap 2"],
          "status": _status(bool(model) and v3, bool(model))}
    if model:
        test_rows = metrics.get("test_rows") or 0
        selected = metrics.get("reliability_research", {}).get("selected_threshold_test", {})
        o2["evidence"] = {
            "model_version": model.version, "status": model.status, "active": model.active, "feature_schema": schema.get("version"),
            "inputs": schema.get("features"), "label_source": metrics.get("label_source"),
            "macro_f1": metrics.get("macro_f1"), "comparators_macro_f1": {k: v.get("macro_f1") for k, v in metrics.get("comparators", {}).items()},
            "under_triage": {"count": metrics.get("under_triage_against_synthetic_label_count"), "rate": round(metrics.get("under_triage_against_synthetic_label_count", 0) / test_rows, 4) if test_rows else None,
                             "definition": "Suggested a less urgent category than the reference label"},
            "over_triage_count": metrics.get("over_triage_against_synthetic_label_count"),
            "coverage_at_threshold": selected.get("coverage"), "selective_risk": selected.get("risk"),
            "expected_calibration_error": metrics.get("calibration", {}).get("expected_calibration_error"),
            "consultation_duration": metrics.get("duration"),
            "missingness": metrics.get("missingness"),
            "explanation": "Exact per-input contributions, a contrastive 'why this category rather than the next most likely' decomposition, and a plain-language two-factor summary",
        }
    o2["requirements"] = [
        {"requirement": "Inputs drawn from routinely collected data (registration context + six triage vital signs)", "met": v3 and schema.get("features") == FEATURES},
        {"requirement": "Missing values quantified per field before imputation", "met": bool(metrics.get("missingness"))},
        {"requirement": "Two targets: urgency and consultation duration", "met": bool(metrics.get("duration"))},
        {"requirement": "Contrastive, selective explanation a clinician can check", "met": v3},
        {"requirement": "Under-triage examined, not only averages", "met": "under_triage_against_synthetic_label_count" in metrics},
        {"requirement": "Advisory only; clinician confirms; overrides logged", "met": True},
        {"requirement": "Clinician-reviewed labels (real or proxy)", "met": False,
         "note": "Blinded clinician review and consensus tooling exists (Research workbench); labels remain synthetic until approved data is available"},
    ]

    # ---------------- Objective 3 / RQ3: dynamic prioritisation, flow tracking, visibility
    count = lambda statement: db.scalar(statement) or 0
    overrides = count(select(func.count(AuditEvent.id)).where(AuditEvent.facility_id == facility_id, AuditEvent.action == "clinician.override_recorded"))
    reassessments = count(select(func.count(AuditEvent.id)).where(AuditEvent.facility_id == facility_id, AuditEvent.action == "triage.reassessed"))
    tracked = count(select(func.count(QueueStateEvent.id)).where(QueueStateEvent.facility_id == facility_id))
    visits = count(select(func.count(Visit.id)).where(Visit.facility_id == facility_id))
    displays = count(select(func.count(DisplayScreen.id)).where(DisplayScreen.facility_id == facility_id, DisplayScreen.revoked_at.is_(None)))
    o3 = {"id": "O3", "objective": "Design and implement a patient management system supporting dynamic prioritisation, patient-flow tracking and real-time visibility.",
          "research_question": "How can a patient management system be designed and implemented to support dynamic queue prioritisation, patient-flow tracking and real-time queue visibility?",
          "proposal_refs": ["§1.2.2(3)", "§1.10", "Gap 3 (connectivity, hardware)"], "status": "evidence",
          "evidence": {"visits_tracked": visits, "queue_state_transitions": tracked, "clinician_overrides": overrides,
                       "clinician_reassessments": reassessments, "active_waiting_room_displays": displays},
          "requirements": [
              {"requirement": "Queue considers clinical urgency, elapsed waiting and service availability", "met": True,
               "note": "Urgency orders; waiting time drives long-wait flags and clinician-review prompts; availability pauses calls. Cross-category ageing is evaluated in simulation only (ADR-034)"},
              {"requirement": "Responds when a condition changes or a service point goes down", "met": True},
              {"requirement": "Patient-flow tracking across service points with timestamps", "met": True},
              {"requirement": "Real-time visibility for staff and patients (status page, TV board)", "met": True},
              {"requirement": "Role-based access control and audit logging", "met": True},
              {"requirement": "Works with intermittent connectivity and modest hardware", "met": True,
               "note": "Offline shell and stale-state labels, paper downtime kit, LAN deployment"},
          ]}

    # ---------------- Objective 4 / RQ4: waiting time, model performance, usability, acceptance
    system_samples = system_wait_samples(db, facility_id)
    baseline_samples = report.get("wait_samples", {})
    waits = {stage: compare_waits(baseline_samples.get(stage, []), system_samples.get(stage, []))
             for stage in sorted(set(baseline_samples) | set(system_samples)) if stage in {"registration", "triage", "consultation", "pharmacy"}}
    runs = db.scalars(select(SimulationRun).where(SimulationRun.facility_id == facility_id, SimulationRun.status == "COMPLETED")
                      .order_by(SimulationRun.finished_at.desc())).all()
    calibrated = next((r for r in runs if r.results_json.get("calibration_validation")), None)
    simulation = calibrated or (runs[0] if runs else None)
    sim = {}
    if simulation:
        results = simulation.results_json
        sim = {"run_id": str(simulation.id), "calibrated_from_baseline": bool(results.get("calibration_validation")),
               "reproduces_baseline": (results.get("calibration_validation") or {}).get("reproduces_baseline"),
               "replications": results.get("replications"),
               "mean_journey_wait": {p: v["waiting_minutes"]["mean"] for p, v in results.get("policies", {}).items()},
               "paired_vs_fcfs": (results.get("inferential") or {}).get("paired_vs_fcfs_mean_journey_wait"),
               "bottom_of_queue": {p: {"P5_p95_wait": v.get("fairness", {}).get("wait_tail_by_urgency", {}).get("P5", {}).get("p95"),
                                       "P5_max_overtaken": v.get("fairness", {}).get("overtaken_by_urgency", {}).get("P5", {}).get("maximum"),
                                       "P1_mean_consultation_wait": v.get("by_urgency", {}).get("P1", {}).get("mean")}
                                   for p, v in results.get("policies", {}).items()}}
    feedback = db.scalars(select(ResearchFeedback).where(ResearchFeedback.facility_id == facility_id)).all()
    acceptance = acceptance_summary(feedback)
    tested = [w for w in waits.values() if w.get("test")]
    o4 = {"id": "O4", "objective": "Evaluate the system against the existing process using waiting time, model performance, usability and clinician acceptance.",
          "research_question": "How does the system perform on waiting time, model performance, usability and clinician acceptance compared with the existing process?",
          "proposal_refs": ["§1.2.2(4)", "§1.5 under-triage", "§1.10 DES and usability", "§2.1.4 TAM", "Gap 4"],
          "status": _status(bool(tested) and bool(sim.get("reproduces_baseline")) and acceptance["sus"]["n"] > 0,
                            bool(tested) or bool(sim) or acceptance["sus"]["n"] > 0),
          "evidence": {"waiting_time_existing_vs_system": waits, "simulation": sim,
                       "model_performance": "See O2 (macro-F1 vs comparators, under-triage, coverage, calibration)",
                       "usability_and_acceptance": acceptance},
          "requirements": [
              {"requirement": "Waiting time vs existing process with an appropriate inferential test", "met": bool(tested)},
              {"requirement": "Discrete-event simulation fitted to, and reproducing, the measured baseline", "met": bool(sim.get("reproduces_baseline"))},
              {"requirement": "Attention to the patient at the bottom of the queue (not only averages)", "met": bool(sim.get("bottom_of_queue"))},
              {"requirement": "Usability (SUS) and clinician acceptance (TAM)", "met": acceptance["sus"]["n"] > 0 and acceptance["tam"]["perceived_usefulness"]["n"] > 0},
          ]}
    return {"generated_at": utcnow(), "research_label": "SYNTHETIC DEMONSTRATION OF THE EVALUATION METHOD — NOT FINDINGS ABOUT A REAL FACILITY",
            "objectives": [o1, o2, o3, o4],
            "summary": {o["id"]: o["status"] for o in (o1, o2, o3, o4)},
            "limitations": ["All data are synthetic until institutional, ethical and facility approval is obtained (proposal §1.8).",
                            "Baseline and system samples here come from different synthetic generators; the test demonstrates the method only.",
                            "P-values from several comparisons are descriptive; no multiple-comparison correction is applied."]}
