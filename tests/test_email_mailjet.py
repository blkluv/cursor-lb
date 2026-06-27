"""Mailjet email sender tests."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import settings
from app.models import Invoice, Job
from app.services.email_service import send_invoice_email


def _sample_job() -> Job:
    job = Job(
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
    return job


def _sample_invoice() -> Invoice:
    invoice = Invoice(
        id=42,
        job_id=1,
        subtotal_cents=250000,
        tax_cents=20000,
        total_cents=270000,
        client_email="billing@riverdaleweddings.com",
    )
    return invoice


def test_mailjet_send_posts_to_api(tmp_path: Path, monkeypatch):
    """When EMAIL_MODE=mailjet, invoice email is sent via Mailjet with PDF attachment."""
    monkeypatch.setattr(settings, "email_mode", "mailjet")
    monkeypatch.setattr(settings, "mailjet_api_key", "test-key")
    monkeypatch.setattr(settings, "mailjet_api_secret", "test-secret")
    monkeypatch.setattr(settings, "mailjet_from_email", "alizubair6475@gmail.com")
    monkeypatch.setattr(settings, "mailjet_from_name", "Matt Photography")

    pdf_path = tmp_path / "invoice-42.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"Messages": [{"Status": "success"}]}

    with patch("app.services.email_service.httpx.post", return_value=mock_response) as mock_post:
        db = MagicMock()
        send_invoice_email(db, _sample_job(), _sample_invoice(), pdf_path)

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs.kwargs["auth"] == ("test-key", "test-secret")
    payload = call_kwargs.kwargs["json"]
    message = payload["Messages"][0]
    assert message["To"][0]["Email"] == "billing@riverdaleweddings.com"
    assert message["Subject"] == "Invoice — Spring garden ceremony"
    assert message["Attachments"][0]["Filename"] == "invoice-42.pdf"
    assert message["Attachments"][0]["ContentType"] == "application/pdf"
