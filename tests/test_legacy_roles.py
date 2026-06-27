"""Tests for legacy user role handling."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import hash_password
from app.db import SessionLocal, engine
from tests.conftest import signup_and_sync


def test_legacy_null_role_user_can_access_dashboard(client: TestClient):
    """Users with NULL/empty role (pre-role migration) reach /dashboard without redirect loop."""
    email = "legacy-null@studio.com"
    password = "legacy123"
    signup_and_sync(client, email, password)

    with SessionLocal() as db:
        db.execute(
            text("UPDATE users SET role = '' WHERE email = :email"),
            {"email": email},
        )
        db.commit()

    # Photographer dashboard must load (not bounce to customer portal)
    dash = client.get("/dashboard", follow_redirects=False)
    assert dash.status_code == 200
    assert "Your shoots" in dash.text

    # Customer portal sends legacy photographer to studio dashboard (no loop)
    customer = client.get("/customer/dashboard", follow_redirects=False)
    assert customer.status_code == 302
    assert customer.headers["location"] == "/dashboard"

    followed = client.get("/customer/dashboard", follow_redirects=True)
    assert followed.status_code == 200
    assert "Your shoots" in followed.text


def test_normalize_user_roles_fixes_null_in_db():
    """Startup migration backfills NULL/empty roles to photographer."""
    with SessionLocal() as db:
        db.execute(
            text(
                "INSERT INTO users (email, password_hash, role) "
                "VALUES (:email, :hash, '')"
            ),
            {"email": "orphan-role@test.com", "hash": hash_password("x")},
        )
        db.commit()

    from app.db_migrate import normalize_user_roles

    normalize_user_roles(engine)

    with SessionLocal() as db:
        row = db.execute(
            text("SELECT role FROM users WHERE email = :email"),
            {"email": "orphan-role@test.com"},
        ).fetchone()
        assert row is not None
        assert row[0] == "photographer"
