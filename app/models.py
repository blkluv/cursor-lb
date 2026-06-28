"""SQLAlchemy ORM models."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Import Base only - no engine creation here
from app.db import Base

# Use TYPE_CHECKING to avoid circular imports at runtime
if TYPE_CHECKING:
    from app.db import get_engine  # For type checking only


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="photographer", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    jobs: Mapped[list["Job"]] = relationship(back_populates="user", lazy="selectin")
    payment_methods: Mapped[list["PaymentMethod"]] = relationship(back_populates="user", lazy="selectin")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    client_name: Mapped[str] = mapped_column(String(255))
    client_email: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    shoot_date: Mapped[str] = mapped_column(String(32))
    payment_due_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    tax_rate: Mapped[float] = mapped_column(Float)
    email_subject: Mapped[str] = mapped_column(String(255))
    email_body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="jobs", lazy="selectin")
    invoice: Mapped["Invoice | None"] = relationship(back_populates="job", uselist=False, lazy="selectin")

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, external_id={self.external_id}, client_name={self.client_name})>"


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    subtotal_cents: Mapped[int] = mapped_column(Integer)
    tax_cents: Mapped[int] = mapped_column(Integer)
    total_cents: Mapped[int] = mapped_column(Integer)
    client_email: Mapped[str] = mapped_column(String(255))
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    email_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(32), default="unpaid", index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payment_due_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payment_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )

    job: Mapped["Job"] = relationship(back_populates="invoice", lazy="selectin")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Invoice(id={self.id}, job_id={self.job_id}, total_cents={self.total_cents})>"


class PaymentMethod(Base):
    """Saved card metadata for a customer.

    Persists only last4, brand, exp_month, exp_year, and a mock token.
    CVV/CVC is never stored — customers must enter it on each payment.
    """

    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    last4: Mapped[str] = mapped_column(String(4))
    brand: Mapped[str] = mapped_column(String(32))
    exp_month: Mapped[int] = mapped_column(Integer)
    exp_year: Mapped[int] = mapped_column(Integer)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="payment_methods", lazy="selectin")
    payments: Mapped[list["Payment"]] = relationship(back_populates="payment_method", lazy="selectin")

    def __repr__(self) -> str:
        return f"<PaymentMethod(id={self.id}, brand={self.brand}, last4={self.last4})>"


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    payment_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_methods.id"), nullable=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    invoice: Mapped["Invoice"] = relationship(back_populates="payments", lazy="selectin")
    payment_method: Mapped["PaymentMethod | None"] = relationship(back_populates="payments", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Payment(id={self.id}, invoice_id={self.invoice_id}, amount_cents={self.amount_cents}, status={self.status})>"


# Optional: Function to create all tables (lazy)
def create_tables():
    """Create all tables if they don't exist."""
    from app.db import get_engine
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


# Optional: Function to drop all tables (use with caution!)
def drop_tables():
    """Drop all tables."""
    from app.db import get_engine
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
