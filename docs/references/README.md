# references — e2e testing

## Tool

**pytest** + **FastAPI TestClient** (Starlette) for HTTP/HTML e2e, **version**: pytest ≥8, httpx (via starlette).

No browser automation required for this prototype — all flows are server-rendered HTML forms.

## Install

```bash
uv sync --dev
```

## How the evaluator drives the app

1. Tests use `TestClient` against `app.main:app` — no live server needed for CI.
2. For manual / smoke checks against a running server, use curl or Playwright optionally.

Example pytest pattern:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_signup_redirects_to_dashboard():
    r = client.post("/signup", data={"email": "matt@example.com", "password": "secret123"})
    assert r.status_code == 200
    assert "/dashboard" in r.headers.get("location", "") or "dashboard" in r.text
```

## Run e2e / integration tests

```bash
uv run pytest tests/ -v
```

## MCP / automation in Cursor

- **cursor-ide-browser**: optional for visual QA of styled pages; not required for CI.
- Prefer `TestClient` in `tests/` for deterministic agent verification.

## LLM reference docs

Drop condensed `*-llms.txt` API docs here if the project later adds LLM features.
