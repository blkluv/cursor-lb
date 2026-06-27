"""Job persistence."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Job
from app.schemas import JobCreate, JobSeed


def list_jobs_for_user(db: Session, user_id: int) -> list[Job]:
    stmt = (
        select(Job)
        .where(Job.user_id == user_id)
        .options(joinedload(Job.invoice))
        .order_by(Job.shoot_date)
    )
    return list(db.scalars(stmt).all())


def list_jobs_for_client_email(db: Session, client_email: str) -> list[Job]:
    email_norm = client_email.strip().lower()
    stmt = (
        select(Job)
        .where(func.lower(Job.client_email) == email_norm)
        .options(joinedload(Job.invoice))
        .order_by(Job.shoot_date)
    )
    return list(db.scalars(stmt).all())


def get_job_for_user(db: Session, user_id: int, job_id: int) -> Job | None:
    return db.scalar(
        select(Job)
        .where(Job.id == job_id, Job.user_id == user_id)
        .options(joinedload(Job.invoice))
    )


def upsert_job_from_seed(db: Session, user_id: int, seed: JobSeed) -> Job:
    job = db.scalar(select(Job).where(Job.external_id == seed.external_id))
    if job is None:
        job = Job(
            user_id=user_id,
            external_id=seed.external_id,
            client_name=seed.client_name,
            client_email=str(seed.client_email).strip().lower(),
            title=seed.title,
            shoot_date=seed.shoot_date,
            amount_cents=seed.amount_cents,
            tax_rate=seed.tax_rate,
            email_subject=seed.email_subject,
            email_body=seed.email_body,
            status="pending",
        )
        db.add(job)
    else:
        job.user_id = user_id
        job.client_name = seed.client_name
        job.client_email = str(seed.client_email).strip().lower()
        job.title = seed.title
        job.shoot_date = seed.shoot_date
        job.amount_cents = seed.amount_cents
        job.tax_rate = seed.tax_rate
        job.email_subject = seed.email_subject
        job.email_body = seed.email_body
    db.commit()
    db.refresh(job)
    return job


def create_job(db: Session, user_id: int, data: JobCreate) -> Job:
    subject = data.email_subject or f"Invoice — {data.title}"
    body = data.email_body or (
        f"Thank you for booking Matt Photography for {data.title}. "
        "Invoice details below."
    )
    job = Job(
        user_id=user_id,
        external_id=f"manual-{uuid.uuid4().hex[:12]}",
        client_name=data.client_name.strip(),
        client_email=str(data.client_email).strip().lower(),
        title=data.title.strip(),
        shoot_date=data.shoot_date.strip(),
        payment_due_date=data.payment_due_date.strip() if data.payment_due_date else None,
        amount_cents=data.amount_cents,
        tax_rate=data.tax_rate,
        email_subject=subject.strip(),
        email_body=body.strip(),
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def mark_job_started(db: Session, job: Job) -> Job:
    job.status = "started"
    job.started_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job


def mark_job_done(db: Session, job: Job) -> Job:
    job.status = "done"
    job.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job
