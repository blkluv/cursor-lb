"""Mock card tokenization and invoice payment processing."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Invoice, Payment, PaymentMethod, User

_CARD_DIGITS = re.compile(r"\D")


def normalize_card_number(raw: str) -> str:
    return _CARD_DIGITS.sub("", raw.strip())


def detect_card_brand(number: str) -> str:
    if number.startswith("4"):
        return "visa"
    if number.startswith(("51", "52", "53", "54", "55")):
        return "mastercard"
    if len(number) >= 4:
        prefix = int(number[:4])
        if 2221 <= prefix <= 2720:
            return "mastercard"
    return "unknown"


def normalize_exp_year(exp_year: int) -> int:
    return exp_year + 2000 if exp_year < 100 else exp_year


def mock_token(user_id: int, last4: str) -> str:
    digest = hashlib.sha256(
        f"{user_id}:{last4}:{secrets.token_hex(8)}".encode()
    ).hexdigest()[:24]
    return f"tok_{digest}"


def validate_save_card_fields(
    card_number: str,
    exp_month: int,
    exp_year: int,
) -> str | None:
    number = normalize_card_number(card_number)
    if not 13 <= len(number) <= 19 or not number.isdigit():
        return "Enter a valid card number"
    brand = detect_card_brand(number)
    if brand == "unknown":
        return "Only Visa and Mastercard are supported for now"
    if not 1 <= exp_month <= 12:
        return "Enter a valid expiration month"
    exp_year = normalize_exp_year(exp_year)
    now = datetime.now(UTC)
    if exp_year < now.year or (exp_year == now.year and exp_month < now.month):
        return "Card has expired"
    return None


def validate_cvc(cvc: str) -> str | None:
    cvc_norm = cvc.strip()
    if not cvc_norm.isdigit() or not 3 <= len(cvc_norm) <= 4:
        return "Enter a valid security code"
    return None


def card_last4(card_number: str) -> str:
    return normalize_card_number(card_number)[-4:]


def create_payment_method(
    db: Session,
    user: User,
    card_number: str,
    exp_month: int,
    exp_year: int,
    *,
    make_default: bool | None = None,
) -> PaymentMethod | str:
    error = validate_save_card_fields(card_number, exp_month, exp_year)
    if error:
        return error

    number = normalize_card_number(card_number)
    exp_year = normalize_exp_year(exp_year)

    existing = list(
        db.scalars(select(PaymentMethod).where(PaymentMethod.user_id == user.id)).all()
    )
    is_first = len(existing) == 0
    is_default = make_default if make_default is not None else is_first

    if is_default:
        for pm in existing:
            pm.is_default = False

    method = PaymentMethod(
        user_id=user.id,
        last4=number[-4:],
        brand=detect_card_brand(number),
        exp_month=exp_month,
        exp_year=exp_year,
        token=mock_token(user.id, number[-4:]),
        is_default=is_default,
    )
    db.add(method)
    db.commit()
    db.refresh(method)
    return method


def get_user_payment_methods(db: Session, user_id: int) -> list[PaymentMethod]:
    return list(
        db.scalars(
            select(PaymentMethod)
            .where(PaymentMethod.user_id == user_id)
            .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.desc())
        ).all()
    )


def get_payment_method_for_user(
    db: Session, user_id: int, payment_method_id: int,
) -> PaymentMethod | None:
    return db.scalar(
        select(PaymentMethod).where(
            PaymentMethod.id == payment_method_id,
            PaymentMethod.user_id == user_id,
        )
    )


def _mock_charge_declined(last4: str) -> bool:
    return last4 == "0002"


def pay_invoice(
    db: Session,
    user: User,
    invoice: Invoice,
    *,
    payment_method_id: int | None = None,
    card_number: str | None = None,
    exp_month: int | None = None,
    exp_year: int | None = None,
    cvc: str | None = None,
    save_card: bool = False,
) -> Payment | str:
    if invoice.payment_status == "paid":
        return "This invoice is already paid"

    cvc_error = validate_cvc(cvc or "")
    if cvc_error:
        return cvc_error

    method: PaymentMethod | None = None
    charge_last4: str | None = None

    if payment_method_id is not None:
        method = get_payment_method_for_user(db, user.id, payment_method_id)
        if method is None:
            return "Select a saved payment method"
        charge_last4 = method.last4
    elif card_number and exp_month is not None and exp_year is not None:
        error = validate_save_card_fields(card_number, exp_month, exp_year)
        if error:
            return error
        charge_last4 = card_last4(card_number)
        if save_card:
            created = create_payment_method(
                db, user, card_number, exp_month, exp_year,
            )
            if isinstance(created, str):
                return created
            method = created
    else:
        return "Choose a saved card or enter card details"

    if charge_last4 is None:
        return "Payment method could not be processed"

    method_id = method.id if method is not None else None

    if _mock_charge_declined(charge_last4):
        payment = Payment(
            invoice_id=invoice.id,
            amount_cents=invoice.total_cents,
            status="failed",
            payment_method_id=method_id,
        )
        db.add(payment)
        db.commit()
        return "Payment declined — try another card"

    paid_at = datetime.now(UTC).replace(tzinfo=None)
    payment = Payment(
        invoice_id=invoice.id,
        amount_cents=invoice.total_cents,
        status="paid",
        payment_method_id=method_id,
        paid_at=paid_at,
    )
    db.add(payment)
    invoice.payment_status = "paid"
    invoice.paid_at = paid_at
    db.commit()
    db.refresh(payment)
    return payment
