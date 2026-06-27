"""Email delivery status and customer email settings tests."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Invoice, Job, User
from app.repositories.users import create_user
from app.services.customer_workflow import update_customer_email
from app.services.email_service import EmailSendError, is_valid_email, send_invoice_email
from tests.conftest import login, signup_and_sync, start_and_complete_job


def _sample_job(**kwargs) -> Job:
    defaults = dict(
        id=1,
        user_id=1,
        external_id="test-1",
        client_name="Riverdale Weddings",
        client_email="billing@riverdaleweddings.com",
        title="Spring garden ceremony",
        shoot_date="2026-05-15",
        amount_cents=250000,
        tax_rate=0.08,
        email_subject="Invoice — Spring garden ceremony",
        email_body="Thank you for booking Matt Photography.",
        status="done",
    )
    defaults.update(kwargs)
    return Job(**defaults)


def _sample_invoice(**kwargs) -> Invoice:
    defaults = dict(
        id=42,
        job_id=1,
        subtotal_cents=250000,
        tax_cents=20000,
        total_cents=270000,
        client_email="billing@riverdaleweddings.com",
        email_status="pending",
    )
    defaults.update(kwargs)
    return Invoice(**defaults)


def test_is_valid_email_rejects_invalid_prefix():
    assert is_valid_email("billing@example.com") is True
    assert is_valid_email("invalid@") is False
    assert is_valid_email("not-an-email") is False


def test_mock_send_records_delivered_status(tmp_path: Path):
    pdf_path = tmp_path / "invoice-42.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    job = _sample_job()
    invoice = _sample_invoice()

    db = MagicMock()
    send_invoice_email(db, job, invoice, pdf_path)

    assert invoice.email_status == "delivered"
    assert invoice.recipient_email == "billing@riverdaleweddings.com"
    assert invoice.email_sent_at is not None
    assert invoice.email_error is None
    db.commit.assert_called()


def test_invalid_recipient_records_failed(tmp_path: Path):
    pdf_path = tmp_path / "invoice-42.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    job = _sample_job(client_email="invalid@")
    invoice = _sample_invoice(client_email="invalid@")

    db = MagicMock()
    with pytest.raises(EmailSendError, match="Invalid recipient"):
        send_invoice_email(db, job, invoice, pdf_path)

    assert invoice.email_status == "failed"
    assert invoice.email_error is not None


def test_mailjet_send_records_sent_status(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "email_mode", "mailjet")
    monkeypatch.setattr(settings, "mailjet_api_key", "test-key")
    monkeypatch.setattr(settings, "mailjet_api_secret", "test-secret")

    pdf_path = tmp_path / "invoice-42.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    job = _sample_job()
    invoice = _sample_invoice()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"Messages": [{"Status": "success"}]}

    db = MagicMock()
    with patch("app.services.email_service.httpx.post", return_value=mock_response):
        send_invoice_email(db, job, invoice, pdf_path)

    assert invoice.email_status == "sent"
    assert invoice.recipient_email == "billing@riverdaleweddings.com"


def test_complete_job_records_delivered(
    client: TestClient, matt_credentials: dict[str, str],
):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    customer_email = "delivered@client.com"
    client.post(
        "/customer/signup",
        data={"name": "Delivered Client", "email": customer_email, "password": "pass1234"},
        follow_redirects=False,
    )
    client.post(
        "/customer/book",
        data={"title": "Delivery test", "shoot_date": "2026-07-01"},
        follow_redirects=False,
    )

    with SessionLocal() as db:
        job = db.scalar(
            select(Job).where(Job.title == "Delivery test", Job.client_email == customer_email)
        )
        assert job is not None
        job_id = job.id

    client.post("/customer/logout", follow_redirects=False)
    login(client, matt_credentials["email"], matt_credentials["password"])
    start_and_complete_job(client, job_id)

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        assert invoice.email_status == "delivered"
        assert invoice.recipient_email == customer_email

    matt_dash = client.get("/dashboard")
    assert matt_dash.status_code == 200
    assert "delivered" in matt_dash.text.lower()


def test_failed_email_shows_on_dashboards(
    client: TestClient, matt_credentials: dict[str, str],
):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    with SessionLocal() as db:
        matt = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert matt is not None
        job = Job(
            user_id=matt.id,
            external_id="bad-email-job",
            client_name="Bad Email Co",
            client_email="invalid@",
            title="Bad email shoot",
            shoot_date="2026-06-01",
            amount_cents=10000,
            tax_rate=0.08,
            email_subject="Invoice",
            email_body="Body",
            status="started",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    client.post(f"/jobs/{job_id}/complete", follow_redirects=False)

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        assert invoice.email_status == "failed"

    matt_dash = client.get("/dashboard")
    assert "Failed" in matt_dash.text


def test_customer_can_update_email(client: TestClient, matt_credentials: dict[str, str]):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    old_email = "old@client.com"
    client.post(
        "/customer/signup",
        data={"name": "Updater", "email": old_email, "password": "pass1234"},
        follow_redirects=False,
    )
    client.post(
        "/customer/book",
        data={"title": "Email sync shoot", "shoot_date": "2026-08-15"},
        follow_redirects=False,
    )

    settings_page = client.get("/customer/settings")
    assert settings_page.status_code == 200
    assert "Settings" in settings_page.text
    assert old_email in settings_page.text

    new_email = "new@client.com"
    r = client.post(
        "/customer/settings",
        data={"email": new_email},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/customer/settings?updated=1"

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == new_email))
        assert user is not None
        job = db.scalar(
            select(Job).where(Job.title == "Email sync shoot", Job.client_email == new_email)
        )
        assert job is not None


def test_customer_email_update_rejects_duplicate(
    client: TestClient, matt_credentials: dict[str, str],
):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    client.post(
        "/customer/signup",
        data={"name": "First", "email": "first@client.com", "password": "pass1234"},
        follow_redirects=False,
    )
    client.post("/customer/logout", follow_redirects=False)
    client.post(
        "/customer/signup",
        data={"name": "Second", "email": "second@client.com", "password": "pass1234"},
        follow_redirects=False,
    )

    r = client.post(
        "/customer/settings",
        data={"email": "first@client.com"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "already registered" in r.text.lower()


def test_update_customer_email_syncs_jobs():
    with SessionLocal() as db:
        customer = create_user(db, "sync@client.com", "pass1234", role="customer", name="Sync")
        photographer = create_user(db, "photo@test.com", "pass1234", role="photographer")
        job = Job(
            user_id=photographer.id,
            external_id="sync-job",
            client_name="Sync",
            client_email="sync@client.com",
            title="Sync job",
            shoot_date="2026-09-01",
            amount_cents=50000,
            tax_rate=0.08,
            email_subject="Invoice",
            email_body="Body",
            status="pending",
        )
        db.add(job)
        db.commit()

        err = update_customer_email(db, customer, "updated@client.com")
        assert err is None

        db.refresh(job)
        assert job.client_email == "updated@client.com"
        assert customer.email == "updated@client.com"
