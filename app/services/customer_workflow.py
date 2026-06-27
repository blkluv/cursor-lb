"""Customer-facing workflows."""

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Invoice, Job, User
from app.repositories.invoices import list_invoices_for_client_email
from app.repositories.jobs import create_job, list_jobs_for_client_email
from app.repositories.users import get_photographer_user, get_user_by_email, update_user_email
from app.schemas import CustomerJobCreate, JobCreate
from app.services.email_service import is_valid_email


def get_customer_jobs(db: Session, customer: User) -> tuple[list[Job], list[Job], list[Job]]:
    all_jobs = list_jobs_for_client_email(db, customer.email)
    pending = [j for j in all_jobs if j.status == "pending"]
    started = [j for j in all_jobs if j.status == "started"]
    completed = [j for j in all_jobs if j.status == "done"]
    return pending, started, completed


def get_customer_invoices(db: Session, customer: User) -> list[Invoice]:
    return list_invoices_for_client_email(db, customer.email)


def book_job_for_customer(db: Session, customer: User, data: CustomerJobCreate) -> Job:
    photographer = get_photographer_user(db)
    if photographer is None:
        raise ValueError("No photographer account is set up yet")

    client_name = (customer.name or "").strip() or customer.email
    job_data = JobCreate(
        client_name=client_name,
        client_email=customer.email,
        title=data.title.strip(),
        shoot_date=data.shoot_date.strip(),
        amount_cents=settings.default_shoot_amount_cents,
        tax_rate=settings.default_tax_rate,
    )
    return create_job(db, photographer.id, job_data)


def update_customer_email(db: Session, customer: User, new_email: str) -> str | None:
    """Update account email and sync client_email on the customer's jobs/invoices."""
    email_norm = new_email.strip().lower()
    if not is_valid_email(email_norm):
        return "Enter a valid email address"
    existing = get_user_by_email(db, email_norm)
    if existing is not None and existing.id != customer.id:
        return "Email already registered by another account"

    old_email = customer.email
    update_user_email(db, customer, email_norm)

    for job in list_jobs_for_client_email(db, old_email):
        job.client_email = email_norm
        if job.invoice is not None:
            job.invoice.client_email = email_norm
            if job.invoice.email_status == "pending":
                job.invoice.recipient_email = email_norm
    db.commit()
    return None
