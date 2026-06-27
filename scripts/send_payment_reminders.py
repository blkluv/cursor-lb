#!/usr/bin/env python3
"""Send payment reminder emails for unpaid invoices due today or overdue."""

import logging
import sys

from app.db import SessionLocal, engine
from app.db_migrate import ensure_schema_synced
from app.services.payment_reminders import send_payment_reminders

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    ensure_schema_synced(engine)
    with SessionLocal() as db:
        count = send_payment_reminders(db)
    logger.info("Sent %s payment reminder(s)", count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
