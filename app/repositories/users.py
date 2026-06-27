"""User persistence."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import effective_role, hash_password, verify_password
from app.models import User


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def list_photographer_users(db: Session) -> list[User]:
    """All studio photographer accounts, oldest first."""
    users = list(db.scalars(select(User).order_by(User.id)).all())
    return [user for user in users if effective_role(user) == "photographer"]


def get_photographer_user(db: Session) -> User | None:
    from app.config import settings

    email = settings.photographer_email.strip().lower()
    if email:
        user = get_user_by_email(db, email)
        if user is not None and effective_role(user) == "photographer":
            return user

    photographers = list_photographer_users(db)
    if not photographers:
        return None
    return photographers[0]


def create_user(
    db: Session,
    email: str,
    password: str,
    *,
    role: str = "photographer",
    name: str | None = None,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        role=role,
        name=name.strip() if name else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def update_user_email(db: Session, user: User, new_email: str) -> User:
    user.email = new_email.strip().lower()
    db.commit()
    return user
