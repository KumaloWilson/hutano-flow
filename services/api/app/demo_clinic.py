"""Coherent fictional clinic fixtures, isolated from the original workspace.

Names are invented combinations, never sourced from patient records. Categories
are scripted synthetic references, not algorithmic triage or staff participation.
Historical timing is a seeded, capacity-constrained FCFS rehearsal using SimPy.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import random
import uuid

import simpy
from sqlalchemy import select, func

from app.config import settings
from app.models import (Facility, User, UserRole, ServicePoint, QueuePolicy, Patient,
    Visit, ServiceEpisode, QueueEntry, QueueStateEvent, TriageAssessment, Observation,
    EncounterNote, Handover, Room, StaffShift, ResourceBlock, ResourceAssignment,
    Dataset, Job, DemoSession, SimulationScenario, SimulationRun, ModelVersion, utcnow)
from app.security import hash_password, status_secret, token_digest
from app.services.audit import record_audit, enqueue_event
from app.services.workflow import ACTIVE_VISIT_STATES, transition_episode
from app.ml.pipeline import generate_synthetic_training_data
from app.seed import POINTS
from app.patients import FIELDS
from app.demo_cast import CAST, CONCERNS, background_identity, plan_text, sample_vitals, triage_reason

VERSION = "fictional-clinic-v3"
FACILITY_ID = uuid.uuid5(uuid.NAMESPACE_URL, "hutano:fictional-community-clinic")
STAFF = [
    ("admin", "Tariro Dube", "DemoAdmin1!", ["ADMIN"]),
    ("reception", "Rudo Moyo", "DemoReception1!", ["RECEPTIONIST"]),
    ("triage", "Nurse Chipo Ndlovu", "DemoTriage1!", ["TRIAGE_NURSE"]),
    ("clinician", "Dr Nyasha Mupfumi", "DemoClinician1!", ["CLINICIAN", "SERVICE_PROVIDER"]),
    ("provider", "Dr Farai Banda", "DemoProvider1!", ["CLINICIAN", "SERVICE_PROVIDER"]),
    ("pharmacy", "Tendai Sibanda", "DemoPharmacy1!", ["PHARMACY"]),
    ("laboratory", "Ruvimbo Chirwa", "DemoLaboratory1!", ["SERVICE_PROVIDER"]),
    ("research", "Kudzai Ncube", "DemoResearch1!", ["RESEARCHER", "MANAGER"]),
]
# Name lists used by v1/v2 preparations; kept only to recognise and refresh those names.
LEGACY_FIRST = "Anesu Chiedza Tinashe Nyasha Rutendo Farai Rumbidzai Tapiwa Vimbai Tatenda Kudzai Chipo Simbarashe Rudo Tafadzwa Tendai Shingai Natsai Munashe Ruvimbo".split()
LEGACY_LAST = "Moyo Dube Ndlovu Banda Ncube Chirwa Mupfumi Sibanda Mlambo Chikore Maposa Mavhunga Nyathi Chikomo Mathe Zhou Mupunga Chuma Shava Moyo-Ncube".split()
# Minutes of service per stage for the earlier steps of a scripted journey.
SERVICE_MINUTES = {"registration": (2, 5), "triage": (4, 9), "consultation": (9, 18), "laboratory": (6, 12), "pharmacy": (3, 7)}
# Urgency mix for completed history. P1 is left out: an immediate case is escalated, not queued FCFS.
HISTORY_URGENCY = (("P2", .06), ("P3", .32), ("P4", .42), ("P5", .20))


# Weekday hours in which a prepared morning looks natural; outside them a note is shown.
CLINIC_HOURS = (7, 16)
STALE_AFTER_HOURS = 8
SCRIPTED_REVIEW_NOTE = ("Scripted demonstration review, recorded automatically because the operator prepared this "
    "fictional clinic with the advisory enabled. No clinician reviewed this model. Not clinical validation.")


def preparation_note(local):
    """Plain-language warning when the rehearsal is prepared outside clinic hours."""
    if local.weekday() < 5 and CLINIC_HOURS[0] <= local.hour < CLINIC_HOURS[1]:
        return None
    return (f"Prepared {local:%A at %H:%M} local time, outside typical clinic hours (weekdays "
            f"{CLINIC_HOURS[0]:02d}:00–{CLINIC_HOURS[1]:02d}:00). Today's arrivals sit in the hours just before "
            "preparation, so the clinic morning appears at this time. Prepare again during clinic hours for a natural timeline.")


def is_stale(session, now):
    return (now - session.anchor_at).total_seconds() > STALE_AFTER_HOURS * 3600


def apply_demo_review(db, job, model):
    """Review and enable a freshly trained model, only when preparation explicitly asked (ADR-038)."""
    facility = db.get(Facility, job.facility_id)
    if not facility or facility.id != FACILITY_ID or not facility.demo_mode or model.status == "RETIRED":
        return False
    old = {"status": model.status, "active": model.active}
    if model.status == "EXPERIMENTAL":
        model.status, model.reviewed_by, model.review_note = "REVIEWED", uuid.UUID(job.config_json["review_clinician_id"]), SCRIPTED_REVIEW_NOTE
    for other in db.scalars(select(ModelVersion).where(ModelVersion.facility_id == facility.id, ModelVersion.id != model.id)):
        other.active = False
    model.active = True
    record_audit(db, facility_id=facility.id, actor_id=None, action="demo.advisory_enabled_by_preparation", object_type="ModelVersion",
        object_id=model.id, correlation_id=str(job.id), old=old, new={"status": model.status, "active": True},
        reason=SCRIPTED_REVIEW_NOTE)
    return True


def ident(name):
    return uuid.uuid5(FACILITY_ID, name)


def historical_paths(seed, day_index):
    rng = random.Random(f"{seed}:{day_index}")
    env = simpy.Environment()
    resources = {kind: simpy.Resource(env, capacity=capacity) for _, kind, capacity in POINTS}
    rows = []
    means = {"registration": 4, "triage": 7, "consultation": 18, "laboratory": 13, "pharmacy": 6}
    arrivals = sorted(rng.triangular(0, 300, 55) for _ in range(24))
    def journey(index, at, route, durations):
        yield env.timeout(at)
        stages = []
        for kind, duration in zip(route, durations):
            queued = env.now
            with resources[kind].request() as request:
                yield request
                started = env.now
                yield env.timeout(duration)
                stages.append((kind, queued, started, env.now))
        rows.append((index, at, stages))
    for index, at in enumerate(arrivals):
        route = ["registration", "triage", "consultation"]
        if index % 7 == 0: route += ["laboratory", "consultation"]
        if index % 4: route += ["pharmacy"]
        durations = [max(2, min(40, rng.lognormvariate(0, .35) * means[k])) for k in route]
        env.process(journey(index, at, route, durations))
    env.run()
    return sorted(rows)


def prepare_clinic(db, *, seed=2026, fresh=False, now=None, enable_advisory=False, if_stale=False, close_manual=False):
    if not 0 <= seed <= 1_000_000_000: raise ValueError("Seed must be between 0 and 1,000,000,000")
    anchor = (now or utcnow()).astimezone(timezone.utc).replace(microsecond=0)
    # Serialise even the first preparation; this CLI never resets another facility.
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy import text
        db.execute(text("SELECT pg_advisory_xact_lock(724301030)"))
    facility = db.get(Facility, FACILITY_ID)
    if not facility:
        facility = Facility(id=FACILITY_ID, name="Hutano Community Clinic", timezone="Africa/Harare", demo_mode=True)
        db.add(facility); db.flush()
    if not facility.demo_mode: raise ValueError("The fictional clinic must remain in demo mode")
    # Local schedule times follow the facility's configured timezone, not a hard-coded one.
    local = anchor.astimezone(ZoneInfo(facility.timezone))
    db.scalar(select(Facility.id).where(Facility.id==facility.id).with_for_update())
    previous = db.scalar(select(DemoSession).where(DemoSession.facility_id == facility.id).order_by(DemoSession.created_at.desc()))
    if previous and not fresh and not (if_stale and is_stale(previous, anchor)):
        return previous
    users = {}
    for role, name, password, roles in STAFF:
        email = f"{role}@showcase.hutano.test"
        user = db.scalar(select(User).where(User.email == email))
        if user and user.facility_id != facility.id: raise ValueError("Demonstration account belongs to another facility")
        if not user:
            user = User(facility_id=facility.id, email=email, display_name=name, password_hash=hash_password(password))
            db.add(user); db.flush()
            for r in roles: db.add(UserRole(facility_id=facility.id, user_id=user.id, role=r))
        users[role] = user
    points = {}
    for name, kind, capacity in POINTS:
        point = db.scalar(select(ServicePoint).where(ServicePoint.facility_id == facility.id, ServicePoint.type == kind))
        if not point:
            point = ServicePoint(facility_id=facility.id, name=name, type=kind, capacity=capacity)
            db.add(point); db.flush()
        points[kind] = point
    policy = db.scalar(select(QueuePolicy).where(QueuePolicy.facility_id == facility.id, QueuePolicy.active.is_(True)))
    if not policy:
        db.add(QueuePolicy(facility_id=facility.id, version="demo-hybrid-v1", config_json={"urgency_order":["P1","P2","P3","P4","P5"],"ageing_scope":"within_confirmed_urgency_only","waiting_weight":.25,"urgency_weight":1.,"capacity_weight":0.,"long_wait_warning_minutes":60,"clinical_review_status":"DEMO_NOT_CLINICALLY_APPROVED"}))
    # Only unfinished fixtures listed by earlier preparations may be retired.
    for session in db.scalars(select(DemoSession).where(DemoSession.facility_id == facility.id)):
        for item in session.manifest_json["cases"]:
            visit = db.get(Visit, uuid.UUID(item["visit_id"]))
            if not visit or visit.facility_id != facility.id or visit.status not in ACTIVE_VISIT_STATES: continue
            for episode in visit.episodes:
                if episode.status not in {"COMPLETED","CANCELLED","NO_SHOW","TRANSFERRED","SKIPPED"}:
                    transition_episode(db, episode, expected={episode.status}, target="CANCELLED", actor_id=users["admin"].id, expected_version=episode.version)
            visit.status = "CANCELLED"; visit.version += 1
            record_audit(db, facility_id=facility.id, actor_id=users["admin"].id, action="demo.fixture_retired", object_type="Visit", object_id=visit.id, correlation_id=str(session.id), reason="Explicit fresh rehearsal; scripted fixture preserved as cancelled")
    if close_manual:
        # Practice registrations from earlier rehearsals; only when explicitly asked (fictional clinic only).
        for visit in db.scalars(select(Visit).where(Visit.facility_id == facility.id, Visit.status.in_(ACTIVE_VISIT_STATES))):
            for episode in visit.episodes:
                if episode.status not in {"COMPLETED","CANCELLED","NO_SHOW","TRANSFERRED","SKIPPED"}:
                    transition_episode(db, episode, expected={episode.status}, target="CANCELLED", actor_id=users["admin"].id, expected_version=episode.version)
            visit.status = "CANCELLED"; visit.version += 1
            record_audit(db, facility_id=facility.id, actor_id=users["admin"].id, action="demo.practice_visit_closed", object_type="Visit", object_id=visit.id, correlation_id="fresh-rehearsal", reason="Fresh rehearsal asked to close visits entered during earlier practice; history preserved as cancelled")
    db.flush()
    session_id = uuid.uuid4()
    patients = []
    refreshed_names=0
    for i in range(300):
        patient = db.get(Patient, ident(f"patient:{i}"))
        if i < len(CAST):
            c=CAST[i]; who={"name":c.name,"sex":c.sex,"age_band":c.age_band,"age":c.age}
        else:
            who=background_identity(i)
        legacy={f"{LEGACY_FIRST[i%20]} {LEGACY_LAST[i//20]}", f"{LEGACY_FIRST[i%20]} {LEGACY_LAST[(i*7+i//20)%20]}"}
        if not patient:
            patient = Patient(id=ident(f"patient:{i}"), facility_id=facility.id, synthetic_flag=True)
            db.add(patient)
        elif not (patient.synthetic_flag and patient.pseudonym in legacy and patient.pseudonym != who["name"]):
            patients.append(patient); continue
        else:
            refreshed_names+=1
        patient.pseudonym=who["name"]; patient.sex=who["sex"]; patient.age_band=who["age_band"]; patient.year_of_birth=local.year-who["age"]
        patients.append(patient)
    if refreshed_names:
        record_audit(db,facility_id=facility.id,actor_id=None,action="demo.fictional_names_refreshed",object_type="Facility",object_id=facility.id,correlation_id=str(session_id),new={"count":refreshed_names,"version":VERSION},reason="Replace earlier generated fictional identities with sex- and age-consistent ones; only unchanged v1/v2 pseudonyms matched")
    db.flush()
    actors = {k: users[{"registration":"reception","triage":"triage","consultation":"clinician","pharmacy":"pharmacy","laboratory":"laboratory","discharge":"reception"}[k]] for k in points}
    def episode(visit, kind, sequence, queued, start=None, end=None, status="COMPLETED", category=None, reason=None):
        actor = actors[kind]
        ep = ServiceEpisode(facility_id=facility.id, visit_id=visit.id, service_point_id=points[kind].id, sequence_no=sequence, status=status, queued_at=queued, called_at=start, started_at=start, ended_at=end, clinician_id=actor.id if start else None, created_at=queued)
        if status == "PAUSED": ep.paused_at = anchor-timedelta(minutes=2)
        db.add(ep); db.flush()
        db.add(QueueEntry(facility_id=facility.id, episode_id=ep.id, service_point_id=points[kind].id, status=status, joined_at=queued, original_order=int(queued.timestamp()), created_at=queued))
        states = [("PLANNED","WAITING",queued)]
        if start: states += [("WAITING","CALLED",start),("CALLED","IN_SERVICE",start)]
        if end: states += [("IN_SERVICE","COMPLETED",end)]
        if status in {"PAUSED","ESCALATION_REQUIRED"}: states += [("IN_SERVICE" if start else "WAITING",status,ep.paused_at or queued)]
        for before, after, at in states:
            db.add(QueueStateEvent(facility_id=facility.id, episode_id=ep.id, actor_id=actor.id, from_status=before, to_status=after, occurred_at=at, metadata_json={"scripted_demo":True,"version":VERSION}))
        if kind == "registration" and end: visit.registered_at=end
        if kind == "triage" and category:
            db.add(TriageAssessment(facility_id=facility.id, visit_id=visit.id, assessor_id=users["triage"].id, configured_urgency=category, reason=reason or "Fictional triage assessment", assessed_at=end or queued))
        return ep
    def new_visit(patient, arrival, route, status, number, visit_id=None):
        visit_id = visit_id or uuid.uuid4()
        token = f"A-{number:03d}"
        visit = Visit(id=visit_id, facility_id=facility.id, patient_id=patient.id, public_token=token, token_day=arrival.astimezone(ZoneInfo(facility.timezone)).date(), token_secret_hash=token_digest(status_secret(visit_id,token)), arrival_at=arrival, created_at=arrival, status=status, visit_type="follow_up" if db.scalar(select(Visit.id).where(Visit.patient_id==patient.id).limit(1)) else "walk_in", planned_services=route[1:])
        db.add(visit); db.flush(); return visit
    historical = 0
    # Scripted first-time patients have no earlier visits; returning ones do.
    pool = [p for i, p in enumerate(patients) if i >= len(CAST) or CAST[i].returning]
    slot = 0
    cast_by_patient = {patients[i].id: case for i, case in enumerate(CAST)}
    # Every weekday has 24 historical arrivals; find each pool member's final slot.
    total_slots = 24*sum((local.date()-timedelta(days=21-d)).weekday() < 5 for d in range(21))
    last_slot = {p.id: k + (total_slots-1-k)//len(pool)*len(pool) for k, p in enumerate(pool) if k < total_slots}
    def observe(visit, values, at):
        for code, value in values.items():
            if value is None: continue
            db.add(Observation(facility_id=facility.id, visit_id=visit.id, field_code=code, value=str(value), unit=FIELDS[code][1], source="fictional_demo", entered_by=users["triage"].id, observed_at=at))
    for day_index in range(21):
        day = local.date()-timedelta(days=21-day_index)
        if day.weekday() >= 5: continue
        opening = datetime.combine(day, datetime.min.time(), ZoneInfo(facility.timezone)).replace(hour=8).astimezone(timezone.utc)
        for index, at, stages in historical_paths(seed, day_index):
            patient = pool[slot % len(pool)]; this_slot = slot; slot += 1
            visit_id = ident(f"history:{seed}:{day}:{index}")
            if db.get(Visit,visit_id): continue
            # Content uses its own stream so the SimPy timings above are unchanged.
            detail = random.Random(f"{seed}:{day}:{index}:detail")
            category = detail.choices([c for c, _ in HISTORY_URGENCY], [w for _, w in HISTORY_URGENCY])[0]
            band = patient.age_band if patient.age_band in CONCERNS else "adult"
            concern = detail.choice(CONCERNS[band])
            # A returning scripted patient's earlier visits explain why they are back today.
            if patient.id in cast_by_patient and this_slot == last_slot.get(patient.id):
                concern = cast_by_patient[patient.id].history or concern
            route = [s[0] for s in stages]
            # Never add a historical visit with the same display token as a staff-created record.
            number=(db.scalar(select(func.count(Visit.id)).where(Visit.facility_id==facility.id,Visit.token_day==day)) or 0)+1
            visit=new_visit(patient, opening+timedelta(minutes=at), route, "COMPLETED", number, visit_id)
            prior = None; consultations = 0
            for sequence,(kind,q,s,e) in enumerate(stages,1):
                ep=episode(visit,kind,sequence,opening+timedelta(minutes=q),opening+timedelta(minutes=s),opening+timedelta(minutes=e),category=category,reason=triage_reason(category, concern))
                if kind == "triage":
                    observe(visit, sample_vitals(detail, band, category), ep.ended_at)
                if kind == "consultation":
                    consultations += 1
                    opening_line = f"{concern}. History taken and examined." if consultations == 1 else "Returned with the laboratory result and reviewed."
                    db.add(EncounterNote(facility_id=facility.id,episode_id=ep.id,actor_id=actors[kind].id,text=f"{opening_line} {plan_text(route[sequence:])}",created_at=ep.ended_at))
                if kind in {"laboratory", "pharmacy"} and prior is not None:
                    db.add(Handover(facility_id=facility.id,visit_id=visit.id,source_episode_id=prior.id,target_point_id=points[kind].id,actor_id=actors["consultation"].id,
                        message="Blood test, then back to consultation with the result." if kind == "laboratory" else "Collect medicines.",
                        created_at=prior.ended_at,acknowledged_at=ep.started_at,acknowledged_by=actors[kind].id))
                prior = ep
            visit.completed_at=ep.ended_at; historical+=1
    # Staff schedules are explicit rehearsal windows around preparation time.
    rooms={}
    for name,kind,staff in [("Consultation room 1","consultation","clinician"),("Consultation room 2","consultation","provider"),("Triage desk","triage","triage"),("Pharmacy counter","pharmacy","pharmacy"),("Laboratory room","laboratory","laboratory")]:
        room=db.scalar(select(Room).where(Room.facility_id==facility.id,Room.name==name))
        if not room:
            room=Room(facility_id=facility.id,name=name,service_point_id=points[kind].id);db.add(room);db.flush()
        rooms[name]=(room,users[staff])
        shifts=db.scalars(select(StaffShift).where(StaffShift.facility_id==facility.id,StaffShift.room_id==room.id,StaffShift.cancelled.is_(False),StaffShift.ends_at>anchor)).all()
        if not shifts:
            db.add(StaffShift(facility_id=facility.id,room_id=room.id,staff_id=users[staff].id,starts_at=anchor-timedelta(hours=2),ends_at=anchor+timedelta(hours=8)))
            db.add(ResourceBlock(facility_id=facility.id,staff_id=users[staff].id,starts_at=anchor+timedelta(minutes=90),ends_at=anchor+timedelta(minutes=110),reason="Fictional roster: scheduled staff break"))
    db.flush()
    planned=[]
    for i,case in enumerate(CAST):
        patient=patients[i]
        if db.scalar(select(Visit.id).where(Visit.patient_id==patient.id,Visit.status.in_(ACTIVE_VISIT_STATES))):
            continue # An independently registered encounter is preserved.
        if case.state in {"IN_SERVICE","PAUSED"}:
            room,staff=rooms["Consultation room 1" if case.state=="IN_SERVICE" else "Consultation room 2"]
            if db.scalar(select(ResourceAssignment.id).where(ResourceAssignment.released_at.is_(None),
                (ResourceAssignment.room_id==room.id)|(ResourceAssignment.staff_id==staff.id))):
                continue # Never displace a staff-created room reservation.
        route=["registration"] if case.stage=="registration" else ["registration","triage"]
        if case.stage in {"consultation","laboratory","pharmacy"}: route += ["consultation"]
        if case.stage in {"laboratory","pharmacy"}: route += [case.stage]
        # Work backwards from the current queue so each step starts when the previous one ended.
        rng=random.Random(f"{seed}:case:{i}")
        minutes=lambda low,high: timedelta(seconds=round(rng.uniform(low,high)*60))
        q=anchor-timedelta(minutes=case.wait)
        if case.state=="IN_SERVICE": start,end=anchor-timedelta(minutes=6),None
        elif case.state=="PAUSED": start,end=anchor-timedelta(minutes=9),None
        elif case.state=="COMPLETED":
            start=q+min(minutes(4,10),timedelta(minutes=case.wait/3))
            end=min(start+minutes(*SERVICE_MINUTES[case.stage]),anchor-timedelta(minutes=1))
        else: start=end=None
        timing=[(q,start,end)]
        for stage in reversed(route[:-1]):
            stage_end=timing[0][0]; stage_start=stage_end-minutes(*SERVICE_MINUTES[stage])
            timing.insert(0,(stage_start-minutes(3,14),stage_start,stage_end))
        planned.append((timing[0][0],i,case,patient,route,timing))
    created={}
    # Created in arrival order, so token numbers rise through the morning as at a real desk.
    for arrival,i,case,patient,route,timing in sorted(planned,key=lambda row:row[0]):
        state=case.state
        number=(db.scalar(select(func.count(Visit.id)).where(Visit.facility_id==facility.id,Visit.token_day==arrival.astimezone(ZoneInfo(facility.timezone)).date())) or 0)+1
        status="COMPLETED" if state=="COMPLETED" else "ESCALATION_REQUIRED" if state=="ESCALATION_REQUIRED" else "REGISTERING" if case.stage=="registration" else "AWAITING_TRIAGE" if case.stage=="triage" else "ACTIVE"
        visit=new_visit(patient,arrival,route,status,number)
        visit.visit_type=case.visit_type
        room_staff=users["provider"] if state=="PAUSED" else users["clinician"]
        prior=None
        for sequence,(stage,(q,start,end)) in enumerate(zip(route,timing),1):
            final=sequence==len(route)
            ep=episode(visit,stage,sequence,q,start,end,state if final else "COMPLETED",case.category,
                       reason=triage_reason(case.category,case.concern) if case.category else None)
            if stage=="triage" and case.category:
                observe(visit,case.vitals,end or q)
            if stage=="consultation" and start and case.note:
                db.add(EncounterNote(facility_id=facility.id,episode_id=ep.id,actor_id=room_staff.id,text=case.note,created_at=end or anchor-timedelta(minutes=2)))
            if final and case.stage in {"laboratory","pharmacy"} and prior:
                db.add(Handover(facility_id=facility.id,visit_id=visit.id,source_episode_id=prior.id,target_point_id=points[case.stage].id,actor_id=users["clinician"].id,message=case.handover,created_at=q,acknowledged_at=start if state=="COMPLETED" else None,acknowledged_by=actors[case.stage].id if state=="COMPLETED" else None))
            prior=ep
        if state=="COMPLETED": visit.completed_at=ep.ended_at
        if state in {"IN_SERVICE","PAUSED"}:
            room,staff=rooms["Consultation room 1" if state=="IN_SERVICE" else "Consultation room 2"]
            if not db.scalar(select(ResourceAssignment.id).where(ResourceAssignment.room_id==room.id,ResourceAssignment.released_at.is_(None))):
                ep.clinician_id=staff.id
                db.add(ResourceAssignment(facility_id=facility.id,episode_id=ep.id,room_id=room.id,staff_id=staff.id,approved_by=users["clinician"].id,approved_at=ep.started_at,started_at=ep.started_at,prediction_json={"scripted_demo":True}))
        created[i]={"patient_id":str(patient.id),"visit_id":str(visit.id),"story":case.story,"concern":case.concern,"initial_stage":case.stage,"initial_status":state}
    # The guide lists cases in walkthrough order, not creation order.
    cases=[created[i] for i in sorted(created)]
    frame=generate_synthetic_training_data(seed=seed)
    payload=frame.to_csv(index=False).encode();digest=hashlib.sha256(payload).hexdigest()
    directory=settings.model_artifact_dir/str(facility.id);directory.mkdir(parents=True,exist_ok=True)
    path=directory/f"dataset-{digest}.csv";path.write_bytes(payload);path.chmod(0o600)
    dataset=db.scalar(select(Dataset).where(Dataset.facility_id==facility.id,Dataset.dataset_hash==digest))
    if not dataset:
        dataset=Dataset(facility_id=facility.id,name="Fictional clinic · advisory methods dataset",source_type="SYNTHETIC",dataset_hash=digest,consent_basis_note="Locally generated fictional examples. No patients or recruited participants.",schema_json={"columns":list(frame.columns),"label_source":"synthetic","operational_cohort_link":"NONE: separate methods dataset"},row_count=len(frame),synthetic_flag=True,file_path=str(path))
        db.add(dataset);db.flush()
    dataset.file_path=str(path)
    # A synthetic time-and-motion baseline (proposal Objective 1), so the Evaluation view and
    # baseline-calibrated simulation can be demonstrated without a field study.
    from app.baseline import inspect_baseline
    from app.simulation.calibration import synthetic_baseline_csv
    raw=synthetic_baseline_csv(days=15,seed=seed,zone_name=facility.timezone,start=anchor).encode()
    baseline_hash=hashlib.sha256(raw).hexdigest()
    if not db.scalar(select(Dataset).where(Dataset.facility_id==facility.id,Dataset.dataset_hash==baseline_hash)):
        frame_baseline,report=inspect_baseline(raw,{},facility.timezone)
        db.add(Dataset(facility_id=facility.id,name="Fictional clinic · synthetic time-and-motion baseline",source_type="SYNTHETIC_BASELINE",dataset_hash=baseline_hash,
            consent_basis_note="Generated by FCFS simulation of 15 walk-in days; not observed facility data.",
            schema_json={"columns":sorted(["journey_no","stage","arrived_at","queued_at","started_at","ended_at"]),"report":report,"label_source":"SYNTHETIC"},
            row_count=len(frame_baseline),synthetic_flag=True))
        db.flush()
    jobs=[]
    # Every rehearsal starts from the same known state: the advisory is off until someone enables
    # it (or preparation was asked to). Earlier reviews remain recorded.
    if not enable_advisory:
        for model in db.scalars(select(ModelVersion).where(ModelVersion.facility_id==facility.id,ModelVersion.active.is_(True))):
            model.active=False
            record_audit(db,facility_id=facility.id,actor_id=None,action="demo.advisory_reset",object_type="ModelVersion",object_id=model.id,correlation_id=str(session_id),old={"active":True},new={"active":False},reason="Fresh rehearsal starts with the advisory disabled")
    train={"dataset_id":str(dataset.id),"seed":seed}
    if enable_advisory: train.update(demo_enable_advisory=True,review_clinician_id=str(users["clinician"].id))
    for kind,config in [("MODEL_TRAIN",train),("OPERATIONAL_TRAIN",{})]:
        job=Job(facility_id=facility.id,type=kind,config_json=config);db.add(job);db.flush();jobs.append(str(job.id))
    from app.schemas import SimulationCreate
    scenario_config=SimulationCreate(name="Fictional clinic · morning queue comparison",seed=seed,patient_count=150,replications=10,consultation_servers=2,arrival_rate_per_hour=12,mean_service_minutes=12)
    scenario=SimulationScenario(facility_id=facility.id,owner_id=users["research"].id,name=scenario_config.name,scenario_json=scenario_config.model_dump(mode="json"),synthetic_flag=True)
    db.add(scenario);db.flush()
    run=SimulationRun(facility_id=facility.id,scenario_id=scenario.id,policy="COMPARISON",seed=seed,replications=10,status="PENDING",started_at=anchor)
    db.add(run);db.flush()
    config=scenario_config.model_dump(exclude={"name","high_load","consultation_servers"})
    config["servers"]=scenario_config.consultation_servers
    job=Job(facility_id=facility.id,type="SIMULATION",config_json=config,result_ref=str(run.id))
    db.add(job);db.flush();jobs.append(str(job.id))
    manifest={"fictional":True,"preparation_note":preparation_note(local),"advisory_enabled_by_preparation":enable_advisory,"historical_visits_added":historical,"history_method":"Seeded FCFS SimPy stages; 24 arrivals per weekday over preceding 21 calendar days. Illustrative inputs, not observed facility measurements.","cases":cases,"jobs":jobs,"dataset_id":str(dataset.id),"warning":"All identities, rosters, observations and assessments are scripted fictional fixtures. No actual clinician review, participant consent or model activation is fabricated."}
    session=DemoSession(id=session_id,facility_id=facility.id,version=VERSION,anchor_at=anchor,seed=seed,manifest_json=manifest)
    db.add(session)
    record_audit(db,facility_id=facility.id,actor_id=None,action="demo.clinic_prepared",object_type="DemoSession",object_id=session_id,correlation_id=str(session_id),new={"version":VERSION,"seed":seed,"historical_visits":historical,"cases":len(cases)},reason="Explicit fictional rehearsal preparation; original workspace unchanged")
    enqueue_event(db,facility_id=facility.id,topic="visit.state_changed",aggregate_id=session_id)
    db.flush()
    return session
