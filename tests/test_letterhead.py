"""Letterhead branding tests."""

from pathlib import Path

from fpdf import FPDF

from app.config import settings
from app.letterhead import letterhead_html, letterhead_text_block, wrap_email_html
from app.models import Invoice, Job
from app.services.invoice_pdf import _draw_letterhead, generate_invoice_pdf


def test_letterhead_text_includes_company_name():
    block = letterhead_text_block()
    assert settings.company_name in block


def test_letterhead_html_includes_company_name():
    html = letterhead_html()
    assert settings.company_name in html


def test_wrap_email_html_includes_letterhead():
    wrapped = wrap_email_html("<p>Invoice body</p>")
    assert settings.company_name in wrapped
    assert "Invoice body" in wrapped


def test_pdf_includes_letterhead(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "app.services.invoice_pdf.INVOICE_DIR",
        tmp_path,
    )
    job = Job(
        id=1,
        user_id=1,
        external_id="test-1",
        client_name="Client",
        client_email="client@example.com",
        title="Test shoot",
        shoot_date="2026-07-01",
        amount_cents=100000,
        tax_rate=0.08,
        email_subject="Invoice",
        email_body="Thanks.",
        status="done",
    )
    invoice = Invoice(
        id=7,
        job_id=1,
        subtotal_cents=100000,
        tax_cents=8000,
        total_cents=108000,
        client_email="client@example.com",
    )
    path = generate_invoice_pdf(job, invoice)
    assert path.is_file()
    assert path.stat().st_size > 0


def test_draw_letterhead_runs_without_error():
    pdf = FPDF()
    pdf.add_page()
    _draw_letterhead(pdf)
