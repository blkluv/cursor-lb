"""Revenue analytics for the dashboard."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.repositories.jobs import list_jobs_for_user
from app.services.workflow import sync_mock_jobs


@dataclass
class RevenueAnalytics:
    pending_cents: int
    pending_count: int
    booked_count: int
    in_progress_count: int
    paid_cents: int
    paid_count: int
    total_pipeline_cents: int


def _job_total_cents(amount_cents: int, tax_rate: float) -> int:
    tax = int(round(amount_cents * tax_rate))
    return amount_cents + tax


def get_revenue_analytics(db: Session, user_id: int) -> RevenueAnalytics:
    sync_mock_jobs(db, user_id)
    jobs = list_jobs_for_user(db, user_id)

    pending_cents = 0
    booked_count = 0
    in_progress_count = 0
    unpaid_invoiced_count = 0
    paid_cents = 0
    paid_count = 0

    for job in jobs:
        if job.status in ("pending", "started"):
            pending_cents += _job_total_cents(job.amount_cents, job.tax_rate)
            if job.status == "pending":
                booked_count += 1
            else:
                in_progress_count += 1
        elif job.status == "done" and job.invoice:
            if job.invoice.payment_status == "paid":
                paid_cents += job.invoice.total_cents
                paid_count += 1
            else:
                pending_cents += job.invoice.total_cents
                unpaid_invoiced_count += 1

    pending_count = booked_count + in_progress_count + unpaid_invoiced_count
    return RevenueAnalytics(
        pending_cents=pending_cents,
        pending_count=pending_count,
        booked_count=booked_count,
        in_progress_count=in_progress_count,
        paid_cents=paid_cents,
        paid_count=paid_count,
        total_pipeline_cents=pending_cents + paid_cents,
    )
