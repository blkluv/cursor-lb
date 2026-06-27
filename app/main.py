"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from app.config import settings
from app.customer_routes import router as customer_router
from app.db import engine
from app.db_migrate import ensure_schema_synced
from app.routes import router
from app.services.payment_due import is_invoice_overdue

logging.basicConfig(level=settings.log_level.upper())
BASE_DIR = Path(__file__).resolve().parent


def _template_invoice_overdue(invoice) -> bool:
    return is_invoice_overdue(invoice.payment_due_date, invoice.payment_status)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema_synced(engine)
    yield


app = FastAPI(title="Matt Invoice Assistant", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.state.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.state.templates.env.globals["invoice_is_overdue"] = _template_invoice_overdue
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(router)
app.include_router(customer_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def root() -> RedirectResponse:
    return RedirectResponse("/login")
