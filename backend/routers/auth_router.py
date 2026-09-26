from fastapi import (
    APIRouter, Depends, HTTPException,
    Request, status)
from fastapi.security import (
    OAuth2PasswordRequestForm)
from sqlalchemy.orm import Session
from backend.database import get_db
from backend import models
from backend.auth import (
    verify_password, hash_password,
    create_access_token,
    get_current_user)
from backend import schemas
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import uuid
import json
import pyotp
import qrcode
import io
import base64

# Import the app-level limiter
from backend.main import limiter

router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"]
)

# ── Account lockout settings ───────────────────────────────
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


# ── Auth audit helper ──────────────────────────────────────
def _log_auth_event(
        db,
        user_id: str,
        action: str,
        details: dict):
    """
    Writes auth events to the audit log.
    case_id is None for auth events.
    """
    try:
        db.add(models.AuditLog(
            id=str(uuid.uuid4()),
            case_id=None,
            action_type=action,
            performed_by=(
                details.get("username",
                             user_id or "unknown")),
            details=json.dumps(details)
        ))
        db.commit()
    except Exception:
        pass


# ── Schemas ────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    role: str = "Analyst"


# ── Register ───────────────────────────────────────────────
@router.post("/register",
             status_code=201)
@limiter.limit("5/hour")
def register(
    request: Request,
    body: RegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Register a new user.
    Rate limited to 5 registrations/hour
    per IP to prevent abuse.
    First user created is automatically Admin.
    All subsequent users default to Analyst
    unless an Admin specifies otherwise.
    """
    # Check duplicates
    if db.query(models.User).filter(
        models.User.username ==
            body.username
    ).first():
        raise HTTPException(
            status_code=400,
            detail="Username already taken")

    if db.query(models.User).filter(
        models.User.email == body.email
    ).first():
        raise HTTPException(
            status_code=400,
            detail="Email already registered")

    # First user becomes Admin
    user_count = db.query(
        models.User).count()
    role = "Admin" if user_count == 0 \
        else body.role

    # Validate role
    valid_roles = [
        "Admin", "Investigator",
        "Analyst", "Viewer"]
    if role not in valid_roles:
        role = "Analyst"

    user = models.User(
        id=str(uuid.uuid4()),
        username=body.username,
        email=body.email,
        hashed_password=hash_password(
            body.password),
        full_name=body.full_name,
        role=role
    )
    db.add(user)
    db.commit()

    _log_auth_event(
        db, user.id,
        "ACCOUNT_CREATED",
        {
            "username": user.username,
            "role": user.role,
            "ip": request.client.host
                if request.client else "unknown"
        }
    )

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "message": (
            "Account created. "
            "You are the Admin."
            if role == "Admin"
            else "Account created."
        )
    }


# ── Login ──────────────────────────────────────────────────
@router.post("/login")
@limiter.limit("10/minute")
def login(
    request: Request,
    form: OAuth2PasswordRequestForm =
        Depends(),
    db: Session = Depends(get_db)
):
    """
    Login with username + password.
    Rate limited to 10 attempts/minute per IP.
    Account locked after 5 consecutive failures
    for 15 minutes.
    Returns JWT access token on success.
    """
    client_ip = (request.client.host
                 if request.client
                 else "unknown")

    user = db.query(models.User).filter(
        models.User.username ==
            form.username
    ).first()

    # ── Check lockout ──────────────────────
    if user and user.locked_until:
        if datetime.utcnow() < user.locked_until:
            remaining = max(1, int((
                user.locked_until -
                datetime.utcnow()
            ).total_seconds() / 60))
            _log_auth_event(
                db, user.id,
                "LOGIN_LOCKED",
                {
                    "username": form.username,
                    "ip": client_ip,
                    "locked_until":
                        str(user.locked_until)
                }
            )
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Account locked for "
                    f"{remaining} more "
                    f"minute(s) due to "
                    f"too many failed "
                    f"attempts."
                )
            )
        else:
            # Lockout period expired — reset
            user.locked_until = None
            user.failed_login_attempts = 0
            db.commit()

    # ── Wrong credentials ──────────────────
    if not user or not verify_password(
        form.password,
        user.hashed_password
    ):
        if user:
            user.failed_login_attempts = (
                (user.failed_login_attempts or 0)
                + 1
            )

            if user.failed_login_attempts \
                    >= MAX_FAILED_ATTEMPTS:
                user.locked_until = (
                    datetime.utcnow() +
                    timedelta(
                        minutes=LOCKOUT_MINUTES)
                )
                db.commit()
                _log_auth_event(
                    db, user.id,
                    "ACCOUNT_LOCKED",
                    {
                        "username": form.username,
                        "ip": client_ip,
                        "locked_until":
                            str(user.locked_until),
                        "attempts":
                            user.failed_login_attempts
                    }
                )
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Account locked for "
                        f"{LOCKOUT_MINUTES} "
                        f"minutes after "
                        f"{MAX_FAILED_ATTEMPTS} "
                        f"failed attempts."
                    )
                )

            db.commit()
            _log_auth_event(
                db, user.id,
                "LOGIN_FAILED",
                {
                    "username": form.username,
                    "ip": client_ip,
                    "attempts":
                        user.failed_login_attempts
                }
            )

        raise HTTPException(
            status_code=401,
            detail="Incorrect username "
                   "or password"
        )

    # ── Deactivated account ────────────────
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Account is deactivated")

    # ── 2FA Check ──────────────────────────
    if user.totp_enabled:
        raise HTTPException(
            status_code=200,
            detail="2FA_REQUIRED",
            headers={"X-2FA-Required": "true"}
        )

    # ── Success — reset counters ───────────
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token(
        data={
            "sub": user.id,
            "role": user.role,
            "username": user.username
        }
    )

    _log_auth_event(
        db, user.id,
        "LOGIN_SUCCESS",
        {
            "username": user.username,
            "ip": client_ip,
            "role": user.role
        }
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
            "email": user.email,
            "totp_enabled": user.totp_enabled
        }
    }


# ── 2FA Login ──────────────────────────────────────────────
class Login2FARequest(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = None

@router.post("/login-2fa")
@limiter.limit("10/minute")
def login_with_2fa(
    request: Request,
    body: Login2FARequest,
    db: Session = Depends(get_db)
):
    """Login endpoint that supports 2FA."""
    client_ip = (request.client.host if request.client else "unknown")

    user = db.query(models.User).filter(
        models.User.username == body.username
    ).first()

    # ── Check lockout ──────────────────────
    if user and user.locked_until:
        if datetime.utcnow() < user.locked_until:
            remaining = max(1, int((user.locked_until - datetime.utcnow()).total_seconds() / 60))
            raise HTTPException(
                status_code=403,
                detail=f"Account locked for {remaining} more minute(s)."
            )
        else:
            user.locked_until = None
            user.failed_login_attempts = 0
            db.commit()

    # ── Wrong credentials ──────────────────
    if not user or not verify_password(body.password, user.hashed_password):
        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                db.commit()
                raise HTTPException(
                    status_code=403,
                    detail=f"Account locked for {LOCKOUT_MINUTES} minutes."
                )
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # ── Deactivated account ────────────────
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # ── 2FA Check ──────────────────────────
    if user.totp_enabled:
        if not body.totp_code:
            return {
                "requires_2fa": True,
                "message": "Enter your 2FA code"
            }
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(body.totp_code, valid_window=1):
            raise HTTPException(status_code=401, detail="Invalid 2FA code")

    # ── Success — reset counters ───────────
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token(
        data={"sub": user.id, "role": user.role, "username": user.username}
    )

    _log_auth_event(
        db, user.id, "LOGIN_SUCCESS",
        {"username": user.username, "ip": client_ip, "role": user.role}
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "requires_2fa": False,
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
            "email": user.email,
            "totp_enabled": user.totp_enabled,
        }
    }


# ── Me ─────────────────────────────────────────────────────
@router.get("/me")
def get_me(
    current_user: models.User = Depends(
        get_current_user)
):
    """Returns current user profile."""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "last_login": str(
            current_user.last_login
        ) if current_user.last_login
          else None
    }


# ── List users (Admin) ─────────────────────────────────────
@router.get("/users")
def list_users(
    current_user: models.User = Depends(
        get_current_user),
    db: Session = Depends(get_db)
):
    """Admin only — list all users."""
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Admin only")
    users = db.query(models.User).all()
    return [{
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "last_login": str(u.last_login)
            if u.last_login else None,
        "failed_login_attempts":
            u.failed_login_attempts or 0,
        "locked_until": str(u.locked_until)
            if u.locked_until else None
    } for u in users]


# ── Update role (Admin) ────────────────────────────────────
@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: str,
    body: dict,
    current_user: models.User = Depends(
        get_current_user),
    db: Session = Depends(get_db)
):
    """Admin only — change a user's role."""
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Admin only")
    user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found")
    new_role = body.get("role")
    valid_roles = [
        "Admin", "Investigator",
        "Analyst", "Viewer"]
    if new_role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. "
                   f"Valid: {valid_roles}")
    user.role = new_role
    db.commit()
    return {"id": user_id, "role": new_role}


