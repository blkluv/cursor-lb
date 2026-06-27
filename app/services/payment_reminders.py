"""Send payment reminder emails for overdue and due-today invoices."""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.repositories.invoices import (
    list_invoices_needing_payment_reminder,
    record_payment_reminder_sent,
)
from app.services.email_service import EmailSendError, send_payment_reminder_email

logger = logging.getLogger(__name__)


def send_payment_reminders(db: Session, *, today: date | None = None) -> int:
    """Send reminders for unpaid invoices due today or overdue. Returns count sent."""
    sent = 0
    for invoice in list_invoices_needing_payment_reminder(db, today=today):
        job = invoice.job
        if job is None:
            continue
        try:
            send_payment_reminder_email(db, job, invoice)
            record_payment_reminder_sent(db, invoice)
            sent += 1
        except EmailSendError as exc:
            logger.error(
                "Payment reminder failed for invoice %s: %s",
                invoice.id,
                exc,
            )
    return sent
