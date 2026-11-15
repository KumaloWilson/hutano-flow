import hashlib

from sqlalchemy import select

from app.database import SessionLocal
from app.ml.pipeline import generate_synthetic_training_data
from app.models import Dataset, Facility, QueuePolicy, ServicePoint, User, UserRole
from app.security import hash_password
from app.config import settings


DEMO_USERS = [
    ("admin@demo.hutano.test", "Demo Administrator", "DemoAdmin1!", ["ADMIN"]),
    ("reception@demo.hutano.test", "Demo Receptionist", "DemoReception1!", ["RECEPTIONIST"]),
    ("triage@demo.hutano.test", "Demo Triage Nurse", "DemoTriage1!", ["TRIAGE_NURSE"]),
    ("clinician@demo.hutano.test", "Demo Clinician", "DemoClinician1!", ["CLINICIAN", "SERVICE_PROVIDER"]),
    ("pharmacy@demo.hutano.test", "Demo Pharmacist", "DemoPharmacy1!", ["PHARMACY"]),
    ("research@demo.hutano.test", "Demo Researcher", "DemoResearch1!", ["RESEARCHER", "MANAGER"]),
]

POINTS = [
    ("Registration", "registration", 2),
    ("Triage", "triage", 1),
    ("Consultation", "consultation", 2),
    ("Pharmacy", "pharmacy", 1),
    ("Laboratory", "laboratory", 1),
    ("Discharge", "discharge", 1),
]


def seed() -> None:
    with SessionLocal() as db:
        facility = db.scalar(select(Facility).where(Facility.name == "Demo Outpatient Clinic"))
        if not facility:
            facility = Facility(name="Demo Outpatient Clinic", timezone="Africa/Harare", demo_mode=True)
            db.add(facility)
            db.flush()
        for name, point_type, capacity in POINTS:
            exists = db.scalar(select(ServicePoint).where(ServicePoint.facility_id == facility.id, ServicePoint.type == point_type))
            if not exists:
                db.add(ServicePoint(facility_id=facility.id, name=name, type=point_type, capacity=capacity))
        for email, display_name, password, roles in DEMO_USERS:
            user = db.scalar(select(User).where(User.email == email))
            if not user:
                user = User(facility_id=facility.id, email=email, display_name=display_name, password_hash=hash_password(password))
                db.add(user)
                db.flush()
                for role in roles:
                    db.add(UserRole(user_id=user.id, facility_id=facility.id, role=role))
        policy = db.scalar(select(QueuePolicy).where(QueuePolicy.facility_id == facility.id, QueuePolicy.version == "demo-hybrid-v1"))
        if not policy:
            db.add(
                QueuePolicy(
                    facility_id=facility.id,
                    version="demo-hybrid-v1",
                    config_json={
                        "urgency_order": ["P1", "P2", "P3", "P4", "P5"],
                        "ageing_scope": "within_confirmed_urgency_only",
                        "urgency_weight": 1.0,
                        "waiting_weight": 0.25,
                        "capacity_weight": 0.0,
                        "long_wait_warning_minutes": 60,
                        "clinical_review_status": "DEMO_NOT_CLINICALLY_APPROVED",
                    },
                )
            )
        frame = generate_synthetic_training_data()
        csv_bytes = frame.to_csv(index=False).encode()
        digest = hashlib.sha256(csv_bytes).hexdigest()
        directory = settings.model_artifact_dir / str(facility.id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"dataset-{digest}.csv"
        path.write_bytes(csv_bytes)
        path.chmod(0o600)
        dataset = db.scalar(select(Dataset).where(Dataset.dataset_hash == digest, Dataset.facility_id == facility.id))
        if not dataset:
            db.add(
                Dataset(
                    facility_id=facility.id,
                    name="Seeded synthetic urgency demonstration",
                    source_type="SYNTHETIC",
                    dataset_hash=digest,
                    consent_basis_note="Generated locally for software testing; contains no real people.",
                    schema_json={"columns": list(frame.columns), "label_source": "synthetic"},
                    row_count=len(frame),
                    synthetic_flag=True,
                    file_path=str(path),
                )
            )
        else:
            # The deterministic seed can be re-materialised after moving the demo
            # between host development and Docker's private artifact volume.
            dataset.file_path = str(path)
        db.commit()
        print("Demo seed is ready")


if __name__ == "__main__":
    seed()

