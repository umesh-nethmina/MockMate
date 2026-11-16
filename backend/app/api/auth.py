from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AfterValidator, BaseModel, EmailStr, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_token, hash_password, verify_password
from app.config import get_settings
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _password_rules(value: str) -> str:
    if len(value.encode()) > 72:
        raise ValueError("must be at most 72 bytes")
    if value.isdigit() or value.isalpha():
        raise ValueError("must mix letters with numbers or symbols")
    return value


Password = Annotated[str, StringConstraints(min_length=8), AfterValidator(_password_rules)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(max_length=200)]


class UserOut(BaseModel):
    id: int
    email: str | None
    name: str
    is_admin: bool
    is_guest: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name, is_admin=user.is_admin, is_guest=user.is_guest)


def _token_response(user: User) -> TokenOut:
    token, expires = create_token(user)
    return TokenOut(access_token=token, expires_at=expires, user=user_out(user))


def purge_expired_guests(db: Session) -> int:
    """SRS 6.1: guest users and their sessions are deleted 24 h after creation."""
    cutoff = datetime.now(UTC) - timedelta(hours=get_settings().guest_ttl_hours)
    ids = list(db.scalars(select(User.id).where(User.is_guest.is_(True), User.created_at < cutoff)))
    if ids:
        for user in db.scalars(select(User).where(User.id.in_(ids))):
            db.delete(user)  # ORM cascade removes sessions, messages, evaluations, reports, CVs
        db.commit()
    return len(ids)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenOut:
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    admins = {e.lower() for e in get_settings().admin_emails}
    user = User(email=email, password_hash=hash_password(body.password), name=body.name, is_admin=email in admins)
    db.add(user)
    db.commit()
    return _token_response(user)


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return _token_response(user)


@router.post("/guest", status_code=status.HTTP_201_CREATED)
def guest(db: Session = Depends(get_db)) -> TokenOut:
    """FR-02: try one short text interview without an account."""
    purge_expired_guests(db)
    user = User(is_guest=True, name="Guest")
    db.add(user)
    db.commit()
    return _token_response(user)
