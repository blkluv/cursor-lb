"""E2E tests mapped to specs/feature_list.json."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Invoice, Job, User
from app.services.invoice_pdf import invoice_pdf_path
from tests.conftest import login, signup_and_sync, start_and_complete_job

EMAIL_LOG = Path(__file__).resolve().parent.parent / "logs" / "email_mock.log"


def test_auth_001_signup_lands_on_dashboard(client: TestClient, matt_credentials: dict[str, str]):
    """auth-001: new user signs up and lands on dashboard with welcome state."""
    email = matt_credentials["email"]
    password = matt_credentials["password"]

    signup_page = client.get("/signup")
    assert signup_page.status_code == 200

    r = client.post(
        "/signup",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/dashboard"

    dash = client.get("/dashboard")
    assert dash.status_code == 200
    assert "Welcome back" in dash.text
    assert email in dash.text
    assert "Your shoots" in dash.text

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None


def test_auth_002_login_and_session_persist(client: TestClient, matt_credentials: dict[str, str]):
    """auth-002: existing user logs in; session survives refresh."""
    email = matt_credentials["email"]
    password = matt_credentials["password"]
    signup_and_sync(client, email, password)
    client.post("/logout", follow_redirects=False)

    login_page = client.get("/login")
    assert login_page.status_code == 200

    login(client, email, password)

    first = client.get("/dashboard")
    second = client.get("/dashboard")
    assert first.status_code == 200
    assert second.status_code == 200
    assert email in second.text


def test_jobs_001_pending_jobs_from_mock_feed(client: TestClient, matt_credentials: dict[str, str]):
    """jobs-001: dashboard lists booked jobs with client, title, and amount."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    dash = client.get("/dashboard")
    assert dash.status_code == 200
    assert "Booked (" in dash.text
    assert "Riverdale Weddings" in dash.text
    assert "Spring garden ceremony" in dash.text
    assert "$2,500.00" in dash.text
    assert "Start shoot" in dash.text


def test_book_new_job(client: TestClient, matt_credentials: dict[str, str]):
    """Matt can book a new shoot from the UI."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    page = client.get("/jobs/book")
    assert page.status_code == 200

    r = client.post(
        "/jobs/book",
        data={
            "client_name": "Studio Client Co",
            "client_email": "billing@studioclient.com",
            "title": "Brand portrait session",
            "shoot_date": "2026-07-01",
            "amount_dollars": "1200",
            "tax_rate_percent": "8",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/dashboard"

    dash = client.get("/dashboard")
    assert "Brand portrait session" in dash.text
    assert "Studio Client Co" in dash.text
    assert "$1,200.00" in dash.text

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert user is not None
        job = db.scalar(
            select(Job).where(Job.user_id == user.id, Job.title == "Brand portrait session")
        )
        assert job is not None
        assert job.status == "pending"
        assert job.external_id.startswith("manual-")


def test_start_job_moves_to_in_progress(client: TestClient, matt_credentials: dict[str, str]):
    """Pending job moves to in progress when started."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert user is not None
        job = db.scalar(
            select(Job).where(Job.user_id == user.id, Job.status == "pending").limit(1)
        )
        assert job is not None
        job_id = job.id
        title = job.title

    r = client.post(f"/jobs/{job_id}/start", follow_redirects=False)
    assert r.status_code == 302

    dash = client.get("/dashboard")
    assert "In progress" in dash.text
    assert title in dash.text
    assert "Mark done" in dash.text

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        assert job.status == "started"
        assert job.started_at is not None


def test_jobs_002_mark_job_done(client: TestClient, matt_credentials: dict[str, str]):
    """jobs-002: start then mark done; status updates in DB and UI."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert user is not None
        job = db.scalar(
            select(Job).where(Job.user_id == user.id, Job.status == "pending").limit(1)
        )
        assert job is not None
        job_id = job.id
        title = job.title

    start_and_complete_job(client, job_id)

    dash = client.get("/dashboard")
    assert "Completed" in dash.text and "invoiced" in dash.text
    assert title in dash.text
    assert "Unpaid" in dash.text

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        assert job.status == "done"


def test_complete_without_start_fails(client: TestClient, matt_credentials: dict[str, str]):
    """Cannot complete a job that has not been started."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert user is not None
        job = db.scalar(
            select(Job).where(Job.user_id == user.id, Job.status == "pending").limit(1)
        )
        assert job is not None
        job_id = job.id

    client.post(f"/jobs/{job_id}/complete", follow_redirects=False)

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        assert job.status == "pending"


