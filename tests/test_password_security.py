"""Portable security regression tests for password hashing and legacy migration."""
from __future__ import annotations

import hashlib

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth.models import User, UserRole
from app.auth.service import AuthService, hash_password, verify_password
from app.db import load_all_models
from app.db.base import Base


def test_new_passwords_use_unique_slow_kdf_salts():
    first = hash_password("correct-horse-battery")
    second = hash_password("correct-horse-battery")
    assert first.startswith("pbkdf2_sha256$")
    assert first != second
    assert verify_password("correct-horse-battery", first)
    assert verify_password("correct-horse-battery", second)
    assert not verify_password("wrong", first)


def test_legacy_sha256_remains_verifiable_and_uses_exact_digest():
    password = "legacy-password"
    salt = "00112233445566778899aabbccddeeff"
    digest = hashlib.sha256((salt + password).encode()).hexdigest()
    stored = f"sha256${salt}${digest}"
    assert verify_password(password, stored)
    assert not verify_password("wrong-password", stored)


def test_unrecognized_or_malformed_hashes_are_rejected():
    assert not verify_password("a", "plain text")
    assert not verify_password("a", "sha256$missing")
    assert not verify_password("a", "pbkdf2_sha256$999999999$aa$bb")
    assert not verify_password("a", "pbkdf2_sha256$0$aa$bb")
    assert not verify_password("a", "pbkdf2_sha256$600000$nothex$nothex")


def test_successful_legacy_login_upgrades_hash_without_changing_identity():
    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            password = "existing-user-password"
            salt = "8ab197db5bc1438a"
            digest = hashlib.sha256((salt + password).encode()).hexdigest()
            original_hash = f"sha256${salt}${digest}"
            existing = User(
                username="investigator", email="investigator@example.test",
                password_hash=original_hash, full_name="Investigator",
                role=UserRole.INVESTIGATOR,
            )
            session.add(existing)
            session.commit()
            user_id = existing.id

            auth = AuthService(session)
            assert auth.authenticate_user("investigator", "invalid") is None
            assert existing.password_hash == original_hash
            authenticated = auth.authenticate_user("investigator", password)
            assert authenticated is not None
            assert authenticated.id == user_id
            assert authenticated.password_hash.startswith("pbkdf2_sha256$")
            session.commit()
        with Session(engine) as session:
            user = session.get(User, user_id)
            assert user is not None
            assert user.password_hash.startswith("pbkdf2_sha256$")
            assert verify_password(password, user.password_hash)
    finally:
        engine.dispose()


def test_inactive_account_cannot_authenticate():
    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            user = User(
                username="inactive", email="inactive@example.test",
                password_hash=hash_password("nondefault-credential"),
                full_name="Disabled", role=UserRole.ADMIN, is_active=False,
            )
            session.add(user)
            session.commit()
            assert AuthService(session).authenticate_user("inactive", "nondefault-credential") is None
    finally:
        engine.dispose()
