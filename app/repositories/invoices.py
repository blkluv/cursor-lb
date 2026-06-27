"""Invoice persistence."""

from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Invoice, Job
from app.services.payment_due import (
    reminder_sent_today,
    resolve_invoice_due_date,
)


def create_invoice_for_job(db: Session, job: Job) -> Invoice:
    subtotal = job.amount_cents
    tax_cents = int(round(subtotal * job.tax_rate))
    total = subtotal + tax_cents
    sent_at = datetime.now(UTC)
    invoice = Invoice(
        job_id=job.id,
        subtotal_cents=subtotal,
        tax_cents=tax_cents,
        total_cents=total,
        client_email=job.client_email,
        email_status="pending",
        recipient_email=job.client_email,
        sent_at=sent_at,
        payment_due_date=resolve_invoice_due_date(job.payment_due_date, sent_at),
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def get_invoice_for_user(db: Session, user_id: int, invoice_id: int) -> Invoice | None:
    return db.scalar(
        select(Invoice)
        .join(Job)
        .where(Invoice.id == invoice_id, Job.user_id == user_id)
        .options(joinedload(Invoice.job))
    )


def _client_email_filter(email_norm: str):
    return or_(
        func.lower(Job.client_email) == email_norm,
        func.lower(Invoice.client_email) == email_norm,
    )


def list_invoices_for_client_email(db: Session, client_email: str) -> list[Invoice]:
    email_norm = client_email.strip().lower()
    stmt = (
        select(Invoice)
        .join(Job)
        .where(_client_email_filter(email_norm))
        .options(joinedload(Invoice.job))
        .order_by(Invoice.sent_at.desc())
    )
    return list(db.scalars(stmt).all())


def get_invoice_for_client_email(
    db: Session, client_email: str, invoice_id: int,
) -> Invoice | None:
    invoice = db.scalar(
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .options(joinedload(Invoice.job))
    )
    if invoice is None or invoice.job is None:
        return None
    email_norm = client_email.strip().lower()
    job_email = invoice.job.client_email.strip().lower()
    inv_email = invoice.client_email.strip().lower()
    if email_norm not in (job_email, inv_email):
        return None
    return invoice


def record_invoice_email_delivery(
    db: Session,
    invoice: Invoice,
    *,
    status: str,
    recipient_email: str,
    error: str | None = None,
) -> Invoice:
    invoice.email_status = status
    invoice.recipient_email = recipient_email.strip().lower()
    invoice.email_sent_at = datetime.now(UTC)
    invoice.email_error = error
    db.commit()
    db.refresh(invoice)
    return invoice


def list_invoices_needing_payment_reminder(
    db: Session,
    *,
    today: date | None = None,
) -> list[Invoice]:
    ref = today or datetime.now(UTC).date()
    today_str = ref.isoformat()
    stmt = (
        select(Invoice)
        .join(Job)
        .where(
            Invoice.payment_status != "paid",
            Invoice.payment_due_date.isnot(None),
            Invoice.payment_due_date <= today_str,
        )
        .options(joinedload(Invoice.job))
    )
    candidates = list(db.scalars(stmt).all())
    return [
        inv for inv in candidates
        if not reminder_sent_today(inv.payment_reminder_sent_at, today=ref)
    ]


def record_payment_reminder_sent(db: Session, invoice: Invoice) -> Invoice:
    invoice.payment_reminder_sent_at = datetime.now(UTC)
    db.commit()
    db.refresh(invoice)
    return invoice
