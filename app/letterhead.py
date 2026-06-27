"""Company letterhead — shared branding for PDF invoices and emails."""

from html import escape

from app.config import settings


def company_contact_lines() -> list[str]:
    lines: list[str] = []
    if settings.company_address:
        lines.append(settings.company_address)
    if settings.company_phone:
        lines.append(settings.company_phone)
    if settings.company_email:
        lines.append(settings.company_email)
    if settings.company_website:
        lines.append(settings.company_website)
    return lines


def letterhead_text_block() -> str:
    lines = [settings.company_name]
    if settings.company_tagline:
        lines.append(settings.company_tagline)
    lines.extend(company_contact_lines())
    return "\n".join(lines)


def letterhead_html() -> str:
    name = escape(settings.company_name)
    tagline = escape(settings.company_tagline) if settings.company_tagline else ""
    contact = [escape(line) for line in company_contact_lines()]
    contact_html = "".join(f"<br>{line}" for line in contact)
    tagline_html = f"<div style='opacity:0.9;font-size:14px;'>{tagline}</div>" if tagline else ""
    return (
        "<div style='background:#1e293b;color:#fff;padding:20px 24px;border-radius:8px 8px 0 0;'>"
        f"<div style='font-size:22px;font-weight:700;'>"
        f"<span style='color:#fff;'>{name}</span>"
        "</div>"
        f"{tagline_html}"
        f"<div style='font-size:13px;margin-top:8px;color:#cbd5e1;'>{contact_html}</div>"
        "</div>"
        "<div style='height:4px;background:#d97706;'></div>"
    )


def wrap_email_html(body_html: str) -> str:
    return (
        "<div style='font-family:Inter,system-ui,sans-serif;color:#1e293b;max-width:600px;'>"
        f"{letterhead_html()}"
        f"<div style='padding:24px;background:#f8fafc;border:1px solid #e2e8f0;"
        "border-top:none;border-radius:0 0 8px 8px;'>"
        f"{body_html}"
        "</div>"
        "</div>"
    )
