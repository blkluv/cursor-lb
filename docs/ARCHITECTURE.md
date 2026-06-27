# ARCHITECTURE.md — Matt's invoice assistant

> Photographer workflow app: authenticate, view pending jobs (mocked from Trello/Jira), mark work done,
> auto-send predetermined invoices via mocked email. No real external API calls.

## Layer diagram

```
┌─────────────────────────────────────────────────────────┐
│  HTTP routes (app/routes/)                              │
│  Parse forms/query params → call services               │
└───────────────────────────┬─────────────────────────────┘
                            │ depends on
┌───────────────────────────▼─────────────────────────────┐
│  Services (app/services/)                               │
│  Job listing, mark-done, invoice generation, email mock │
└───────────────────────────┬─────────────────────────────┘
                            │ depends on
┌───────────────────────────▼─────────────────────────────┐
│  Repositories (app/repositories/)                       │
│  SQLite access for users, jobs, invoices                │
└───────────────────────────┬─────────────────────────────┘
                            │ depends on
┌───────────────────────────▼─────────────────────────────┐
│  Database (app/db.py, SQLite file)                      │
└─────────────────────────────────────────────────────────┘

Boundary adapters (injected into services, never called from routes directly):
  • JobProvider  — reads mock job feed (data/mock_jobs.json), simulates Trello/Jira
  • EmailSender  — logs/mock-sends invoice emails (no SMTP)
```

## Layers

| Layer | Owns | May not |
|-------|------|---------|
| **Routes** | HTTP, cookies/sessions, Jinja2 context, redirect | Business rules, SQL, file I/O for jobs |
| **Services** | Workflows (sync jobs, complete job, send invoice) | Raw HTTP, template rendering |
| **Repositories** | CRUD queries, row → domain mapping | Business rules beyond persistence |
| **Adapters** | External-shaped data at the boundary | Direct route access |

## Dependency rule

Dependencies point **inward only**: `routes → services → repositories → db`.
Adapters are passed into services at startup; services never import routes.
Cross-cutting auth (`app/auth.py`) is used by routes only; services receive `user_id` as an argument.

## Boundary / parse rule

All untrusted input is parsed at the boundary:

- **HTTP**: Pydantic models or explicit form parsing in routes before calling services.
- **Mock job feed** (`data/mock_jobs.json`): validated into `JobSeed` Pydantic models on load; corrupt rows are skipped with a log line.
- **DB rows**: mapped to Pydantic `User`, `Job`, `Invoice` in repositories — services never index raw dicts.

Downstream code may assume these typed shapes are already valid.

## Frontend / UI

Server-rendered **Jinja2** templates with **Tailwind CSS** (CDN for prototype).
No separate SPA build. Design rules live in `.cursor/rules/frontend-design.mdc`.

## Project invariants

1. **No real external API calls** — job sources and email are mocked locally.
2. **Invoice terms are predetermined at booking** — amount, tax, and email template come from the mock job seed, not computed at send time.
3. **Completing a job is the only trigger for invoice send** — one invoice per job completion.
4. **Mock email** — when `EMAIL_MODE=mock`, emails log to `logs/email_mock.log`. With `EMAIL_MODE=mailjet`, invoices send via Mailjet API (PDF attached).

## API contract

Not applicable — server-rendered app; contract lives in templates and route handlers.
