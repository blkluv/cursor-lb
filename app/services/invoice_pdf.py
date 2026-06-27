"""Generate downloadable invoice PDFs."""

from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.config import settings
from app.letterhead import company_contact_lines
from app.models import Invoice, Job

INVOICE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "invoices"
# Slate header + amber accent (matches app UI)
_HEADER_FILL = (30, 41, 59)
_ACCENT_FILL = (217, 119, 6)
_TEXT_ON_HEADER = (255, 255, 255)
_TEXT_MUTED = (148, 163, 184)


def invoice_pdf_path(invoice_id: int) -> Path:
    return INVOICE_DIR / f"invoice-{invoice_id}.pdf"


def _safe(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def _fmt_cents(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _draw_letterhead(pdf: FPDF) -> None:
    pdf.set_fill_color(*_HEADER_FILL)
    pdf.rect(0, 0, 210, 32, style="F")
    pdf.set_fill_color(*_ACCENT_FILL)
    pdf.rect(0, 32, 210, 2, style="F")

    pdf.set_xy(15, 10)
    pdf.set_text_color(*_TEXT_ON_HEADER)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 8, _safe(settings.company_name), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if settings.company_tagline:
        pdf.set_x(15)
        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(*_TEXT_MUTED)
        pdf.cell(0, 6, _safe(settings.company_tagline), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    contact = "  |  ".join(_safe(line) for line in company_contact_lines())
    if contact:
        pdf.set_x(15)
        pdf.set_font("Helvetica", size=9)
        pdf.cell(0, 5, contact, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(42)
    pdf.set_text_color(0, 0, 0)


def generate_invoice_pdf(job: Job, invoice: Invoice) -> Path:
    INVOICE_DIR.mkdir(parents=True, exist_ok=True)
    path = invoice_pdf_path(invoice.id)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    _draw_letterhead(pdf)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "INVOICE", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 7, _safe(f"Invoice #{invoice.id}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    sent = (invoice.sent_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M")
    pdf.cell(0, 7, f"Date: {sent}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Bill to", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 7, _safe(job.client_name), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 7, _safe(job.client_email), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Shoot details", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 7, _safe(job.title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 7, f"Shoot date: {job.shoot_date}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 7, f"Reference: {job.external_id}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(6)

    col_w = 130
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(col_w, 8, "Description", border=1)
    pdf.cell(50, 8, "Amount", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")

    pdf.set_font("Helvetica", size=11)
    pdf.cell(col_w, 8, _safe(job.title), border=1)
    pdf.cell(
        50, 8, _fmt_cents(invoice.subtotal_cents), border=1,
        new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R",
    )

    tax_pct = int(round(job.tax_rate * 100))
    pdf.cell(col_w, 8, f"Tax ({tax_pct}%)", border=1)
    pdf.cell(
        50, 8, _fmt_cents(invoice.tax_cents), border=1,
        new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R",
    )

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(col_w, 8, "Total due", border=1)
    pdf.cell(
        50, 8, _fmt_cents(invoice.total_cents), border=1,
        new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R",
    )
    pdf.ln(8)

    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 6, _safe(job.email_body))

    pdf.output(str(path))
    return path


def ensure_invoice_pdf(job: Job, invoice: Invoice) -> Path:
    """Return path to invoice PDF, regenerated so branding and content stay current."""
    return generate_invoice_pdf(job, invoice)
