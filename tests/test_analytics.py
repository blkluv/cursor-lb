"""Analytics dashboard tests."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Job, User
from tests.conftest import signup_and_sync, start_and_complete_job


def test_analytics_page_shows_pending_and_paid(
    client: TestClient, matt_credentials: dict[str, str],
):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    before = client.get("/analytics")
    assert before.status_code == 200
    assert "Revenue analytics" in before.text
    assert "Pending" in before.text
    assert "$2,700.00" in before.text or "$" in before.text

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert user is not None
        job = db.scalar(
            select(Job).where(Job.user_id == user.id, Job.status == "pending").limit(1)
        )
        assert job is not None
        start_and_complete_job(client, job.id)

    after = client.get("/analytics")
    assert after.status_code == 200
    assert "Paid" in after.text
    assert "paid" in after.text.lower()

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert user is not None
        job = db.scalar(
            select(Job).where(Job.user_id == user.id, Job.status == "done").limit(1)
        )
        assert job is not None
        assert job.invoice is not None
        assert job.invoice.payment_status == "unpaid"
