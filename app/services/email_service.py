"""Invoice email delivery — Mailjet API or mock log."""

import base64
import logging
import re
from datetime import UTC, datetime
from html import escape
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.letterhead import letterhead_text_block, wrap_email_html
from app.models import Invoice, Job
from app.repositories.invoices import record_invoice_email_delivery

logger = logging.getLogger(__name__)
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
EMAIL_LOG = LOG_DIR / "email_mock.log"
MAILJET_SEND_URL = "https://api.mailjet.com/v3.1/send"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailSendError(Exception):
    """Raised when Mailjet rejects or fails a send request."""


def is_valid_email(email: str) -> bool:
    """Basic format check; mock mode also rejects addresses starting with invalid@."""
    normalized = email.strip().lower()
    if normalized.startswith("invalid@"):
        return False
    return bool(EMAIL_RE.match(normalized))


def _fmt_cents(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _use_mailjet() -> bool:
    if settings.email_mode == "mock":
        return False
    return bool(settings.mailjet_api_key and settings.mailjet_api_secret)


def _build_html_body(job: Job, invoice: Invoice) -> str:
    title = escape(job.title)
    body = escape(job.email_body)
    inner = (
        f"<h2 style='margin:0 0 12px;color:#1e293b;'>Invoice for {title}</h2>"
        f"<p style='margin:0 0 16px;color:#475569;'>{body}</p>"
        "<table style='width:100%;border-collapse:collapse;font-size:14px;'>"
        "<tr style='background:#f1f5f9;'>"
        "<th style='padding:8px;text-align:left;border:1px solid #e2e8f0;'>Item</th>"
        "<th style='padding:8px;text-align:right;border:1px solid #e2e8f0;'>Amount</th>"
        "</tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0;'>Subtotal</td>"
        f"<td style='padding:8px;text-align:right;border:1px solid #e2e8f0;'>"
        f"{_fmt_cents(invoice.subtotal_cents)}</td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0;'>Tax</td>"
        f"<td style='padding:8px;text-align:right;border:1px solid #e2e8f0;'>"
        f"{_fmt_cents(invoice.tax_cents)}</td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0;font-weight:700;'>Total</td>"
        f"<td style='padding:8px;text-align:right;border:1px solid #e2e8f0;font-weight:700;'>"
        f"{_fmt_cents(invoice.total_cents)}</td></tr>"
        "</table>"
        "<p style='margin:16px 0 0;color:#64748b;font-size:13px;'>"
        "Your detailed invoice PDF is attached.</p>"
    )
    return wrap_email_html(inner)


def _build_text_body(job: Job, invoice: Invoice) -> str:
    header = letterhead_text_block()
    return (
        f"{header}\n"
        f"{'=' * 40}\n\n"
        f"INVOICE — {job.title}\n\n"
        f"{job.email_body}\n\n"
        f"Subtotal: {_fmt_cents(invoice.subtotal_cents)}\n"
        f"Tax: {_fmt_cents(invoice.tax_cents)}\n"
        f"Total: {_fmt_cents(invoice.total_cents)}\n\n"
        "Your detailed invoice PDF is attached."
    )


def _send_mock(job: Job, invoice: Invoice, pdf_path: Path) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = (
        f"{datetime.now(UTC).isoformat()} | TO={invoice.client_email} | "
        f"SUBJECT={job.email_subject} | subtotal={invoice.subtotal_cents} | "
        f"tax={invoice.tax_cents} | total={invoice.total_cents} | job={job.external_id} | "
        f"pdf={pdf_path}\n"
        f"BODY: {job.email_body}\n"
    )
    with EMAIL_LOG.open("a") as f:
        f.write(line)
    logger.info("Mock email logged for job %s to %s", job.external_id, invoice.client_email)


def _send_mailjet(job: Job, invoice: Invoice, pdf_path: Path) -> None:
    pdf_bytes = pdf_path.read_bytes()
    payload = {
        "Messages": [
            {
                "From": {
                    "Email": settings.mailjet_from_email,
                    "Name": settings.mailjet_from_name,
                },
                "To": [
                    {
                        "Email": invoice.client_email,
                        "Name": job.client_name,
                    }
                ],
                "Subject": job.email_subject,
                "TextPart": _build_text_body(job, invoice),
                "HTMLPart": _build_html_body(job, invoice),
                "Attachments": [
                    {
                        "ContentType": "application/pdf",
                        "Filename": f"invoice-{invoice.id}.pdf",
                        "Base64Content": base64.b64encode(pdf_bytes).decode("ascii"),
                    }
                ],
            }
        ]
    }

    try:
        response = httpx.post(
            MAILJET_SEND_URL,
            auth=(settings.mailjet_api_key, settings.mailjet_api_secret),
            json=payload,
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise EmailSendError(f"Mailjet request failed: {exc}") from exc

    if response.status_code >= 400:
        raise EmailSendError(f"Mailjet HTTP {response.status_code}: {response.text}")

    data = response.json()
    messages = data.get("Messages", [])
    if not messages or messages[0].get("Status") != "success":
        raise EmailSendError(f"Mailjet send failed: {response.text}")

    logger.info(
        "Mailjet email sent for job %s to %s (invoice %s)",
        job.external_id,
        invoice.client_email,
        invoice.id,
    )


def send_invoice_email(
    db: Session, job: Job, invoice: Invoice, pdf_path: Path,
) -> None:
    if not pdf_path.is_file():
        raise EmailSendError(f"Invoice PDF missing: {pdf_path}")

    recipient = invoice.client_email.strip().lower()
    if not is_valid_email(recipient):
        error = f"Invalid recipient email: {recipient}"
        record_invoice_email_delivery(
            db, invoice, status="failed", recipient_email=recipient, error=error,
        )
        raise EmailSendError(error)

    try:
        if _use_mailjet():
            _send_mailjet(job, invoice, pdf_path)
            record_invoice_email_delivery(
                db, invoice, status="sent", recipient_email=recipient,
            )
        else:
            _send_mock(job, invoice, pdf_path)
            record_invoice_email_delivery(
                db, invoice, status="delivered", recipient_email=recipient,
            )
    except EmailSendError as exc:
        record_invoice_email_delivery(
            db, invoice, status="failed", recipient_email=recipient, error=str(exc),
        )
        raise


def _payment_reminder_pay_url(invoice: Invoice) -> str:
    base = settings.app_base_url.rstrip("/")
    return f"{base}/customer/invoices/{invoice.id}/pay"


def _build_reminder_html(job: Job, invoice: Invoice, pay_url: str) -> str:
    title = escape(job.title)
    due = escape(invoice.payment_due_date or "")
    inner = (
        f"<h2 style='margin:0 0 12px;color:#1e293b;'>Payment reminder — {title}</h2>"
        f"<p style='margin:0 0 16px;color:#475569;'>"
        f"Your invoice #{invoice.id} for {_fmt_cents(invoice.total_cents)} "
        f"was due by {due}. Please pay at your earliest convenience.</p>"
        f"<p style='margin:0 0 16px;'>"
        f"<a href='{escape(pay_url)}' style='color:#635bff;font-weight:600;'>"
        f"Pay invoice online</a></p>"
    )
    return wrap_email_html(inner)


def _build_reminder_text(job: Job, invoice: Invoice, pay_url: str) -> str:
    header = letterhead_text_block()
    due = invoice.payment_due_date or ""
    return (
        f"{header}\n"
        f"{'=' * 40}\n\n"
        f"PAYMENT REMINDER — {job.title}\n\n"
        f"Invoice #{invoice.id}\n"
        f"Amount due: {_fmt_cents(invoice.total_cents)}\n"
        f"Due by: {due}\n\n"
        f"Pay online: {pay_url}\n"
    )


def _send_reminder_mock(job: Job, invoice: Invoice, pay_url: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = (
        f"{datetime.now(UTC).isoformat()} | REMINDER | TO={invoice.client_email} | "
        f"SUBJECT=Payment reminder — Invoice #{invoice.id} | "
        f"total={invoice.total_cents} | due={invoice.payment_due_date} | "
        f"pay_url={pay_url} | job={job.external_id}\n"
    )
    with EMAIL_LOG.open("a") as f:
        f.write(line)
    logger.info(
        "Mock payment reminder logged for invoice %s to %s",
        invoice.id,
        invoice.client_email,
    )


def _send_reminder_mailjet(job: Job, invoice: Invoice, pay_url: str) -> None:
    subject = f"Payment reminder — Invoice #{invoice.id}"
    payload = {
        "Messages": [
            {
                "From": {
                    "Email": settings.mailjet_from_email,
                    "Name": settings.mailjet_from_name,
                },
                "To": [
                    {
                        "Email": invoice.client_email,
                        "Name": job.client_name,
                    }
                ],
                "Subject": subject,
                "TextPart": _build_reminder_text(job, invoice, pay_url),
                "HTMLPart": _build_reminder_html(job, invoice, pay_url),
            }
        ]
    }

    try:
        response = httpx.post(
            MAILJET_SEND_URL,
            auth=(settings.mailjet_api_key, settings.mailjet_api_secret),
            json=payload,
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise EmailSendError(f"Mailjet request failed: {exc}") from exc

    if response.status_code >= 400:
        raise EmailSendError(f"Mailjet HTTP {response.status_code}: {response.text}")

    data = response.json()
    messages = data.get("Messages", [])
    if not messages or messages[0].get("Status") != "success":
        raise EmailSendError(f"Mailjet send failed: {response.text}")

    logger.info(
        "Mailjet payment reminder sent for invoice %s to %s",
        invoice.id,
        invoice.client_email,
    )


def send_payment_reminder_email(
    db: Session, job: Job, invoice: Invoice,
) -> None:
    recipient = invoice.client_email.strip().lower()
    if not is_valid_email(recipient):
        raise EmailSendError(f"Invalid recipient email: {recipient}")

    pay_url = _payment_reminder_pay_url(invoice)
    if _use_mailjet():
        _send_reminder_mailjet(job, invoice, pay_url)
    else:
        _send_reminder_mock(job, invoice, pay_url)
