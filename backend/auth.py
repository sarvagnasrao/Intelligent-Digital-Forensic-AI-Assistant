from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from backend.database import get_db
from backend import models
import os

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "idfai-secret-key-change-in-production"
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480
# 8 hours — forensic sessions are long


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login"
)

# Role hierarchy — higher index = more access
ROLE_HIERARCHY = [
    "Viewer",
    "Analyst",
    "Investigator",
    "Admin"
]


def verify_password(
        plain: str,
        hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain.encode('utf-8'),
            hashed.encode('utf-8')
        )
    except Exception:
        return False


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(
        password.encode('utf-8'), salt
    )
    return hashed.decode('utf-8')


def create_access_token(
        data: dict,
        expires_delta: Optional[
            timedelta] = None
) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or
        timedelta(
            minutes=
            ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )


def get_current_user(
        token: str = Depends(oauth2_scheme),
        db: Session = Depends(get_db)
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"}
    )
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def require_role(minimum_role: str):
    """
    Dependency factory.
    Usage: Depends(require_role("Analyst"))
    Allows the specified role and all
    higher roles.
    """
    def role_checker(
        current_user: models.User = Depends(
            get_current_user)
    ) -> models.User:
        user_level = ROLE_HIERARCHY.index(
            current_user.role
        ) if current_user.role in \
            ROLE_HIERARCHY else -1
        required_level = \
            ROLE_HIERARCHY.index(
                minimum_role
            ) if minimum_role in \
            ROLE_HIERARCHY else 999

        if user_level < required_level:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Requires {minimum_role}"
                    f" role or higher. "
                    f"Your role: "
                    f"{current_user.role}"
                )
            )
        return current_user
    return role_checker


# Convenience dependencies
require_viewer = require_role("Viewer")
require_analyst = require_role("Analyst")
require_investigator = require_role(
    "Investigator")
require_admin = require_role("Admin")
