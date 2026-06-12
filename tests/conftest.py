import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("AUTH_MODE", "dev")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("RATE_LIMIT_PUBLIC", "1000")
os.environ.setdefault("RATE_LIMIT_AUTH", "5")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.rate_limit import reset_counters

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    reset_counters()
    yield


@pytest.fixture
def db():
    session = TestingSessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    response = client.post(
        "/auth/dev-login", json={"email": "tester@wajz.app", "display_name": "Tester"}
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    return {"X-Admin-Token": "test-admin-token"}


@pytest.fixture
def demo_data(db):
    """Seed demo articles and run the full (heuristic) pipeline."""
    from app.seeds import seed_demo

    seed_demo(db)
    return db
