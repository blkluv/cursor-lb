"""HTTP route handlers."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import effective_role
from app.config import settings
from app.db import get_db
from app.models import User
from app.repositories.invoices import get_invoice_for_user
from app.repositories.users import authenticate_user, create_user, get_user_by_email
from app.schemas import JobCreate
from app.services.analytics import get_revenue_analytics
from app.services.invoice_pdf import ensure_invoice_pdf
from app.services.workflow import (
    book_job,
    complete_job,
    get_dashboard_jobs,
    resend_invoice,
    start_job,
)

router = APIRouter()


def _current_user_id(request: Request) -> int | None:
    return request.session.get("user_id")


def _require_user(request: Request) -> int:
    user_id = _current_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user_id


def _fmt_cents(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _require_photographer(request: Request, db: Session) -> RedirectResponse | User:
    user_id = _current_user_id(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)
    user = db.get(User, user_id)
    if user is None:
        request.session.clear()
        return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)
    if effective_role(user) != "photographer":
        return RedirectResponse("/customer/dashboard", status_code=status.HTTP_302_FOUND)
    return user


@router.get("/login", response_class=HTMLResponse, response_model=None)
def login_page(request: Request, db: Session = Depends(get_db)) -> RedirectResponse | HTMLResponse:
    user_id = _current_user_id(request)
    if user_id is not None:
        user = db.get(User, user_id)
        if user is not None and effective_role(user) == "customer":
            return RedirectResponse("/customer/dashboard", status_code=status.HTTP_302_FOUND)
        return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)
    return request.app.state.templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_model=None)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    user = authenticate_user(db, email.strip().lower(), password)
    if user is None:
        return request.app.state.templates.TemplateResponse(
            request, "login.html", {"error": "Invalid email or password"}, status_code=400
        )
    if effective_role(user) == "customer":
        return request.app.state.templates.TemplateResponse(
            request,
            "login.html",
            {"error": "This account is for clients. Use the client portal login."},
            status_code=400,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)


@router.get("/signup", response_class=HTMLResponse, response_model=None)
def signup_page(request: Request, db: Session = Depends(get_db)) -> RedirectResponse | HTMLResponse:
    user_id = _current_user_id(request)
    if user_id is not None:
        user = db.get(User, user_id)
        if user is not None and effective_role(user) == "customer":
            return RedirectResponse("/customer/dashboard", status_code=status.HTTP_302_FOUND)
        return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)
    return request.app.state.templates.TemplateResponse(request, "signup.html", {"error": None})


@router.post("/signup", response_model=None)
def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    email_norm = email.strip().lower()
    if len(password) < 6:
        return request.app.state.templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Password must be at least 6 characters"},
            status_code=400,
        )
    if get_user_by_email(db, email_norm):
        return request.app.state.templates.TemplateResponse(
            request, "signup.html", {"error": "Email already registered"}, status_code=400
        )
    user = create_user(db, email_norm, password)
    request.session["user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)


@router.get("/dashboard", response_class=HTMLResponse, response_model=None)
def dashboard(request: Request, db: Session = Depends(get_db)) -> RedirectResponse | HTMLResponse:
    auth = _require_photographer(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    pending, started, completed = get_dashboard_jobs(db, auth.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user_email": auth.email,
            "pending_jobs": pending,
            "started_jobs": started,
            "completed_jobs": completed,
            "fmt_cents": _fmt_cents,
        },
    )


@router.get("/analytics", response_class=HTMLResponse, response_model=None)
def analytics_page(
    request: Request, db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _require_photographer(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    analytics = get_revenue_analytics(db, auth.id)
    total = analytics.total_pipeline_cents
    pending_pct = round(analytics.pending_cents / total * 100) if total else 0
    paid_pct = round(analytics.paid_cents / total * 100) if total else 0
    return request.app.state.templates.TemplateResponse(
        request,
        "analytics.html",
        {
            "user_email": auth.email,
            "analytics": analytics,
            "fmt_cents": _fmt_cents,
            "pending_pct": pending_pct,
            "paid_pct": paid_pct,
        },
    )


@router.get("/jobs/book", response_class=HTMLResponse, response_model=None)
def job_book_page(
    request: Request, db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _require_photographer(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    return request.app.state.templates.TemplateResponse(
        request,
        "job_book.html",
        {
            "error": None,
            "user_email": auth.email,
            "default_payment_due_days": settings.default_payment_due_days,
        },
    )


@router.post("/jobs/book", response_model=None)
def job_book_submit(
    request: Request,
    client_name: str = Form(...),
    client_email: str = Form(...),
    title: str = Form(...),
    shoot_date: str = Form(...),
    amount_dollars: str = Form(...),
    tax_rate_percent: str = Form("8"),
    payment_due_date: str = Form(""),
    email_subject: str = Form(""),
    email_body: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _require_photographer(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    try:
        amount = float(amount_dollars)
        if amount <= 0:
            raise ValueError("Amount must be positive")
        amount_cents = int(round(amount * 100))
        tax_pct = float(tax_rate_percent or "8")
        if tax_pct < 0 or tax_pct > 100:
            raise ValueError("Tax must be between 0 and 100")
        tax_rate = tax_pct / 100
    except ValueError:
        return request.app.state.templates.TemplateResponse(
            request,
            "job_book.html",
            {
                "error": "Enter a valid amount and tax rate",
                "user_email": auth.email,
            },
            status_code=400,
        )

    data = JobCreate(
        client_name=client_name,
        client_email=client_email,
        title=title,
        shoot_date=shoot_date,
        payment_due_date=payment_due_date.strip() or None,
        amount_cents=amount_cents,
        tax_rate=tax_rate,
        email_subject=email_subject.strip() or None,
        email_body=email_body.strip() or None,
    )
    book_job(db, auth.id, data)
    return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)


@router.post("/jobs/{job_id}/start")
def job_start(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    auth = _require_photographer(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    start_job(db, auth.id, job_id)
    return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)


@router.post("/jobs/{job_id}/complete")
def job_complete(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    auth = _require_photographer(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    ok, _ = complete_job(db, auth.id, job_id)
    if not ok:
        pass  # still redirect; flash messages optional for MVP
    return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)


@router.post("/jobs/{job_id}/resend-invoice")
def job_resend_invoice(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    auth = _require_photographer(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    resend_invoice(db, auth.id, job_id)
    return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)


@router.get("/invoices/{invoice_id}/pdf", response_model=None)
def download_invoice_pdf(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> FileResponse | RedirectResponse:
    auth = _require_photographer(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    invoice = get_invoice_for_user(db, auth.id, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    path = ensure_invoice_pdf(invoice.job, invoice)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"invoice-{invoice_id}.pdf",
    )
