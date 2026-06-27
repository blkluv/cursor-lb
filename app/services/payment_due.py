"""Payment due date helpers."""

from datetime import UTC, date, datetime, timedelta

from app.config import settings


def default_payment_due_date(from_dt: datetime | None = None) -> str:
    base = (from_dt or datetime.now(UTC)).date()
    return (base + timedelta(days=settings.default_payment_due_days)).isoformat()


def resolve_invoice_due_date(
    job_payment_due: str | None,
    sent_at: datetime | None = None,
) -> str:
    if job_payment_due and job_payment_due.strip():
        return job_payment_due.strip()
    return default_payment_due_date(sent_at)


def is_invoice_overdue(payment_due_date: str | None, payment_status: str) -> bool:
    if payment_status == "paid" or not payment_due_date:
        return False
    try:
        due = date.fromisoformat(payment_due_date)
    except ValueError:
        return False
    return due < datetime.now(UTC).date()


def reminder_sent_today(sent_at: datetime | None, *, today: date | None = None) -> bool:
    if sent_at is None:
        return False
    ref = today or datetime.now(UTC).date()
    return sent_at.astimezone(UTC).date() == ref
