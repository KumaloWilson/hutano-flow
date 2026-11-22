import argparse
import os
import sys
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import (
    Facility,
    Patient,
    QueueEntry,
    ServiceEpisode,
    ServicePoint,
    TriageAssessment,
    User,
    Visit,
    QueueStateEvent,
)
from app.services.audit import record_audit


def generate_completed_visits(count: int, seed: int) -> None:
    if not 1 <= count <= 10000 or seed < 0:
        raise ValueError("Use 1–10,000 synthetic visits and a non-negative seed")
    with SessionLocal() as db:
        clinician = db.scalar(select(User).where(User.email == "clinician@demo.hutano.test"))
        facility = db.scalar(select(Facility).where(Facility.id == clinician.facility_id, Facility.demo_mode.is_(True)).with_for_update()) if clinician else None
        if not facility:
            raise RuntimeError("Run the demo seed before generating visits")
        points = {point.type: point for point in db.scalars(select(ServicePoint).where(ServicePoint.facility_id == facility.id))}
        if not facility or not clinician or not points:
            raise RuntimeError("Run the demo seed before generating visits")
        day = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
        inserted = 0
        for index in range(count):
            rng = np.random.default_rng(np.random.SeedSequence([seed, index]))
            opaque = f"generated-{seed}-{index}"
            digest = hashlib.sha256(opaque.encode()).digest()
            if db.scalar(select(Visit.id).where(Visit.facility_id == facility.id, Visit.token_secret_hash == digest)):
                continue
            patient = Patient(facility_id=facility.id, pseudonym=f"Synthetic {seed}-{index + 1:03d}", age_band=str(rng.choice(["child", "adult", "older_adult"])), sex=str(rng.choice(["female", "male", "not_recorded"])), synthetic_flag=True)
            db.add(patient)
            db.flush()
            arrival = day + timedelta(days=index % 21, minutes=float((index // 21) * 20 + rng.uniform(0, 3)))
            visit = Visit(facility_id=facility.id, patient_id=patient.id, public_token=f"G-{seed}-{index + 1:03d}", token_day=arrival.date(), token_secret_hash=digest, arrival_at=arrival, status="COMPLETED", visit_type="walk_in", planned_services=["triage", "consultation", "pharmacy"])
            db.add(visit)
            db.flush()
            urgency = str(rng.choice(["P1", "P2", "P3", "P4", "P5"], p=[0.03, 0.09, 0.23, 0.4, 0.25]))
            cursor = arrival
            for sequence, point_type in enumerate(["registration", "triage", "consultation", "pharmacy"], start=1):
                wait = float(rng.uniform(2, 30))
                service = float(rng.uniform(2, 14))
                queued = cursor
                started = queued + timedelta(minutes=wait)
                ended = started + timedelta(minutes=service)
                episode = ServiceEpisode(facility_id=facility.id, visit_id=visit.id, service_point_id=points[point_type].id, sequence_no=sequence, status="COMPLETED", queued_at=queued, called_at=started, started_at=started, ended_at=ended, clinician_id=clinician.id)
                db.add(episode)
                db.flush()
                db.add(QueueEntry(facility_id=facility.id, episode_id=episode.id, service_point_id=points[point_type].id, status="COMPLETED", joined_at=queued, original_order=index + 1))
                for before, after, at in [("PLANNED", "WAITING", queued), ("WAITING", "CALLED", started), ("CALLED", "IN_SERVICE", started), ("IN_SERVICE", "COMPLETED", ended)]:
                    db.add(QueueStateEvent(facility_id=facility.id, episode_id=episode.id, actor_id=clinician.id,
                        from_status=before, to_status=after, occurred_at=at, metadata_json={"synthetic_generator": True, "seed": seed}))
                if point_type == "registration":
                    visit.registered_at = ended
                if point_type == "triage":
                    db.add(TriageAssessment(facility_id=facility.id, visit_id=visit.id, assessor_id=clinician.id,
                        configured_urgency=urgency, reason="Synthetic generated reference label", assessed_at=ended))
                cursor = ended
            visit.completed_at = cursor
            inserted += 1
            if (index + 1) % 100 == 0:
                db.flush()
        record_audit(db, facility_id=facility.id, actor_id=None, action="synthetic.generated", object_type="Facility",
            object_id=facility.id, correlation_id=f"seed-{seed}", new={"seed": seed, "inserted": inserted, "requested": count},
            reason="Seeded independent synthetic timings; not observed clinic data")
        db.commit()
        print(f"Generated {inserted} completed synthetic visits with seed {seed}; {count - inserted} already present")


def export_openapi(path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(f"Wrote {target}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    synthetic = sub.add_parser("synthetic")
    synthetic.add_argument("--count", type=int, default=300)
    synthetic.add_argument("--seed", type=int, default=2026)
    openapi = sub.add_parser("openapi")
    openapi.add_argument("--path", default="docs/API_OPENAPI.json")
    showcase = sub.add_parser("showcase", help="Prepare a separate, explicitly fictional clinic")
    showcase.add_argument("--seed", type=int, default=2026)
    showcase.add_argument("--fresh", action="store_true", help="Retire only earlier scripted active cases and start another rehearsal")
    showcase.add_argument("--close-manual", action="store_true", help="With --fresh: also close unfinished visits entered by hand during earlier practice (history kept)")
    showcase.add_argument("--if-stale", action="store_true", help=f"Start a fresh rehearsal only when the current one is older than 8 hours (used at boot)")
    showcase.add_argument("--with-reviewed-advisory", action="store_true", default=os.getenv("SHOWCASE_REVIEWED_ADVISORY", "").lower() == "true",
        help="Record a clearly labelled scripted review and enable the trained advisory (fictional clinic only)")
    args = parser.parse_args()
    if args.command == "synthetic":
        generate_completed_visits(args.count, args.seed)
    elif args.command == "showcase":
        from app.demo_clinic import prepare_clinic
        with SessionLocal() as db:
            session = prepare_clinic(db, seed=args.seed, fresh=args.fresh, if_stale=args.if_stale, enable_advisory=args.with_reviewed_advisory, close_manual=args.close_manual and args.fresh)
            db.commit()
            if session.manifest_json.get("preparation_note"):
                print("NOTE: " + session.manifest_json["preparation_note"], file=sys.stderr)
            print(json.dumps({"facility":"Hutano Community Clinic", "session_id":str(session.id), "prepared_at":session.anchor_at.isoformat(), "advisory_enabled_by_preparation":session.manifest_json.get("advisory_enabled_by_preparation", False), "historical_visits_added":session.manifest_json["historical_visits_added"], "scripted_cases":len(session.manifest_json["cases"]), "research_jobs":session.manifest_json["jobs"], "account_domain":"showcase.hutano.test", "fictional":True}))
    else:
        export_openapi(args.path)


if __name__ == "__main__":
    main()

