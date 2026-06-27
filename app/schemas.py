"""Pydantic schemas for boundaries."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class JobSeed(BaseModel):
    external_id: str
    client_name: str
    client_email: EmailStr
    title: str
    shoot_date: str
    amount_cents: int = Field(gt=0)
    tax_rate: float = Field(ge=0, le=1)
    email_subject: str
    email_body: str


class CustomerJobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    shoot_date: str = Field(min_length=1, max_length=32)


class JobCreate(BaseModel):
    client_name: str = Field(min_length=1, max_length=255)
    client_email: EmailStr
    title: str = Field(min_length=1, max_length=255)
    shoot_date: str = Field(min_length=1, max_length=32)
    payment_due_date: str | None = Field(default=None, max_length=32)
    amount_cents: int = Field(gt=0)
    tax_rate: float = Field(ge=0, le=1, default=0.08)
    email_subject: str | None = None
    email_body: str | None = None


class UserPublic(BaseModel):
    id: int
    email: str


class JobView(BaseModel):
    id: int
    external_id: str
    client_name: str
    client_email: str
    title: str
    shoot_date: str
    amount_cents: int
    tax_rate: float
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None


class InvoiceView(BaseModel):
    id: int
    job_id: int
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    client_email: str
    sent_at: datetime
    payment_due_date: str | None = None
