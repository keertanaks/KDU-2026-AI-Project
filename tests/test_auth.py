"""
Tests for authentication service: password hashing, session lifecycle,
session expiry, and session revocation.

DB tests require a running PostgreSQL instance (Docker) and use the
session-scoped 'db' fixture from conftest.py.
"""

import uuid
from datetime import datetime, timedelta

import pytest

from app.auth.models import Session as DBSession, UserRole
from app.auth.service import AuthService


# ---------------------------------------------------------------------------
# AuthService.hash_password / verify_password (pure unit tests — no DB)
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_is_bytes(self):
        h = AuthService.hash_password("secret")
        assert isinstance(h, bytes)

    def test_hash_is_bcrypt_format(self):
        h = AuthService.hash_password("secret")
        decoded = h.decode("utf-8")
        # bcrypt hashes start with $2b$ and are 60 characters
        assert decoded.startswith("$2b$")
        assert len(decoded) == 60

    def test_hash_uses_rounds_12(self):
        h = AuthService.hash_password("secret")
        # bcrypt format: $2b$<rounds>$...
        rounds = int(h.decode("utf-8").split("$")[2])
        assert rounds == 12

    def test_verify_correct_password(self):
        h = AuthService.hash_password("correct_horse")
        assert AuthService.verify_password("correct_horse", h) is True

    def test_verify_wrong_password(self):
        h = AuthService.hash_password("correct_horse")
        assert AuthService.verify_password("wrong_password", h) is False

    def test_different_password_same_hash_fails(self):
        h = AuthService.hash_password("password1")
        assert AuthService.verify_password("password2", h) is False

    def test_two_hashes_of_same_password_differ(self):
        # bcrypt generates a fresh salt each time
        h1 = AuthService.hash_password("same")
        h2 = AuthService.hash_password("same")
        assert h1 != h2

    def test_both_hashes_verify_correctly(self):
        h1 = AuthService.hash_password("same")
        h2 = AuthService.hash_password("same")
        assert AuthService.verify_password("same", h1) is True
        assert AuthService.verify_password("same", h2) is True


# ---------------------------------------------------------------------------
# AuthService.create_session (integration — requires DB)
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_returns_uuid_string(self, db, test_user):
        sid = AuthService.create_session(db, test_user.user_id, test_user.role)
        assert isinstance(sid, str)
        # Must parse as a valid UUID
        uuid.UUID(sid)

    def test_session_persisted_in_db(self, db, test_user):
        sid = AuthService.create_session(db, test_user.user_id, test_user.role)
        row = db.query(DBSession).filter_by(session_id=sid).first()
        assert row is not None

    def test_session_is_valid_on_creation(self, db, test_user):
        sid = AuthService.create_session(db, test_user.user_id, test_user.role)
        row = db.query(DBSession).filter_by(session_id=sid).first()
        assert row.is_valid is True

    def test_session_expires_in_8_hours(self, db, test_user):
        sid = AuthService.create_session(db, test_user.user_id, test_user.role)
        row = db.query(DBSession).filter_by(session_id=sid).first()
        delta = row.expires_at - datetime.utcnow()
        # Allow ±10 seconds drift from the expected 8-hour window
        assert timedelta(hours=7, minutes=59, seconds=50) < delta < timedelta(hours=8, seconds=10)


# ---------------------------------------------------------------------------
# AuthService.validate_session (integration — requires DB)
# ---------------------------------------------------------------------------

class TestValidateSession:
    def test_valid_session_returns_dict(self, db, test_user):
        sid = AuthService.create_session(db, test_user.user_id, test_user.role)
        result = AuthService.validate_session(db, sid)
        assert result is not None
        assert result["user_id"] == test_user.user_id
        assert result["session_id"] == sid

    def test_valid_session_includes_role(self, db, test_user):
        sid = AuthService.create_session(db, test_user.user_id, test_user.role)
        result = AuthService.validate_session(db, sid)
        assert result["role"] == test_user.role

    def test_nonexistent_session_returns_none(self, db):
        result = AuthService.validate_session(db, str(uuid.uuid4()))
        assert result is None

    def test_expired_session_returns_none(self, db, test_user):
        sid = AuthService.create_session(db, test_user.user_id, test_user.role)
        row = db.query(DBSession).filter_by(session_id=sid).first()
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        result = AuthService.validate_session(db, sid)
        assert result is None

    def test_revoked_session_returns_none(self, db, test_user):
        sid = AuthService.create_session(db, test_user.user_id, test_user.role)
        AuthService.revoke_session(db, sid)
        result = AuthService.validate_session(db, sid)
        assert result is None


# ---------------------------------------------------------------------------
# AuthService.revoke_session (integration — requires DB)
# ---------------------------------------------------------------------------

class TestRevokeSession:
    def test_revoke_sets_is_valid_false(self, db, test_user):
        sid = AuthService.create_session(db, test_user.user_id, test_user.role)
        AuthService.revoke_session(db, sid)
        db.expire_all()
        row = db.query(DBSession).filter_by(session_id=sid).first()
        assert row.is_valid is False

    def test_revoke_nonexistent_session_does_not_raise(self, db):
        # Should be a no-op, not an exception
        AuthService.revoke_session(db, str(uuid.uuid4()))

    def test_revoke_idempotent(self, db, test_user):
        sid = AuthService.create_session(db, test_user.user_id, test_user.role)
        AuthService.revoke_session(db, sid)
        AuthService.revoke_session(db, sid)  # second call must not raise
        row = db.query(DBSession).filter_by(session_id=sid).first()
        assert row.is_valid is False

    def test_revoked_session_cannot_be_revalidated(self, db, test_user):
        sid = AuthService.create_session(db, test_user.user_id, test_user.role)
        assert AuthService.validate_session(db, sid) is not None
        AuthService.revoke_session(db, sid)
        assert AuthService.validate_session(db, sid) is None

    def test_revoking_one_session_does_not_affect_another(self, db, test_user):
        sid1 = AuthService.create_session(db, test_user.user_id, test_user.role)
        sid2 = AuthService.create_session(db, test_user.user_id, test_user.role)
        AuthService.revoke_session(db, sid1)
        assert AuthService.validate_session(db, sid2) is not None
