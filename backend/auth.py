import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User

# JWT config — the signing key MUST come from the environment. There is no
# committed fallback: a hardcoded default would let anyone with the repo forge
# valid session tokens. Fail fast at import if it is missing.
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or not SECRET_KEY.strip():
    raise RuntimeError(
        "SECRET_KEY environment variable is required (set it in the app's .env). "
        "Refusing to start without a JWT signing key."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week token lifespan for ease of CLI operation

# Password hashing
pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

# OAuth2 setup (for token URL swagger documentation)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_user_from_token(token: Optional[str], db: Session) -> Optional[User]:
    """Resolve a JWT ('<jwt>' or 'Bearer <jwt>') to its User, or None if the token
    is missing, malformed, expired, or names a user that no longer exists.

    Shared by get_current_user (the API dependency) and the HTML route guards so
    both agree on who is signed in. Gating a page on cookie *presence* while the
    API checks token *validity* is what caused the infinite login<->app redirect
    loop for expired/invalid tokens — routing both through this keeps them in sync.
    """
    if not token:
        return None
    if token.startswith("Bearer "):
        token = token.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
    except JWTError:
        return None
    if not email:
        return None
    return db.query(User).filter(User.email == email).first()

# Custom hybrid dependency to resolve token from Authorization header OR cookie
async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Prefer the Authorization header (CLI / API clients); fall back to the cookie
    # (browser convenience). get_user_from_token strips the optional "Bearer ".
    token = request.headers.get("Authorization") or request.cookies.get("access_token")

    user = get_user_from_token(token, db)
    if user is None:
        raise credentials_exception

    # Resolve the caller's effective permissions ONCE, here, and cache them on
    # the user for the rest of the request.
    #
    # This is load-bearing, not an optimisation. Every route checks access with
    # `permissions.require(current_user, ...)`, which has no database session —
    # so without this, a per-user exception or a saved permission matrix would
    # show correctly in the UI and be ignored by the routes that enforce it. A
    # deny you can see but that does not apply is worse than no deny at all.
    # Doing it at authentication means every existing call site picks it up with
    # no change and none can be forgotten.
    from backend import permissions  # local import: auth is imported by permissions' callers
    try:
        user._effective_permissions = permissions.permissions_for(user, db)
    except Exception:  # noqa: BLE001
        # Never let a permission-resolution problem turn into a 500 on every
        # request. Falling through leaves permissions_for() to compute from the
        # role alone, which is the pre-existing behaviour.
        pass

    return user
