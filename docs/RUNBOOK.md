# RUNBOOK.md — Matt's invoice assistant

## Prerequisites

1. **Python 3.12+** and **uv** (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
2. Copy env file: `cp .env.example .env` and set `SECRET_KEY` (see `.env.example` comments).
3. Install deps: `uv sync --dev`.
4. Mock job data is committed at `data/mock_jobs.json` (not gitignored).

**After model/schema changes**, sync the database:

```bash
./scripts/check-db.sh
```

This runs automatically in `./scripts/verify.sh` and on app startup.

## Running locally

**Quick start (smoke test):**

```bash
./init.sh
```

**Interactive dev server (streams logs until Ctrl+C):**

```bash
./scripts/run.sh
```

Reload watches `app/` only (not `.venv` or caches) to avoid "too many open files" on Linux.

If reload still fails, start without it:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Healthy startup looks like:

```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

Open http://127.0.0.1:8000 — you should see the login page.

## Email (Mailjet)

Invoice emails are sent via [Mailjet](https://www.mailjet.com/) when `EMAIL_MODE=mailjet` and API keys are set in `.env`.

1. Copy API key + secret from https://app.mailjet.com/account/apikeys into `.env`.
2. Set `MAILJET_FROM_EMAIL` to a **verified sender** in your Mailjet account.
3. Set `EMAIL_MODE=mailjet`.

Each invoice email includes HTML + text body and the PDF attachment.

To test without sending (CI / local): `EMAIL_MODE=mock` — writes to `logs/email_mock.log` instead.

## Checking logs

- **stdout**: uvicorn and app logs print to the terminal running `run.sh`.
- **Mock mode** (`EMAIL_MODE=mock`): invoice sends append to `logs/email_mock.log`.
- **Mailjet mode**: success/failure appears in uvicorn logs; check Mailjet dashboard for delivery.
- **Invoice PDFs**: saved to `data/invoices/invoice-{id}.pdf` (gitignored); download from dashboard.

```bash
tail -f logs/email_mock.log
```

## Payment reminders (cron)

Unpaid invoices with a due date of today or earlier get a reminder email when you run:

```bash
uv run python scripts/send_payment_reminders.py
```

Schedule daily (e.g. 9:00 AM server time):

```bash
0 9 * * * cd /path/to/cursor-hackathon && uv run python scripts/send_payment_reminders.py
```

- `DEFAULT_PAYMENT_DUE_DAYS` (default 14) sets the due date when Matt does not pick one at booking.
- `APP_BASE_URL` is used in reminder emails for the pay link (`/customer/invoices/{id}/pay`).
- Reminders append to `logs/email_mock.log` in mock mode (lines prefixed with `REMINDER`).

## Stopping the app

- If using `scripts/run.sh`: press **Ctrl+C** — trap kills the uvicorn process.
- Verify stopped: `ps aux | grep uvicorn` should show no listener on port 8000.

## Deploying to a remote server (Docker + Compose)

Target: single VM with Docker.

1. Clone repo on the server.
2. `cp .env.example .env` and set `SECRET_KEY` and `DATABASE_URL`.
3. Build and run (when `docker-compose.yml` is added):

   ```bash
   docker compose up -d --build
   ```

4. Verify: `curl -sf http://localhost:8000/health` returns `{"status":"ok"}`.
5. Check logs: `docker compose logs -f app`.

Until Docker is wired, use `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000` behind nginx or a PaaS.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `SECRET_KEY` error on boot | Set value in `.env` |
| Port in use | Change `PORT` in `.env` or kill existing uvicorn |
| Empty job list | Ensure `data/mock_jobs.json` exists; restart app to sync seeds |
| `no such column` SQLite error | Run `./scripts/check-db.sh` then restart the app |
