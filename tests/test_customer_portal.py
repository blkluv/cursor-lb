"""E2E tests for the customer portal."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Invoice, Job, User
from app.repositories.users import create_user, get_photographer_user
from app.services.invoice_pdf import invoice_pdf_path
from tests.conftest import login, signup_and_sync, start_and_complete_job


def _signup_customer(client: TestClient, email: str, password: str, name: str) -> None:
    r = client.post(
        "/customer/signup",
        data={"name": name, "email": email, "password": password},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/customer/dashboard"


def test_customer_signup_and_dashboard(client: TestClient):
    """Customer signs up and lands on their shoots dashboard."""
    email = "client@example.com"
    _signup_customer(client, email, "clientpass", "Jane Client")

    dash = client.get("/customer/dashboard")
    assert dash.status_code == 200
    assert "My shoots" in dash.text
    assert "Jane Client" in dash.text
    assert email in dash.text

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        assert user.role == "customer"
        assert user.name == "Jane Client"


def test_customer_book_shoot_visible_to_photographer(
    client: TestClient, matt_credentials: dict[str, str], monkeypatch: pytest.MonkeyPatch,
):
    """Customer books a shoot; only their job appears on customer dashboard; Matt sees it too."""
    monkeypatch.setattr(settings, "photographer_email", matt_credentials["email"])
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    customer_email = "booker@weddings.com"
    _signup_customer(client, customer_email, "bookpass", "River Booker")

    r = client.post(
        "/customer/book",
        data={"title": "Engagement photos", "shoot_date": "2026-08-01"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/customer/dashboard"

    dash = client.get("/customer/dashboard")
    assert "Engagement photos" in dash.text
    assert "Booked" in dash.text
    # Mock jobs from other clients should not appear
    assert "Spring garden ceremony" not in dash.text

    client.post("/customer/logout", follow_redirects=False)
    login(client, matt_credentials["email"], matt_credentials["password"])

    matt_dash = client.get("/dashboard")
    assert "Engagement photos" in matt_dash.text
    assert "River Booker" in matt_dash.text


def test_customer_book_assigns_to_configured_studio_photographer(
    client: TestClient, matt_credentials: dict[str, str], monkeypatch: pytest.MonkeyPatch,
):
    """With multiple photographer accounts, bookings go to PHOTOGRAPHER_EMAIL, not the oldest id."""
    with SessionLocal() as db:
        stale = create_user(db, "legacy-studio@test.com", "legacy123", name="Legacy Studio")
        stale_id = stale.id

    monkeypatch.setattr(settings, "photographer_email", matt_credentials["email"])
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    with SessionLocal() as db:
        matt = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert matt is not None
        assert matt.id != stale_id
        assert get_photographer_user(db) == matt

    _signup_customer(client, "multi@client.com", "multipass", "Multi Client")
    client.post(
        "/customer/book",
        data={"title": "Anniversary shoot", "shoot_date": "2026-11-20"},
        follow_redirects=False,
    )

    with SessionLocal() as db:
        job = db.scalar(
            select(Job).where(
                Job.title == "Anniversary shoot",
                Job.client_email == "multi@client.com",
            )
        )
        matt = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert job is not None
        assert matt is not None
        assert job.user_id == matt.id
        assert job.user_id != stale_id

    client.post("/customer/logout", follow_redirects=False)
    login(client, matt_credentials["email"], matt_credentials["password"])
    matt_dash = client.get("/dashboard")
    assert "Anniversary shoot" in matt_dash.text
    assert "Multi Client" in matt_dash.text


def test_customer_sees_status_updates(client: TestClient, matt_credentials: dict[str, str]):
    """Customer sees in-progress and completed status after Matt updates the job."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    customer_email = "status@client.com"
    _signup_customer(client, customer_email, "statuspass", "Status Client")
    client.post(
        "/customer/book",
        data={"title": "Headshot session", "shoot_date": "2026-09-10"},
        follow_redirects=False,
    )

    with SessionLocal() as db:
        job = db.scalar(
            select(Job).where(Job.title == "Headshot session", Job.client_email == customer_email)
        )
        assert job is not None
        job_id = job.id

    client.post("/customer/logout", follow_redirects=False)
    login(client, matt_credentials["email"], matt_credentials["password"])
    start_and_complete_job(client, job_id)
    client.post("/logout", follow_redirects=False)

    client.post(
        "/customer/login",
        data={"email": customer_email, "password": "statuspass"},
        follow_redirects=False,
    )
    dash = client.get("/customer/dashboard")
    assert "Headshot session" in dash.text
    assert "Completed" in dash.text
    assert "invoice sent" in dash.text.lower()
    assert "Awaiting payment" in dash.text
    assert "Unpaid" in dash.text
    assert "Your invoices" in dash.text or "All your invoices" in dash.text
    assert "Download PDF" in dash.text

    with SessionLocal() as db:
        job = db.scalar(
            select(Job).where(Job.title == "Headshot session", Job.client_email == customer_email)
        )
        assert job is not None
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job.id))
        assert invoice is not None
        assert invoice.payment_status == "unpaid"
        assert invoice.paid_at is None
        invoice_id = invoice.id

    pdf = client.get(f"/customer/invoices/{invoice_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"


def test_role_separation_login(client: TestClient, matt_credentials: dict[str, str]):
    """Photographer cannot use customer login; customer cannot use photographer login."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    _signup_customer(client, "roles@test.com", "rolepass", "Role Tester")
    client.post("/customer/logout", follow_redirects=False)

    bad_photog = client.post(
        "/login",
        data={"email": "roles@test.com", "password": "rolepass"},
        follow_redirects=False,
    )
    assert bad_photog.status_code == 400
    assert "client portal" in bad_photog.text.lower()

    bad_customer = client.post(
        "/customer/login",
        data={"email": matt_credentials["email"], "password": matt_credentials["password"]},
        follow_redirects=False,
    )
    assert bad_customer.status_code == 400
    assert "photographer" in bad_customer.text.lower()


def test_customer_cannot_download_other_invoice(
    client: TestClient, matt_credentials: dict[str, str],
):
    """Customer cannot download invoices belonging to another client's email."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.external_id == "trello-card-101"))
        assert job is not None
        job_id = job.id

    start_and_complete_job(client, job_id)

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        other_invoice_id = invoice.id

    client.post("/logout", follow_redirects=False)
    _signup_customer(client, "isolated@client.com", "isopass", "Isolated Client")

    denied = client.get(f"/customer/invoices/{other_invoice_id}/pdf")
    assert denied.status_code == 404


def test_customer_pdf_download_regenerates_if_missing(
    client: TestClient, matt_credentials: dict[str, str],
):
    """Customer can download PDF even when the file was never written to disk."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    customer_email = "pdf@client.com"
    _signup_customer(client, customer_email, "pdfpass", "PDF Client")
    client.post(
        "/customer/book",
        data={"title": "PDF test shoot", "shoot_date": "2026-10-01"},
        follow_redirects=False,
    )

    with SessionLocal() as db:
        job = db.scalar(
            select(Job).where(Job.title == "PDF test shoot", Job.client_email == customer_email)
        )
        assert job is not None
        job_id = job.id

    client.post("/customer/logout", follow_redirects=False)
    login(client, matt_credentials["email"], matt_credentials["password"])
    start_and_complete_job(client, job_id)

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        pdf_path = invoice_pdf_path(invoice.id)
        if pdf_path.is_file():
            pdf_path.unlink()

    client.post("/logout", follow_redirects=False)
    client.post(
        "/customer/login",
        data={"email": customer_email, "password": "pdfpass"},
        follow_redirects=False,
    )

    pdf = client.get(f"/customer/invoices/{invoice.id}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf_path.is_file()
    assert pdf_path.stat().st_size > 0
