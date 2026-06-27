"""Shared test fixtures."""

import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["EMAIL_MODE"] = "mock"
os.environ["PHOTOGRAPHER_EMAIL"] = ""

import app.models as _models  # noqa: E402, F401 — register tables on Base.metadata
from app.config import settings  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

EMAIL_LOG = Path(__file__).resolve().parent.parent / "logs" / "email_mock.log"


@pytest.fixture(autouse=True)
def clear_studio_photographer_email(monkeypatch: pytest.MonkeyPatch):
    """Tests opt in to PHOTOGRAPHER_EMAIL; production uses .env studio owner."""
    monkeypatch.setattr(settings, "photographer_email", "")


@pytest.fixture(autouse=True)
def clean_db(client: TestClient):
    """Isolate tests — in-memory SQLite + StaticPool shares one connection per process."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    client.cookies.clear()
    EMAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_LOG.write_text("")
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def matt_credentials() -> dict[str, str]:
    return {
        "email": f"matt-{uuid.uuid4().hex[:8]}@studio.com",
        "password": "studio123",
    }


def signup_and_sync(client: TestClient, email: str, password: str) -> None:
    """Sign up and load dashboard so mock jobs sync to the new user."""
    r = client.post(
        "/signup",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/dashboard"
    sync = client.get("/dashboard")
    assert sync.status_code == 200


def login(client: TestClient, email: str, password: str) -> None:
    r = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/dashboard"
    client.get("/dashboard")


def start_and_complete_job(client: TestClient, job_id: int) -> None:
    r = client.post(f"/jobs/{job_id}/start", follow_redirects=False)
    assert r.status_code == 302
    r = client.post(f"/jobs/{job_id}/complete", follow_redirects=False)
    assert r.status_code == 302
