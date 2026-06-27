"""E2E tests for customer payment methods and invoice payments."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Invoice, Job, Payment, PaymentMethod, User
from tests.conftest import login, signup_and_sync, start_and_complete_job

TEST_VISA = "4111111111111111"
TEST_DECLINE = "4000000000000002"


def _signup_customer(client: TestClient, email: str, password: str, name: str) -> None:
    r = client.post(
        "/customer/signup",
        data={"name": name, "email": email, "password": password},
        follow_redirects=False,
    )
    assert r.status_code == 302


def _book_and_complete(
    client: TestClient,
    matt_credentials: dict[str, str],
    customer_email: str,
    title: str = "Payment test shoot",
) -> int:
    client.post(
        "/customer/book",
        data={"title": title, "shoot_date": "2026-11-15"},
        follow_redirects=False,
    )
    with SessionLocal() as db:
        job = db.scalar(
            select(Job).where(Job.title == title, Job.client_email == customer_email)
        )
        assert job is not None
        job_id = job.id

    client.post("/customer/logout", follow_redirects=False)
    login(client, matt_credentials["email"], matt_credentials["password"])
    start_and_complete_job(client, job_id)
    client.post("/logout", follow_redirects=False)
    return job_id


def test_add_payment_method_stores_token_not_full_number(client: TestClient):
    email = "cards@client.com"
    _signup_customer(client, email, "cardpass", "Card Client")

    r = client.post(
        "/customer/payment-methods",
        data={
            "card_number": "4111 1111 1111 1111",
            "exp_month": "12",
            "exp_year": "2030",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/customer/payment-methods"

    page = client.get("/customer/payment-methods")
    assert page.status_code == 200
    assert "···· 1111" in page.text or "1111" in page.text
    assert "4111 1111 1111 1111" not in page.text

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        pm = db.scalar(select(PaymentMethod).where(PaymentMethod.user_id == user.id))
        assert pm is not None
        assert pm.last4 == "1111"
        assert pm.brand == "visa"
        assert pm.token.startswith("tok_")
        assert pm.is_default is True
        assert not hasattr(pm, "cvc") and not hasattr(pm, "cvv")


def test_invoice_unpaid_after_job_complete(
    client: TestClient, matt_credentials: dict[str, str],
):
    """Sending an invoice does not mark it paid until the client pays."""
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    email = "unpaid@client.com"
    _signup_customer(client, email, "unpaidpass", "Unpaid Client")
    _book_and_complete(client, matt_credentials, email, title="Unpaid invoice shoot")

    with SessionLocal() as db:
        invoice = db.scalar(
            select(Invoice).join(Job).where(Job.client_email == email)
        )
        assert invoice is not None
        assert invoice.payment_status == "unpaid"
        assert invoice.paid_at is None
        invoice_id = invoice.id

    client.post(
        "/customer/login",
        data={"email": email, "password": "unpaidpass"},
        follow_redirects=False,
    )
    dash = client.get("/customer/dashboard")
    assert "Awaiting payment" in dash.text
    assert "Unpaid" in dash.text

    pay_page = client.get(f"/customer/invoices/{invoice_id}/pay")
    assert pay_page.status_code == 200
    assert "Powered by" in pay_page.text
    assert "stripe" in pay_page.text.lower()
    assert "Test mode" in pay_page.text
    assert f"Pay ${invoice.total_cents / 100:,.2f}" in pay_page.text or "Pay $" in pay_page.text


def test_pay_invoice_with_saved_card(client: TestClient, matt_credentials: dict[str, str]):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    email = "payer@client.com"
    _signup_customer(client, email, "paypass", "Pay Client")
    _book_and_complete(client, matt_credentials, email)

    client.post(
        "/customer/login",
        data={"email": email, "password": "paypass"},
        follow_redirects=False,
    )
    client.post(
        "/customer/payment-methods",
        data={
            "card_number": TEST_VISA,
            "exp_month": "6",
            "exp_year": "2028",
        },
        follow_redirects=False,
    )

    with SessionLocal() as db:
        invoice = db.scalar(
            select(Invoice).join(Job).where(Job.client_email == email)
        )
        assert invoice is not None
        pm = db.scalar(
            select(PaymentMethod).join(User).where(User.email == email)
        )
        assert pm is not None
        invoice_id = invoice.id
        pm_id = pm.id

    pay = client.post(
        f"/customer/invoices/{invoice_id}/pay",
        data={"payment_method_id": str(pm_id), "cvc": "456"},
        follow_redirects=False,
    )
    assert pay.status_code == 302
    assert pay.headers["location"] == "/customer/dashboard?paid=1"

    dash = client.get("/customer/dashboard")
    assert "Paid" in dash.text
    assert "Pay now" not in dash.text

    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        assert invoice is not None
        assert invoice.payment_status == "paid"
        assert invoice.paid_at is not None
        payment = db.scalar(select(Payment).where(Payment.invoice_id == invoice_id))
        assert payment is not None
        assert payment.status == "paid"
        assert payment.amount_cents == invoice.total_cents


def test_pay_saved_card_requires_cvc_each_time(
    client: TestClient, matt_credentials: dict[str, str],
):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    email = "cvc-required@client.com"
    _signup_customer(client, email, "cvcpass", "CVC Client")
    _book_and_complete(client, matt_credentials, email, title="CVC required shoot")

    client.post(
        "/customer/login",
        data={"email": email, "password": "cvcpass"},
        follow_redirects=False,
    )
    client.post(
        "/customer/payment-methods",
        data={"card_number": TEST_VISA, "exp_month": "9", "exp_year": "2028"},
        follow_redirects=False,
    )

    with SessionLocal() as db:
        invoice = db.scalar(
            select(Invoice).join(Job).where(Job.client_email == email)
        )
        pm = db.scalar(select(PaymentMethod).join(User).where(User.email == email))
        assert invoice is not None and pm is not None
        invoice_id = invoice.id
        pm_id = pm.id

    denied = client.post(
        f"/customer/invoices/{invoice_id}/pay",
        data={"payment_method_id": str(pm_id)},
        follow_redirects=False,
    )
    assert denied.status_code == 400
    assert "security code" in denied.text.lower()

    pay_page = client.get(f"/customer/invoices/{invoice_id}/pay")
    assert "CVV is never stored" in pay_page.text


def test_payment_methods_page_does_not_collect_cvc(client: TestClient):
    _signup_customer(client, "nocvc@client.com", "nocvcpass", "No CVC")
    page = client.get("/customer/payment-methods")
    assert page.status_code == 200
    assert "CVV is never stored" in page.text
    assert 'name="cvc"' not in page.text


def test_pay_invoice_one_time_card(client: TestClient, matt_credentials: dict[str, str]):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    email = "onetime@client.com"
    _signup_customer(client, email, "otpass", "One Time")
    _book_and_complete(client, matt_credentials, email, title="One-time pay shoot")

    client.post(
        "/customer/login",
        data={"email": email, "password": "otpass"},
        follow_redirects=False,
    )

    with SessionLocal() as db:
        invoice = db.scalar(
            select(Invoice).join(Job).where(Job.client_email == email)
        )
        assert invoice is not None
        invoice_id = invoice.id

    pay = client.post(
        f"/customer/invoices/{invoice_id}/pay",
        data={
            "card_number": "5555 5555 5555 4444",
            "exp_month": "3",
            "exp_year": "2029",
            "cvc": "999",
        },
        follow_redirects=False,
    )
    assert pay.status_code == 302

    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        assert invoice is not None
        assert invoice.payment_status == "paid"
        methods = db.scalars(
            select(PaymentMethod).join(User).where(User.email == email)
        ).all()
        assert len(methods) == 0


def test_cannot_pay_other_customers_invoice(
    client: TestClient, matt_credentials: dict[str, str],
):
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
    _signup_customer(client, "thief@client.com", "thiefpass", "Thief")

    denied = client.post(
        f"/customer/invoices/{other_invoice_id}/pay",
        data={"card_number": TEST_VISA, "exp_month": "1", "exp_year": "2030", "cvc": "111"},
        follow_redirects=False,
    )
    assert denied.status_code == 404


def test_cannot_pay_already_paid_invoice(
    client: TestClient, matt_credentials: dict[str, str],
):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    email = "double@client.com"
    _signup_customer(client, email, "dblpass", "Double Pay")
    _book_and_complete(client, matt_credentials, email, title="Double pay shoot")

    client.post(
        "/customer/login",
        data={"email": email, "password": "dblpass"},
        follow_redirects=False,
    )

    with SessionLocal() as db:
        invoice = db.scalar(
            select(Invoice).join(Job).where(Job.client_email == email)
        )
        assert invoice is not None
        invoice_id = invoice.id

    first = client.post(
        f"/customer/invoices/{invoice_id}/pay",
        data={"card_number": TEST_VISA, "exp_month": "7", "exp_year": "2031", "cvc": "222"},
        follow_redirects=False,
    )
    assert first.status_code == 302

    second = client.post(
        f"/customer/invoices/{invoice_id}/pay",
        data={"card_number": TEST_VISA, "exp_month": "7", "exp_year": "2031", "cvc": "222"},
        follow_redirects=False,
    )
    assert second.status_code == 400
    assert "already paid" in second.text.lower()


def test_declined_card_shows_error(client: TestClient, matt_credentials: dict[str, str]):
    signup_and_sync(client, matt_credentials["email"], matt_credentials["password"])
    client.post("/logout", follow_redirects=False)

    email = "decline@client.com"
    _signup_customer(client, email, "decpass", "Decline Client")
    _book_and_complete(client, matt_credentials, email, title="Decline shoot")

    client.post(
        "/customer/login",
        data={"email": email, "password": "decpass"},
        follow_redirects=False,
    )

    with SessionLocal() as db:
        invoice = db.scalar(
            select(Invoice).join(Job).where(Job.client_email == email)
        )
        assert invoice is not None
        invoice_id = invoice.id

    pay = client.post(
        f"/customer/invoices/{invoice_id}/pay",
        data={
            "card_number": TEST_DECLINE,
            "exp_month": "8",
            "exp_year": "2030",
            "cvc": "123",
        },
        follow_redirects=False,
    )
    assert pay.status_code == 400
    assert "declined" in pay.text.lower()

    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        assert invoice is not None
        assert invoice.payment_status == "unpaid"
        failed = db.scalar(
            select(Payment).where(
                Payment.invoice_id == invoice_id, Payment.status == "failed"
            )
        )
        assert failed is not None


def test_payment_methods_requires_login(client: TestClient):
    r = client.get("/customer/payment-methods", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/customer/login"
