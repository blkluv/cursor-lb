"""Customer portal HTTP routes."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import effective_role
from app.db import get_db
from app.models import User
from app.repositories.invoices import get_invoice_for_client_email
from app.repositories.users import authenticate_user, create_user, get_user_by_email
from app.schemas import CustomerJobCreate
from app.services.customer_workflow import (
    book_job_for_customer,
    get_customer_invoices,
    get_customer_jobs,
    update_customer_email,
)
from app.services.invoice_pdf import ensure_invoice_pdf
from app.services.payments import create_payment_method, get_user_payment_methods, pay_invoice

router = APIRouter(prefix="/customer")


def _current_user_id(request: Request) -> int | None:
    return request.session.get("user_id")


def _fmt_cents(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _auth_redirect(request: Request, db: Session) -> RedirectResponse | User:
    user_id = _current_user_id(request)
    if user_id is None:
        return RedirectResponse("/customer/login", status_code=status.HTTP_302_FOUND)
    user = db.get(User, user_id)
    if user is None:
        request.session.clear()
        return RedirectResponse("/customer/login", status_code=status.HTTP_302_FOUND)
    if effective_role(user) != "customer":
        return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)
    return user


@router.get("/login", response_class=HTMLResponse, response_model=None)
def customer_login_page(
    request: Request, db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    user_id = _current_user_id(request)
    if user_id is not None:
        user = db.get(User, user_id)
        if user is not None and effective_role(user) == "customer":
            return RedirectResponse("/customer/dashboard", status_code=status.HTTP_302_FOUND)
        if user is not None and effective_role(user) == "photographer":
            return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)
    return request.app.state.templates.TemplateResponse(
        request, "customer/login.html", {"error": None}
    )


@router.post("/login", response_model=None)
def customer_login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    user = authenticate_user(db, email.strip().lower(), password)
    if user is None:
        return request.app.state.templates.TemplateResponse(
            request,
            "customer/login.html",
            {"error": "Invalid email or password"},
            status_code=400,
        )
    if effective_role(user) != "customer":
        return request.app.state.templates.TemplateResponse(
            request,
            "customer/login.html",
            {"error": "This account is for the studio dashboard. Use the photographer login."},
            status_code=400,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/customer/dashboard", status_code=status.HTTP_302_FOUND)


@router.get("/signup", response_class=HTMLResponse, response_model=None)
def customer_signup_page(
    request: Request, db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    user_id = _current_user_id(request)
    if user_id is not None:
        user = db.get(User, user_id)
        if user is not None and effective_role(user) == "customer":
            return RedirectResponse("/customer/dashboard", status_code=status.HTTP_302_FOUND)
    return request.app.state.templates.TemplateResponse(
        request, "customer/signup.html", {"error": None}
    )


@router.post("/signup", response_model=None)
def customer_signup_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    email_norm = email.strip().lower()
    name_norm = name.strip()
    if len(name_norm) < 1:
        return request.app.state.templates.TemplateResponse(
            request,
            "customer/signup.html",
            {"error": "Enter your name"},
            status_code=400,
        )
    if len(password) < 6:
        return request.app.state.templates.TemplateResponse(
            request,
            "customer/signup.html",
            {"error": "Password must be at least 6 characters"},
            status_code=400,
        )
    if get_user_by_email(db, email_norm):
        return request.app.state.templates.TemplateResponse(
            request,
            "customer/signup.html",
            {"error": "Email already registered"},
            status_code=400,
        )
    user = create_user(
        db, email_norm, password, role="customer", name=name_norm,
    )
    request.session["user_id"] = user.id
    return RedirectResponse("/customer/dashboard", status_code=status.HTTP_302_FOUND)


@router.post("/logout")
def customer_logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/customer/login", status_code=status.HTTP_302_FOUND)


@router.get("/dashboard", response_class=HTMLResponse, response_model=None)
def customer_dashboard(
    request: Request, db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _auth_redirect(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    pending, started, completed = get_customer_jobs(db, auth)
    invoices = get_customer_invoices(db, auth)
    failed_deliveries = [
        inv for inv in invoices if inv.email_status == "failed"
    ]
    # Fallback: invoices tied to visible completed jobs (avoids empty list if email drift)
    if not invoices:
        invoices = sorted(
            [j.invoice for j in completed if j.invoice is not None],
            key=lambda inv: inv.sent_at,
            reverse=True,
        )
    return request.app.state.templates.TemplateResponse(
        request,
        "customer/dashboard.html",
        {
            "user_email": auth.email,
            "user_name": auth.name or auth.email,
            "pending_jobs": pending,
            "started_jobs": started,
            "completed_jobs": completed,
            "invoices": invoices,
            "failed_deliveries": failed_deliveries,
            "fmt_cents": _fmt_cents,
        },
    )


@router.get("/book", response_class=HTMLResponse, response_model=None)
def customer_book_page(
    request: Request, db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _auth_redirect(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    return request.app.state.templates.TemplateResponse(
        request,
        "customer/book.html",
        {"error": None, "user_email": auth.email, "user_name": auth.name or auth.email},
    )


@router.post("/book", response_model=None)
def customer_book_submit(
    request: Request,
    title: str = Form(...),
    shoot_date: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _auth_redirect(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    title_norm = title.strip()
    shoot_date_norm = shoot_date.strip()
    if not title_norm or not shoot_date_norm:
        return request.app.state.templates.TemplateResponse(
            request,
            "customer/book.html",
            {
                "error": "Enter a shoot title and date",
                "user_email": auth.email,
                "user_name": auth.name or auth.email,
            },
            status_code=400,
        )

    try:
        book_job_for_customer(
            db,
            auth,
            CustomerJobCreate(title=title_norm, shoot_date=shoot_date_norm),
        )
    except ValueError as exc:
        return request.app.state.templates.TemplateResponse(
            request,
            "customer/book.html",
            {
                "error": str(exc),
                "user_email": auth.email,
                "user_name": auth.name or auth.email,
            },
            status_code=400,
        )

    return RedirectResponse("/customer/dashboard", status_code=status.HTTP_302_FOUND)


@router.get("/invoices/{invoice_id}/pdf", response_model=None)
def customer_download_invoice_pdf(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> FileResponse | RedirectResponse:
    auth = _auth_redirect(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    invoice = get_invoice_for_client_email(db, auth.email, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    path = ensure_invoice_pdf(invoice.job, invoice)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"invoice-{invoice_id}.pdf",
    )


@router.get("/payment-methods", response_class=HTMLResponse, response_model=None)
def customer_payment_methods_page(
    request: Request, db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _auth_redirect(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    methods = get_user_payment_methods(db, auth.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "customer/payment_methods.html",
        {
            "user_email": auth.email,
            "user_name": auth.name or auth.email,
            "payment_methods": methods,
            "error": None,
            "success": None,
        },
    )


@router.post("/payment-methods", response_model=None)
def customer_add_payment_method(
    request: Request,
    card_number: str = Form(...),
    exp_month: int = Form(...),
    exp_year: int = Form(...),
    make_default: str | None = Form(None),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _auth_redirect(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    result = create_payment_method(
        db,
        auth,
        card_number,
        exp_month,
        exp_year,
        make_default=(make_default == "on") if make_default is not None else None,
    )
    if isinstance(result, str):
        methods = get_user_payment_methods(db, auth.id)
        return request.app.state.templates.TemplateResponse(
            request,
            "customer/payment_methods.html",
            {
                "user_email": auth.email,
                "user_name": auth.name or auth.email,
                "payment_methods": methods,
                "error": result,
                "success": None,
            },
            status_code=400,
        )

    return RedirectResponse("/customer/payment-methods", status_code=status.HTTP_302_FOUND)


@router.get("/invoices/{invoice_id}/pay", response_class=HTMLResponse, response_model=None)
def customer_pay_invoice_page(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _auth_redirect(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    invoice = get_invoice_for_client_email(db, auth.email, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.job.status != "done":
        raise HTTPException(status_code=400, detail="Invoice is not ready for payment")
    methods = get_user_payment_methods(db, auth.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "customer/pay_invoice.html",
        {
            "user_email": auth.email,
            "user_name": auth.name or auth.email,
            "invoice": invoice,
            "payment_methods": methods,
            "fmt_cents": _fmt_cents,
            "error": None,
        },
    )


@router.post("/invoices/{invoice_id}/pay", response_model=None)
def customer_pay_invoice_submit(
    invoice_id: int,
    request: Request,
    payment_method_id: str | None = Form(None),
    card_number: str | None = Form(None),
    exp_month: int | None = Form(None),
    exp_year: int | None = Form(None),
    cvc: str | None = Form(None),
    save_card: str | None = Form(None),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _auth_redirect(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    invoice = get_invoice_for_client_email(db, auth.email, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.job.status != "done":
        raise HTTPException(status_code=400, detail="Invoice is not ready for payment")

    pm_id: int | None = None
    if payment_method_id and payment_method_id.strip():
        pm_id = int(payment_method_id)

    result = pay_invoice(
        db,
        auth,
        invoice,
        payment_method_id=pm_id,
        card_number=card_number,
        exp_month=exp_month,
        exp_year=exp_year,
        cvc=cvc or "",
        save_card=save_card == "on",
    )

    if isinstance(result, str):
        methods = get_user_payment_methods(db, auth.id)
        return request.app.state.templates.TemplateResponse(
            request,
            "customer/pay_invoice.html",
            {
                "user_email": auth.email,
                "user_name": auth.name or auth.email,
                "invoice": invoice,
                "payment_methods": methods,
                "fmt_cents": _fmt_cents,
                "error": result,
            },
            status_code=400,
        )

    return RedirectResponse(
        "/customer/dashboard?paid=1",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/settings", response_class=HTMLResponse, response_model=None)
def customer_settings_page(
    request: Request, db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _auth_redirect(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    return request.app.state.templates.TemplateResponse(
        request,
        "customer/settings.html",
        {
            "user_email": auth.email,
            "user_name": auth.name or auth.email,
            "error": None,
            "success": None,
        },
    )


@router.post("/settings", response_model=None)
def customer_settings_submit(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    auth = _auth_redirect(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    result = update_customer_email(db, auth, email)
    if result is not None:
        return request.app.state.templates.TemplateResponse(
            request,
            "customer/settings.html",
            {
                "user_email": auth.email,
                "user_name": auth.name or auth.email,
                "error": result,
                "success": None,
            },
            status_code=400,
        )

    return RedirectResponse(
        "/customer/settings?updated=1",
        status_code=status.HTTP_302_FOUND,
    )
