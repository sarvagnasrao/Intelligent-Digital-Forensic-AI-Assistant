"""Authentication service with JWT tokens and password hashing."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import User, UserRole
from app.cases.models import Case
from app.config import get_config


def hash_password(password: str) -> str:
    """Simple SHA-256 hash for password (use bcrypt in production)."""
    salt = secrets.token_hex(16)
    return f"sha256${salt}${hashlib.sha256((salt + password).encode()).hexdigest()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    try:
        algo, salt, hash_val = hashed_password.split("$", 2)
        if algo == "sha256":
            return hashlib.sha256((salt + plain_password).encode()).hexdigest() == hash_val
        return False
    except ValueError:
        return False


class AuthService:
    """Authentication and authorization service."""

    def __init__(self, session: Session):
        self.session = session
        self.config = get_config()

    # --- Password hashing ---
    def hash_password(self, password: str) -> str:
        return hash_password(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return verify_password(plain_password, hashed_password)

    # --- Token management ---
    def create_access_token(self, data: dict, expires_delta: timedelta | None = None) -> str:
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=self.config.auth.access_token_expire_minutes))
        to_encode.update({"exp": expire, "type": "access"})
        return jwt.encode(to_encode, self.config.auth.secret_key, algorithm=self.config.auth.algorithm)

    def create_refresh_token(self, data: dict) -> str:
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + timedelta(days=self.config.auth.refresh_token_expire_days)
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(to_encode, self.config.auth.secret_key, algorithm=self.config.auth.algorithm)

    def decode_token(self, token: str) -> dict | None:
        try:
            payload = jwt.decode(token, self.config.auth.secret_key, algorithms=[self.config.auth.algorithm])
            return payload
        except JWTError:
            return None

    def verify_access_token(self, token: str) -> dict | None:
        payload = self.decode_token(token)
        if payload and payload.get("type") == "access":
            return payload
        return None

    def verify_refresh_token(self, token: str) -> dict | None:
        payload = self.decode_token(token)
        if payload and payload.get("type") == "refresh":
            return payload
        return None

    # --- User management ---
    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        full_name: str,
        role: UserRole = UserRole.INVESTIGATOR,
    ) -> User:
        user = User(
            username=username,
            email=email,
            password_hash=self.hash_password(password),
            full_name=full_name,
            role=role,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def get_user_by_username(self, username: str) -> User | None:
        return self.session.execute(select(User).where(User.username == username)).scalar_one_or_none()

    def get_user_by_email(self, email: str) -> User | None:
        return self.session.execute(select(User).where(User.email == email)).scalar_one_or_none()

    def authenticate_user(self, username: str, password: str) -> User | None:
        user = self.get_user_by_username(username)
        if not user or not user.is_active:
            return None
        if not self.verify_password(password, user.password_hash):
            return None
        return user

    def update_last_login(self, user_id: int) -> None:
        user = self.get_user_by_id(user_id)
        if user:
            user.last_login_at = datetime.now(timezone.utc)
            self.session.flush()

    def change_password(self, user_id: int, old_password: str, new_password: str) -> bool:
        user = self.get_user_by_id(user_id)
        if not user or not self.verify_password(old_password, user.password_hash):
            return False
        user.password_hash = self.hash_password(new_password)
        self.session.flush()
        return True

    def list_users(self, active_only: bool = True) -> list[User]:
        stmt = select(User)
        if active_only:
            stmt = stmt.where(User.is_active == True)
        return list(self.session.execute(stmt.order_by(User.username)).scalars().all())

    def update_user(
        self,
        user_id: int,
        *,
        full_name: str | None = None,
        email: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> User | None:
        """Update a user's editable profile fields.

        Usernames are immutable: audit records and login history refer to them,
        and renaming one silently would break that trail.
        """
        user = self.get_user_by_id(user_id)
        if user is None:
            return None
        if full_name is not None:
            user.full_name = full_name
        if email is not None:
            user.email = email
        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        self.session.flush()
        return user

    def admin_reset_password(self, user_id: int, new_password: str) -> bool:
        """Set a new password without knowing the old one (administrator action)."""
        user = self.get_user_by_id(user_id)
        if user is None:
            return False
        user.password_hash = self.hash_password(new_password)
        self.session.flush()
        return True

    def count_active_admins(self, exclude_user_id: int | None = None) -> int:
        """Count active administrators, optionally ignoring one account.

        Used to protect against deactivating or demoting the last administrator.
        """
        stmt = select(func.count(User.id)).where(
            User.is_active == True, User.role == UserRole.ADMIN
        )
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        return int(self.session.execute(stmt).scalar_one())

    # --- Authorization ---
    def user_can_access_case(self, user: User, case_id: int) -> bool:
        """Check if user can access a case (admin or assignee)."""
        if user.role == UserRole.ADMIN:
            return True
        case = self.session.get(Case, case_id)
        if not case:
            return False
        return case.assignee_id == user.id or case.created_by_id == user.id

    def user_can_modify_case(self, user: User, case_id: int) -> bool:
        """Check if user can modify a case (admin, creator, or assignee)."""
        return self.user_can_access_case(user, case_id)

    def user_can_write_case(self, user: User | None, case_id: int) -> bool:
        """Check if user can perform write operations on a case.
        
        READ_ONLY users can never write, regardless of case assignment.
        ADMIN and INVESTIGATOR users can write if they have case access.
        None user returns False.
        """
        if user is None:
            return False
        if user.role == UserRole.READ_ONLY:
            return False
        return self.user_can_access_case(user, case_id)

    def user_is_admin(self, user: User) -> bool:
        return user.role == UserRole.ADMIN

    def get_user_cases(self, user: User) -> list[Case]:
        """Get cases accessible to user."""
        if user.role == UserRole.ADMIN:
            stmt = select(Case)
        else:
            stmt = select(Case).where(
                (Case.assignee_id == user.id) | (Case.created_by_id == user.id)
            )
        return list(self.session.execute(stmt.order_by(Case.updated_at.desc())).scalars().all())

    # --- Token pair generation ---
    def create_token_pair(self, user: User) -> tuple[str, str]:
        data = {"sub": str(user.id), "username": user.username, "role": user.role.value}
        access_token = self.create_access_token(data)
        refresh_token = self.create_refresh_token(data)
        return access_token, refresh_token