"""Non-preemptive multi-stage SimPy experiment with common random numbers."""
from dataclasses import asdict, dataclass
import hashlib
import json
from statistics import mean
import numpy as np
import simpy
from scipy.stats import t, ttest_rel, wilcoxon

POLICIES = ["FCFS", "URGENCY_FIRST", "HYBRID"]
# Research-only arms (ADR-034). They exist to quantify trade-offs for the patient at the
# bottom of the queue and the value of duration prediction; neither is used by the live
# queue, where only clinician-confirmed urgency orders patients.
RESEARCH_POLICIES = ["AGEING_BOUNDED", "DURATION_AWARE"]
RESEARCH_DEFAULTS = {"promote_minutes": 60.0, "max_promotion_levels": 2, "duration_guard_minutes": 60.0, "prediction_error_sigma": .35}
URGENCY_ORDER = {f"P{i}": i for i in range(1, 6)}
STAGES = ["registration", "triage", "consultation", "pharmacy"]


@dataclass(frozen=True)
class SimPatient:
    patient_no: int
    arrival: float
    service: float
    urgency: str | None
    registration: float = 3.0
    triage: float = 5.0
    pharmacy: float = 4.0
    needs_pharmacy: bool = True


def generate_patients(seed, count, arrivals_per_hour, mean_service, urgency_mix=None,
                      pharmacy_probability=.75, arrival_pattern="poisson", hourly_rates=None,
                      stage_means=None, service_tail=.5):
    rng = np.random.default_rng(seed)
    arrivals = []
    now = 0.0
    for index in range(count):
        rate = hourly_rates[min(int(now // 60), len(hourly_rates) - 1)] if hourly_rates else arrivals_per_hour
        if rate <= 0:
            now = (int(now // 60) + 1) * 60
            rate = arrivals_per_hour
        now += float(rng.exponential(60 / rate)) if arrival_pattern != "burst" else (60 if index and index % 30 == 0 else 0)
        arrivals.append(now)
    services = rng.lognormal(np.log(mean_service) - service_tail ** 2 / 2, service_tail, count)
    labels = rng.choice(list(URGENCY_ORDER), count, p=urgency_mix or [.03, .09, .23, .4, .25])
    means = {"registration": 3., "triage": 5., "pharmacy": 4., **(stage_means or {})}
    stage_values = {stage: rng.lognormal(np.log(value) - .125, .5, count) for stage, value in means.items()}
    pharmacy = rng.random(count) < pharmacy_probability
    return [SimPatient(i + 1, arrivals[i], float(services[i]), str(labels[i]),
        float(stage_values["registration"][i]), float(stage_values["triage"][i]),
        float(stage_values["pharmacy"][i]), bool(pharmacy[i])) for i in range(count)]


def _select(waiting, policy, now, stage, research=None, predicted=None):
    research = research or RESEARCH_DEFAULTS
    prioritised = stage in {"consultation", "pharmacy"}
    def key(item):
        patient, queued, _ = item
        group = URGENCY_ORDER.get(patient.urgency, 99) if policy != "FCFS" and prioritised else 0
        age = -min(now - queued, 240) / 240 if policy == "HYBRID" else 0
        if policy == "AGEING_BOUNDED" and prioritised:
            # One category step per `promote_minutes` waited, capped; never above P1.
            steps = min(int(research["max_promotion_levels"]), int((now - queued) // research["promote_minutes"]))
            group = max(1, group - steps)
        if policy == "DURATION_AWARE" and stage == "consultation":
            # Within a category: anyone past the guard goes first (oldest first); otherwise
            # shortest *predicted* consultation first. The guard prevents starvation.
            overdue = (now - queued) >= research["duration_guard_minutes"]
            shortest = 0.0 if overdue else (predicted or {}).get(patient.patient_no, patient.service)
            return group, 0 if overdue else 1, shortest, queued, patient.patient_no
        return group, 0, age, queued, patient.patient_no
    return min(waiting, key=key)


def summary(values):
    if not values:
        return {"mean": None, "median": None, "p90": None, "maximum": None}
    return {"mean": round(float(np.mean(values)), 4), "median": round(float(np.median(values)), 4),
        "p90": round(float(np.percentile(values, 90)), 4), "maximum": round(float(max(values)), 4)}


def tail(values):
    """Extra distribution detail for fairness reporting (kept separate so `summary` is stable)."""
    if not values:
        return {"n": 0, "p95": None, "sd": None}
    return {"n": len(values), "p95": round(float(np.percentile(values, 95)), 4),
            "sd": round(float(np.std(values, ddof=1)), 4) if len(values) > 1 else None}


def simulate_once(patients, policy, servers, stage_capacities=None, outage=None, warning_minutes=60, research=None, predicted=None):
    env = simpy.Environment()
    capacities = {"registration": 2, "triage": 1, "consultation": servers, "pharmacy": 1, **(stage_capacities or {})}
    queues = {stage: [] for stage in STAGES}
    signals = {stage: simpy.Store(env) for stage in STAGES}
    stage_waits = {stage: [] for stage in STAGES}
    stage_service = {stage: [] for stage in STAGES}
    lengths = {stage: {"last": 0., "area": 0., "maximum": 0} for stage in STAGES}
    consultation_waits, all_waits, totals, arrival_provider = [], [], [], []
    by_urgency = {label: [] for label in URGENCY_ORDER}
    consult_log = []  # (queued, started, urgency) for overtaking analysis
    traces = {}

    def changed(stage):
        stat = lengths[stage]
        stat["area"] += len(queues[stage]) * (env.now - stat["last"])
        stat["last"] = env.now

    def patient_process(patient):
        yield env.timeout(patient.arrival)
        own_waits = []
        trace = []
        for stage in STAGES:
            if stage == "pharmacy" and not patient.needs_pharmacy:
                continue
            done = env.event()
            queued = float(env.now)
            changed(stage)
            queues[stage].append((patient, queued, done))
            lengths[stage]["maximum"] = max(lengths[stage]["maximum"], len(queues[stage]))
            yield signals[stage].put(True)
            record = yield done
            own_waits.append(record["wait"])
            trace.append({"stage": stage, **record})
        totals.append(float(env.now - patient.arrival))
        all_waits.append(sum(own_waits))
        traces[str(patient.patient_no)] = trace

    def worker(stage, index):
        while True:
            while not queues[stage]:
                yield signals[stage].get()
            if outage and stage == outage.get("stage", "consultation"):
                start = outage["start_minute"]
                end = start + outage["duration_minutes"]
                if start <= env.now < end and index >= outage.get("available_servers", 0):
                    yield env.timeout(end - env.now)
                    continue
            selected = _select(queues[stage], policy, env.now, stage, research, predicted)
            changed(stage)
            queues[stage].remove(selected)
            patient, queued, done = selected
            started = float(env.now)
            wait = started - queued
            stage_waits[stage].append(wait)
            if stage == "consultation":
                consultation_waits.append(wait)
                arrival_provider.append(started - patient.arrival)
                by_urgency.setdefault(patient.urgency or "UNLABELLED", []).append(wait)
                consult_log.append((queued, started, patient.urgency))
            duration = patient.service if stage == "consultation" else getattr(patient, stage)
            stage_service[stage].append(duration)
            yield env.timeout(duration)
            done.succeed({"queued": queued, "started": started, "ended": float(env.now), "wait": wait, "service": duration})

    for stage, capacity in capacities.items():
        for index in range(capacity):
            env.process(worker(stage, index))
    for patient in patients:
        env.process(patient_process(patient))
    env.run()
    horizon = float(env.now)
    for stage in STAGES:
        changed(stage)
    utilisation = {stage: sum(stage_service[stage]) / (capacities[stage] * horizon)
        if capacities[stage] and horizon else 0. for stage in STAGES}
    return {"completed": len(totals), "unserved": len(patients) - len(totals), "waits": consultation_waits,
        "all_stage_waits": all_waits, "by_urgency": by_urgency, "arrival_to_provider": arrival_provider,
        "total_visit": totals, "utilisation": utilisation["consultation"], "horizon_minutes": horizon,
        "stage_waits": stage_waits, "stage_services": stage_service, "stage_utilisation": utilisation,
        "queue_lengths": {stage: {"mean": lengths[stage]["area"] / horizon if horizon else 0.,
            "maximum": lengths[stage]["maximum"]} for stage in STAGES},
        "overtaken": overtaking(consult_log),
        "traces": traces}


def overtaking(log):
    """For each consultation, how many patients who queued *later* started *earlier*."""
    result = {label: [] for label in URGENCY_ORDER}
    ordered = sorted(log)
    for index, (queued, started, urgency) in enumerate(ordered):
        count = sum(1 for other_queued, other_started, _ in ordered[index + 1:] if other_queued > queued and other_started < started)
        result.setdefault(urgency or "UNLABELLED", []).append(count)
    return result


def paired_test(first, second):
    """Paired comparison of replication means (second - first)."""
    differences = [b - a for a, b in zip(first, second) if a is not None and b is not None]
    if len(differences) < 2:
        return {"n": len(differences), "mean_difference": float(np.mean(differences)) if differences else None,
                "ci95": None, "t_p_value": None, "wilcoxon_p_value": None}
    diff = np.asarray(differences, dtype=float)
    margin = float(t.ppf(.975, len(diff) - 1) * diff.std(ddof=1) / np.sqrt(len(diff)))
    result = {"n": len(diff), "mean_difference": float(diff.mean()), "ci95": [float(diff.mean() - margin), float(diff.mean() + margin)]}
    if np.allclose(diff, 0):
        result.update(t_p_value=1.0, wilcoxon_p_value=1.0, note="Identical in every replication")
    else:
        result["t_p_value"] = float(ttest_rel(second[:len(diff)], first[:len(diff)]).pvalue)
        try:
            result["wilcoxon_p_value"] = float(wilcoxon(diff).pvalue)
        except ValueError:
            result["wilcoxon_p_value"] = None
    return result


def predicted_durations(seed, patients, sigma):
    """Imperfect duration predictions from a separate stream, so the shared patient sequence
    (and every non-research result) is unchanged by enabling research arms."""
    rng = np.random.default_rng(np.random.SeedSequence([seed, 7919]))
    noise = rng.lognormal(-sigma ** 2 / 2, sigma, len(patients)) if sigma > 0 else np.ones(len(patients))
    return {p.patient_no: float(p.service * n) for p, n in zip(patients, noise)}


def validate_against_baseline(runs, target, tolerance):
    """Does the simulated FCFS facility reproduce the observed baseline? (proposal §1.8)"""
    rows, observed_stages = [], target.get("stages", {})
    for stage in STAGES:
        observed = observed_stages.get(stage)
        if not observed or observed.get("waiting_minutes", {}).get("mean") is None:
            continue
        simulated = summary([v for r in runs for v in r["stage_waits"][stage]])
        for statistic in ("mean", "p90"):
            obs, sim = observed["waiting_minutes"].get(statistic), simulated.get(statistic)
            if obs is None or sim is None:
                continue
            allowed = max(tolerance * obs, 5.0)
            rows.append({"stage": stage, "statistic": f"wait {statistic}", "observed_minutes": round(obs, 2), "simulated_minutes": round(sim, 2),
                         "absolute_error": round(abs(sim - obs), 2), "allowed_error": round(allowed, 2), "within_tolerance": abs(sim - obs) <= allowed})
    for key, label in (("arrival_to_provider_minutes", "arrival to provider"), ("total_visit_minutes", "total visit")):
        obs = (target.get(key) or {}).get("mean")
        simulated = summary([v for r in runs for v in r["arrival_to_provider" if key.startswith("arrival") else "total_visit"]])["mean"]
        if obs is not None and simulated is not None:
            allowed = max(tolerance * obs, 5.0)
            rows.append({"stage": "journey", "statistic": f"{label} mean", "observed_minutes": round(obs, 2), "simulated_minutes": round(simulated, 2),
                         "absolute_error": round(abs(simulated - obs), 2), "allowed_error": round(allowed, 2), "within_tolerance": abs(simulated - obs) <= allowed})
    reproduced = bool(rows) and all(row["within_tolerance"] for row in rows)
    return {"reproduces_baseline": reproduced, "tolerance": f"max({int(tolerance * 100)}% of observed, 5 minutes)", "checks": rows,
            "interpretation": "Policy comparisons are only interpretable for this facility if the FCFS simulation reproduces the measured baseline."
                              if reproduced else "The simulated facility does NOT reproduce the measured baseline within tolerance; treat policy comparisons as exploratory and revisit the calibration."}


def run_comparison(*, seed, patient_count, replications, servers, arrival_rate_per_hour, mean_service_minutes,
                   urgency_mix=None, pharmacy_probability=.75, arrival_pattern="poisson", hourly_rates=None,
                   stage_means=None, stage_capacities=None, outage=None, warning_minutes=60, service_tail=.5,
                   include_research_arms=False, research=None, validation_target=None, validation_tolerance=.25, calibration=None):
    research = {**RESEARCH_DEFAULTS, **(research or {})}
    policies = POLICIES + (RESEARCH_POLICIES if include_research_arms else [])
    collected = {policy: [] for policy in policies}
    paired, input_hashes = [], []
    for replication in range(replications):
        patients = generate_patients(seed + replication, patient_count, arrival_rate_per_hour, mean_service_minutes,
            urgency_mix, pharmacy_probability, arrival_pattern, hourly_rates, stage_means, service_tail)
        input_hashes.append(hashlib.sha256(json.dumps([asdict(p) for p in patients], sort_keys=True).encode()).hexdigest())
        predicted = predicted_durations(seed + replication, patients, research["prediction_error_sigma"]) if include_research_arms else None
        runs = {policy: simulate_once(patients, policy, servers, stage_capacities, outage, warning_minutes, research, predicted) for policy in policies}
        for policy in policies:
            collected[policy].append(runs[policy])
        if runs["FCFS"]["all_stage_waits"] and runs["HYBRID"]["all_stage_waits"]:
            baseline, proposed = mean(runs["FCFS"]["all_stage_waits"]), mean(runs["HYBRID"]["all_stage_waits"])
            paired.append({"replication": replication + 1, "fcfs_mean": baseline, "hybrid_mean": proposed,
                "difference_minutes": proposed - baseline})
    summaries = {}
    for policy, runs in collected.items():
        summaries[policy] = {"waiting_minutes": summary([v for r in runs for v in r["all_stage_waits"]]),
            "consultation_waiting_minutes": summary([v for r in runs for v in r["waits"]]),
            "arrival_to_provider_minutes": summary([v for r in runs for v in r["arrival_to_provider"]]),
            "total_visit_minutes": summary([v for r in runs for v in r["total_visit"]]),
            "by_urgency": {u: summary([v for r in runs for v in r["by_urgency"].get(u, [])]) for u in URGENCY_ORDER},
            "completed_mean": mean(r["completed"] for r in runs), "unserved_mean": mean(r["unserved"] for r in runs),
            "utilisation_mean": mean(r["utilisation"] for r in runs),
            "low_urgency_long_waits": sum(v >= warning_minutes for r in runs for u in ["P4", "P5"] for v in r["by_urgency"].get(u, [])),
            "stages": {stage: {"wait_minutes": summary([v for r in runs for v in r["stage_waits"][stage]]),
                "service_minutes": summary([v for r in runs for v in r["stage_services"][stage]]),
                "utilisation": mean(r["stage_utilisation"][stage] for r in runs),
                "queue_length_mean": mean(r["queue_lengths"][stage]["mean"] for r in runs),
                "queue_length_maximum": max(r["queue_lengths"][stage]["maximum"] for r in runs)} for stage in STAGES},
            "replication_mean_waits": [mean(r["all_stage_waits"]) if r["all_stage_waits"] else None for r in runs],
            "fairness": {"wait_tail_by_urgency": {u: tail([v for r in runs for v in r["by_urgency"].get(u, [])]) for u in URGENCY_ORDER},
                "overtaken_by_urgency": {u: {"mean": round(float(np.mean(vals)), 3) if vals else None, "maximum": max(vals) if vals else None}
                    for u in URGENCY_ORDER for vals in [[v for r in runs for v in r["overtaken"].get(u, [])]]},
                "low_urgency_max_wait": max([v for r in runs for u in ["P4", "P5"] for v in r["by_urgency"].get(u, [])], default=None),
                "definition": "Consultation stage. Overtaken = later arrivals who started consultation first; the cost of priority borne by each patient."},
            "research_only": policy in RESEARCH_POLICIES}
    differences = [p["difference_minutes"] for p in paired]
    delta = float(np.mean(differences)) if differences else None
    interval = None
    if len(differences) >= 2:
        margin = float(t.ppf(.975, len(differences) - 1) * np.std(differences, ddof=1) / np.sqrt(len(differences)))
        interval = [delta - margin, delta + margin]
    baseline = summaries["FCFS"]["waiting_minutes"]["mean"]
    fcfs_means = summaries["FCFS"]["replication_mean_waits"]
    versus_fcfs = {policy: paired_test(fcfs_means, summaries[policy]["replication_mean_waits"]) for policy in policies if policy != "FCFS"}
    extra = {"inferential": {"paired_vs_fcfs_mean_journey_wait": versus_fcfs,
                             "method": "Replication-level paired comparison with common random numbers: paired t-test and Wilcoxon signed-rank; descriptive at the replication level, not patient-level significance",
                             "multiple_comparisons": "Several policies are compared with FCFS; interpret p-values descriptively (no correction applied)"}}
    if include_research_arms:
        extra["research_arms"] = {"policies": RESEARCH_POLICIES, "parameters": research,
            "AGEING_BOUNDED": f"Waiting time promotes a patient one category per {research['promote_minutes']:g} minutes, at most {research['max_promotion_levels']} categories. RESEARCH ONLY: crosses clinician-confirmed categories, which the live queue never does.",
            "DURATION_AWARE": f"Within a category, shortest predicted consultation first (prediction error σ={research['prediction_error_sigma']}); anyone waiting {research['duration_guard_minutes']:g}+ minutes goes first. RESEARCH ONLY.",
            "safety": "Research arms quantify trade-offs for discussion; adopting either would require clinical governance review (ADR-034)."}
    if validation_target:
        extra["calibration_validation"] = validate_against_baseline(collected["FCFS"], validation_target, validation_tolerance)
    if calibration:
        extra["calibration"] = calibration
    return {**extra,"research_label": "SYNTHETIC SIMULATION — NOT CLINICAL EVIDENCE", "seed": seed,
        "replications": replications, "patient_count_per_replication": patient_count,
        "input_sequence_hashes": input_hashes, "policy_version": "safe-groups-v2",
        "parameters": {"servers": servers, "arrival_rate_per_hour": arrival_rate_per_hour,
            "mean_service_minutes": mean_service_minutes, "urgency_mix": urgency_mix,
            "pharmacy_probability": pharmacy_probability, "arrival_pattern": arrival_pattern,
            "hourly_rates": hourly_rates, "stage_means": stage_means, "stage_capacities": stage_capacities,
            "outage": outage, "warning_minutes": warning_minutes, "service_tail": service_tail},
        "policies": summaries, "comparison": {"absolute_mean_difference_minutes": delta,
            "percentage_difference": delta / baseline * 100 if delta is not None and baseline else None,
            "paired_95_ci_minutes": interval, "hybrid_improved_mean_wait": delta is not None and delta < 0,
            "paired_replications": paired, "method": "Shared arrival, route, urgency and service sequence across all policies; paired Student-t interval across independent replications."},
        "definitions": {"primary": "Sum of waiting minutes across the completed outpatient journey",
            "arrival_to_provider": "Consultation start minus arrival (includes registration and triage service)",
            "utilisation": "Busy time / nominal server capacity over the drained replication horizon",
            "outage": "Non-preemptive: already-started service completes; affected workers pause new starts during outage"},
        "limitations": ["Synthetic distributions are engineering assumptions", "Urgency labels do not implement a triage protocol",
            "Hybrid and urgency-first can coincide when age cannot cross urgency groups", "No policy can create staffing capacity",
            "Unserved visits are reported separately and excluded from completed-journey means"]}


def synthetic_rows(seed=2026, count=300):
    return [asdict(p) for p in generate_patients(seed, count, 24., 12.)]
