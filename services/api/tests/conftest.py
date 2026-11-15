import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test-hutano.sqlite3")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-more-than-thirty-two-characters")
os.environ.setdefault("RESEARCH_MODE", "true")
os.environ.setdefault("MODEL_ARTIFACT_DIR", "artifacts")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Dataset, Facility, QueuePolicy, ServicePoint, User, UserRole
from app.security import hash_password, rate_limiter


@pytest.fixture(autouse=True)
def isolated_rate_limits():
    # A fresh application lifespan per test must not inherit another test's IP quota.
    # Limits remain enabled, including for explicit rate-limit regression tests.
    rate_limiter._events.clear()
    yield
    rate_limiter._events.clear()


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    db = TestingSession()
    facility = Facility(name="Test Demo Clinic", demo_mode=True)
    other = Facility(name="Other Demo Clinic", demo_mode=True)
    db.add_all([facility, other]); db.flush()
    for name, point_type, capacity in [
        ("Registration", "registration", 1), ("Triage", "triage", 1),
        ("Consultation", "consultation", 2), ("Pharmacy", "pharmacy", 1),
    ]:
        db.add(ServicePoint(facility_id=facility.id, name=name, type=point_type, capacity=capacity))
    users = [
        ("reception@test.local", "Reception", ["RECEPTIONIST"]),
        ("clinician@test.local", "Clinician", ["CLINICIAN", "SERVICE_PROVIDER"]),
        ("research@test.local", "Research", ["RESEARCHER", "MANAGER"]),
        ("admin@test.local", "Admin", ["ADMIN"]),
        ("pharmacy@test.local", "Pharmacy", ["PHARMACY"]),
        ("other@test.local", "Other", ["ADMIN"]),
    ]
    for email, name, roles in users:
        target = other if email.startswith("other") else facility
        user = User(facility_id=target.id, email=email, display_name=name, password_hash=hash_password("Testing123!"))
        db.add(user); db.flush()
        for role in roles:
            db.add(UserRole(user_id=user.id, facility_id=target.id, role=role))
    db.add(QueuePolicy(facility_id=facility.id, version="demo-hybrid-v1", config_json={"ageing_scope": "within_confirmed_urgency_only"}))
    db.add(Dataset(facility_id=facility.id, name="Synthetic seed", source_type="SYNTHETIC", dataset_hash="a" * 64, consent_basis_note="Synthetic local test data only", schema_json={}, row_count=300, synthetic_flag=True))
    db.commit()

    def override_db():
        try:
            db.expire_all()
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    yield db
    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def client(db_session):
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, email: str) -> str:
    csrf = client.cookies.get("hutano_csrf")
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "Testing123!"}, headers={"X-CSRF-Token": csrf} if csrf else {})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def command_headers(csrf: str, key: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf, "Idempotency-Key": key}

