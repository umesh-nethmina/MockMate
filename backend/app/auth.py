"""Password hashing (bcrypt) and JWT bearer tokens that expire after 24 h (FR-01, NFR-05)."""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; the API caps passwords at 72 bytes so nothing is silently ignored
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(user: User) -> tuple[str, datetime]:
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(hours=settings.jwt_expire_hours)
    payload = {"sub": str(user.id), "exp": expires, "guest": user.is_guest}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM), expires


def _unauthorized(detail: str = "Please log in to continue") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    if creds is None:
        raise _unauthorized()
    try:
        payload = jwt.decode(creds.credentials, get_settings().jwt_secret, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except jwt.ExpiredSignatureError as e:
        raise _unauthorized("Your session has expired - please log in again") from e
    except (jwt.InvalidTokenError, KeyError, ValueError) as e:
        raise _unauthorized() from e
    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized()
    return user


def require_account(user: User = Depends(get_current_user)) -> User:
    """Endpoints that need a registered account (not a guest)."""
    if user.is_guest:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Create a free account to use this feature")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user
