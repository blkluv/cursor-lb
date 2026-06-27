"""Business workflows."""

from sqlalchemy.orm import Session

from app.models import Job
from app.repositories.invoices import create_invoice_for_job
from app.repositories.jobs import (
    create_job,
    get_job_for_user,
    list_jobs_for_user,
    mark_job_done,
    mark_job_started,
    upsert_job_from_seed,
)
from app.schemas import JobCreate
from app.services.email_service import EmailSendError, send_invoice_email
from app.services.invoice_pdf import ensure_invoice_pdf, generate_invoice_pdf
from app.services.job_provider import load_job_seeds


def sync_mock_jobs(db: Session, user_id: int) -> None:
    for seed in load_job_seeds():
        upsert_job_from_seed(db, user_id, seed)


def get_dashboard_jobs(db: Session, user_id: int) -> tuple[list, list, list]:
    sync_mock_jobs(db, user_id)
    all_jobs = list_jobs_for_user(db, user_id)
    pending = [j for j in all_jobs if j.status == "pending"]
    started = [j for j in all_jobs if j.status == "started"]
    completed = [j for j in all_jobs if j.status == "done"]
    return pending, started, completed


def book_job(db: Session, user_id: int, data: JobCreate) -> Job:
    return create_job(db, user_id, data)


def start_job(db: Session, user_id: int, job_id: int) -> tuple[bool, str]:
    job = get_job_for_user(db, user_id, job_id)
    if job is None:
        return False, "Job not found"
    if job.status != "pending":
        return False, "Only booked (pending) jobs can be started"
    mark_job_started(db, job)
    return True, "Job started"


def complete_job(db: Session, user_id: int, job_id: int) -> tuple[bool, str]:
    job = get_job_for_user(db, user_id, job_id)
    if job is None:
        return False, "Job not found"
    if job.status == "done":
        return False, "Job already completed"
    if job.status != "started":
        return False, "Start the job before marking it done"
    job = mark_job_done(db, job)
    invoice = create_invoice_for_job(db, job)
    pdf_path = generate_invoice_pdf(job, invoice)
    try:
        send_invoice_email(db, job, invoice, pdf_path)
    except EmailSendError as exc:
        return False, str(exc)
    return True, "Invoice sent"


def resend_invoice(db: Session, user_id: int, job_id: int) -> tuple[bool, str]:
    job = get_job_for_user(db, user_id, job_id)
    if job is None:
        return False, "Job not found"
    if job.status != "done":
        return False, "Only completed jobs can have invoices resent"
    if job.invoice is None:
        return False, "No invoice for this job"
    invoice = job.invoice
    pdf_path = ensure_invoice_pdf(job, invoice)
    try:
        send_invoice_email(db, job, invoice, pdf_path)
    except EmailSendError as exc:
        return False, str(exc)
    return True, "Invoice resent"
