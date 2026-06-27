"""Password hashing helpers."""

import bcrypt

from app.models import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def effective_role(user: User) -> str:
    """Legacy rows may have NULL/empty role — treat as photographer."""
    role = (user.role or "").strip()
    if role == "customer":
        return "customer"
    return "photographer"
