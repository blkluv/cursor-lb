"""Tests for payment due dates and reminder emails."""

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Invoice, Job, User
from app.repositories.invoices import create_invoice_for_job
from app.repositories.jobs import create_job, mark_job_done
from app.schemas import JobCreate
from app.services.payment_due import default_payment_due_date
from app.services.payment_reminders import send_payment_reminders
from tests.conftest import signup_and_sync, start_and_complete_job

EMAIL_LOG = Path(__file__).resolve().parent.parent / "logs" / "email_mock.log"


def _seed_unpaid_invoice(
    db,
    *,
    client_email: str = "remind@client.com",
    due_date: str,
    payment_status: str = "unpaid",
    reminder_sent_at: datetime | None = None,
) -> Invoice:
    photographer = db.scalar(select(User).where(User.role == "photographer"))
    assert photographer is not None
    job = create_job(
        db,
        photographer.id,
        JobCreate(
            client_name="Reminder Client",
            client_email=client_email,
            title=f"Reminder {client_email}",
            shoot_date="2026-10-01",
            amount_cents=10000,
            tax_rate=0.08,
        ),
    )
    mark_job_done(db, job)
    invoice = create_invoice_for_job(db, job)
    invoice.payment_due_date = due_date
    invoice.payment_status = payment_status
    invoice.payment_reminder_sent_at = reminder_sent_at
    if payment_status == "paid":
        invoice.paid_at = datetime.now(UTC)
    db.commit()
    db.refresh(invoice)
    return invoice


def test_invoice_gets_default_due_date_on_creation(
    client: TestClient, matt_credentials: dict[str, str], monkeypatch,
):
    """Due date defaults to DEFAULT_PAYMENT_DUE_DAYS after invoice is sent."""
    monkeypatch.setattr(settings, "default_payment_due_days", 14)
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    client.post(
        "/jobs/book",
        data={
            "client_name": "Default Due Client",
            "client_email": "duedate@client.com",
            "title": "Default due shoot",
            "shoot_date": "2026-10-01",
            "amount_dollars": "500.00",
            "tax_rate_percent": "8",
        },
        follow_redirects=False,
    )

    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.title == "Default due shoot"))
        assert job is not None
        job_id = job.id

    start_and_complete_job(client, job_id)

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        expected = default_payment_due_date(invoice.sent_at)
        assert invoice.payment_due_date == expected


def test_invoice_uses_job_payment_due_date_when_set(
    client: TestClient, matt_credentials: dict[str, str],
):
    """Matt can set payment due date when booking."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    custom_due = "2026-12-01"
    client.post(
        "/jobs/book",
        data={
            "client_name": "Custom Due Client",
            "client_email": "customdue@client.com",
            "title": "Custom due shoot",
            "shoot_date": "2026-10-01",
            "payment_due_date": custom_due,
            "amount_dollars": "500.00",
            "tax_rate_percent": "8",
        },
        follow_redirects=False,
    )

    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.title == "Custom due shoot"))
        assert job is not None
        job_id = job.id

    start_and_complete_job(client, job_id)

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        assert invoice.payment_due_date == custom_due


def test_reminder_script_sends_for_due_today_unpaid(
    client: TestClient, matt_credentials: dict[str, str],
):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    today = date(2026, 6, 25)
    email = "remind@client.com"

    with SessionLocal() as db:
        invoice = _seed_unpaid_invoice(
            db, client_email=email, due_date=today.isoformat(),
        )
        invoice_id = invoice.id

    EMAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_LOG.write_text("")

    with SessionLocal() as db:
        sent = send_payment_reminders(db, today=today)
    assert sent == 1

    log_text = EMAIL_LOG.read_text()
    assert "REMINDER" in log_text
    assert email in log_text
    assert f"/customer/invoices/{invoice_id}/pay" in log_text

    with SessionLocal() as db:
        inv = db.get(Invoice, invoice_id)
        assert inv is not None
        assert inv.payment_reminder_sent_at is not None


def test_reminder_script_skips_paid_invoice(
    client: TestClient, matt_credentials: dict[str, str],
):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    today = date(2026, 6, 25)

    with SessionLocal() as db:
        _seed_unpaid_invoice(
            db,
            client_email="paidremind@client.com",
            due_date=today.isoformat(),
            payment_status="paid",
        )

    EMAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_LOG.write_text("")

    with SessionLocal() as db:
        sent = send_payment_reminders(db, today=today)
    assert sent == 0
    assert "REMINDER" not in EMAIL_LOG.read_text()


def test_reminder_script_skips_already_reminded_today(
    client: TestClient, matt_credentials: dict[str, str],
):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    today = date(2026, 6, 25)
    reminded_at = datetime(today.year, today.month, today.day, 10, 0, tzinfo=UTC)

    with SessionLocal() as db:
        _seed_unpaid_invoice(
            db,
            client_email="dupremind@client.com",
            due_date=today.isoformat(),
            reminder_sent_at=reminded_at,
        )

    EMAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_LOG.write_text("")

    with SessionLocal() as db:
        sent = send_payment_reminders(db, today=today)
    assert sent == 0
    assert EMAIL_LOG.read_text() == ""