# ── Deactivate (Admin) ─────────────────────────────────────
@router.patch("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    current_user: models.User = Depends(
        get_current_user),
    db: Session = Depends(get_db)
):
    """Admin only — deactivate a user."""
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Admin only")
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Cannot deactivate self")
    user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found")
    user.is_active = False
    db.commit()
    return {"message": "User deactivated"}


# ── Reactivate (Admin) ─────────────────────────────────────
@router.patch("/users/{user_id}/activate")
def activate_user(
    user_id: str,
    current_user: models.User = Depends(
        get_current_user),
    db: Session = Depends(get_db)
):
    """Admin only — reactivate a user."""
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Admin only")
    user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found")
    user.is_active = True
    # Also clear any lingering lockout
    user.locked_until = None
    user.failed_login_attempts = 0
    db.commit()
    return {"message": "User reactivated"}


# ── Change own password ────────────────────────────────────
class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class AdminPasswordReset(BaseModel):
    new_password: str


@router.post("/change-password")
def change_own_password(
    body: PasswordChange,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """User changes their own password."""
    if not verify_password(
        body.current_password,
        current_user.hashed_password
    ):
        raise HTTPException(
            status_code=400,
            detail="Current password incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be 8+ chars")
    current_user.hashed_password = hash_password(body.new_password)
    db.commit()
    _log_auth_event(
        db, current_user.id,
        "PASSWORD_CHANGED",
        {"username": current_user.username}
    )
    return {"message": "Password changed"}


# ── Admin reset another user's password ───────────────────
@router.patch("/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: str,
    body: AdminPasswordReset,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Admin resets another user's password."""
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Admin only")
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be 8+ chars")
    user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found")
    user.hashed_password = hash_password(body.new_password)
    db.commit()
    _log_auth_event(
        db, current_user.id,
        "PASSWORD_RESET_BY_ADMIN",
        {
            "target_user": user.username,
            "reset_by": current_user.username
        }
    )
    return {"message": f"Password reset for {user.username}"}


# ── 2FA ──────────────────────────────────────────────────────────

@router.post("/2fa/setup")
def setup_2fa(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generates a new TOTP secret and
    returns QR code as base64 image.
    User must verify before 2FA activates.
    """
    secret = pyotp.random_base32()
    current_user.totp_secret = secret
    db.commit()

    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(
        name=current_user.email or current_user.username,
        issuer_name="IDF AI Assistant"
    )

    # Generate QR code
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "secret": secret,
        "qr_code": f"data:image/png;base64,{qr_b64}",
        "manual_entry_key": secret,
        "instructions": (
            "Scan this QR code with Google Authenticator or Authy. "
            "Then verify with a code to activate 2FA."
        )
    }


class TOTPVerify(BaseModel):
    code: str


@router.post("/2fa/verify")
def verify_and_enable_2fa(
    body: TOTPVerify,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Verifies TOTP code and enables 2FA."""
    if not current_user.totp_secret:
        raise HTTPException(
            status_code=400,
            detail="Run /2fa/setup first")

    totp = pyotp.TOTP(current_user.totp_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=400,
            detail="Invalid code. Try again.")

    current_user.totp_enabled = True
    db.commit()
    _log_auth_event(
        db, current_user.id,
        "2FA_ENABLED",
        {"username": current_user.username}
    )
    return {"message": "2FA enabled successfully"}


@router.post("/2fa/disable")
def disable_2fa(
    body: TOTPVerify,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Disables 2FA after verifying code."""
    if not current_user.totp_enabled:
        raise HTTPException(
            status_code=400,
            detail="2FA is not enabled")

    totp = pyotp.TOTP(current_user.totp_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=400,
            detail="Invalid code")

    current_user.totp_enabled = False
    current_user.totp_secret = None
    db.commit()
    _log_auth_event(
        db, current_user.id,
        "2FA_DISABLED",
        {"username": current_user.username}
    )
    return {"message": "2FA disabled"}


# ── Preferences ──────────────────────────────────────────────

@router.get("/preferences", response_model=schemas.UserPreferenceResponse)
def get_preferences(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the current user's preferences."""
    pref = current_user.preferences
    if not pref:
        pref = models.UserPreference(
            id=str(uuid.uuid4()),
            user_id=current_user.id
        )
        db.add(pref)
        db.commit()
        db.refresh(pref)
        
    return {
        "theme": pref.theme,
        "timezone": pref.timezone,
        "api_keys": json.loads(pref.api_keys) if pref.api_keys else {},
        "show_system_resources": bool(pref.show_system_resources)
    }

@router.put("/preferences", response_model=schemas.UserPreferenceResponse)
def update_preferences(
    body: schemas.UserPreferenceUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update the current user's preferences."""
    pref = current_user.preferences
    if not pref:
        pref = models.UserPreference(
            id=str(uuid.uuid4()),
            user_id=current_user.id
        )
        db.add(pref)

    if body.theme is not None:
        pref.theme = body.theme
    if body.timezone is not None:
        pref.timezone = body.timezone
    if body.api_keys is not None:
        pref.api_keys = json.dumps(body.api_keys)
    if body.show_system_resources is not None:
        pref.show_system_resources = body.show_system_resources

    db.commit()
    db.refresh(pref)
    
    return {
        "theme": pref.theme,
        "timezone": pref.timezone,
        "api_keys": json.loads(pref.api_keys) if pref.api_keys else {},
        "show_system_resources": bool(pref.show_system_resources)
    }