def test_invoice_001_mock_email_on_completion(client: TestClient, matt_credentials: dict[str, str]):
    """invoice-001: completing a job writes email log and invoice row."""
    EMAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_LOG.write_text("")

    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert user is not None
        job = db.scalar(
            select(Job).where(Job.user_id == user.id, Job.status == "pending").limit(1)
        )
        assert job is not None
        job_id = job.id
        client_email = job.client_email
        amount = job.amount_cents
        tax_rate = job.tax_rate

    start_and_complete_job(client, job_id)

    expected_tax = int(round(amount * tax_rate))
    expected_total = amount + expected_tax

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        assert invoice.client_email == client_email
        assert invoice.subtotal_cents == amount
        assert invoice.tax_cents == expected_tax
        assert invoice.total_cents == expected_total

    log_text = EMAIL_LOG.read_text()
    assert client_email in log_text
    assert f"subtotal={amount}" in log_text
    assert f"tax={expected_tax}" in log_text
    assert f"total={expected_total}" in log_text
    assert "pdf=" in log_text

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        pdf_path = invoice_pdf_path(invoice.id)
        assert pdf_path.is_file()
        assert pdf_path.stat().st_size > 0


def test_invoice_002_view_sent_invoice_on_dashboard(
    client: TestClient, matt_credentials: dict[str, str],
):
    """invoice-002: completed jobs show invoice details matching DB."""
    EMAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_LOG.write_text("")

    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert user is not None
        job = db.scalar(
            select(Job).where(Job.user_id == user.id, Job.status == "pending").limit(1)
        )
        assert job is not None
        job_id = job.id
        title = job.title

    start_and_complete_job(client, job_id)

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        subtotal = invoice.subtotal_cents
        tax = invoice.tax_cents
        total = invoice.total_cents
        sent_at = invoice.sent_at.strftime("%Y-%m-%d")

    dash = client.get("/dashboard")
    assert title in dash.text
    assert f"${subtotal / 100:,.2f}" in dash.text
    assert f"${tax / 100:,.2f}" in dash.text
    assert f"${total / 100:,.2f}" in dash.text
    assert sent_at in dash.text
    assert "Unpaid" in dash.text

    log_text = EMAIL_LOG.read_text()
    assert str(total) in log_text or f"total={total}" in log_text


def test_invoice_pdf_download(client: TestClient, matt_credentials: dict[str, str]):
    """Completed invoice PDF is generated and downloadable."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert user is not None
        job = db.scalar(
            select(Job).where(Job.user_id == user.id, Job.status == "pending").limit(1)
        )
        assert job is not None
        job_id = job.id

    start_and_complete_job(client, job_id)

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        invoice_id = invoice.id

    r = client.get(f"/invoices/{invoice_id}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"

    dash = client.get("/dashboard")
    assert f"/invoices/{invoice_id}/pdf" in dash.text
    assert "Download" in dash.text


def test_resend_invoice(client: TestClient, matt_credentials: dict[str, str]):
    """Matt can resend a completed invoice; mock log and email_status update."""
    EMAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_LOG.write_text("")

    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == matt_credentials["email"]))
        assert user is not None
        job = db.scalar(
            select(Job).where(Job.user_id == user.id, Job.status == "pending").limit(1)
        )
        assert job is not None
        job_id = job.id
        client_email = job.client_email

    start_and_complete_job(client, job_id)

    initial_log = EMAIL_LOG.read_text()
    assert initial_log.count(f"TO={client_email}") == 1

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        assert invoice.email_status == "delivered"
        first_email_sent_at = invoice.email_sent_at
        assert first_email_sent_at is not None

    dash = client.get("/dashboard")
    assert "Resend invoice" in dash.text

    r = client.post(f"/jobs/{job_id}/resend-invoice", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/dashboard"

    resend_log = EMAIL_LOG.read_text()
    assert resend_log.count(f"TO={client_email}") == 2
    assert len(resend_log) > len(initial_log)

    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.job_id == job_id))
        assert invoice is not None
        assert invoice.email_status == "delivered"
        assert invoice.recipient_email == client_email.strip().lower()
        assert invoice.email_sent_at is not None
        assert invoice.email_sent_at >= first_email_sent_at
