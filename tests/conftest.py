"""
Shared pytest fixtures.

DB fixtures connect to the live PostgreSQL instance (Docker).
Tests that need a database are marked with @pytest.mark.usefixtures("db")
or accept 'db' / 'test_user' as a parameter.

Test users and sessions created here are cleaned up in teardown.
Audit log rows are NOT cleaned up because the table is intentionally
append-only (immutable triggers). Tests that check audit rows query by
a unique test_user_id to avoid collision with production rows.
"""

import uuid
from datetime import datetime, timedelta

import pytest

from app.auth.models import User, UserRole, Session as DBSession
from app.auth.service import AuthService
from app.database import SessionLocal


@pytest.fixture(scope="session")
def db():
    """
    Session-scoped SQLAlchemy session against the live PostgreSQL database.
    Use 'db' fixtures for integration tests that need real persistence.
    """
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def test_user(db):
    """
    Create a fresh treating-clinician test user for each test, then delete it.
    The user gets a unique ID so tests are fully isolated.
    """
    uid = str(uuid.uuid4())
    user = User(
        user_id=uid,
        username=f"pytest_{uid[:8]}",
        password_hash=AuthService.hash_password("test_password"),
        role=UserRole.TREATING_CLINICIAN,
        department="testdept",
        is_active=True,
    )
    db.add(user)
    db.commit()
    yield user
    # Teardown: delete sessions first (FK constraint), then user
    db.query(DBSession).filter_by(user_id=uid).delete()
    db.query(User).filter_by(user_id=uid).delete()
    db.commit()


@pytest.fixture
def test_nontreating_user(db):
    """Non-treating clinician variant of test_user."""
    uid = str(uuid.uuid4())
    user = User(
        user_id=uid,
        username=f"pytest_nt_{uid[:8]}",
        password_hash=AuthService.hash_password("test_password"),
        role=UserRole.NON_TREATING_CLINICIAN,
        department="research",
        is_active=True,
    )
    db.add(user)
    db.commit()
    yield user
    db.query(DBSession).filter_by(user_id=uid).delete()
    db.query(User).filter_by(user_id=uid).delete()
    db.commit()


@pytest.fixture
def test_admin_user(db):
    """Administrator variant of test_user."""
    uid = str(uuid.uuid4())
    user = User(
        user_id=uid,
        username=f"pytest_adm_{uid[:8]}",
        password_hash=AuthService.hash_password("test_password"),
        role=UserRole.ADMINISTRATOR,
        department=None,
        is_active=True,
    )
    db.add(user)
    db.commit()
    yield user
    db.query(DBSession).filter_by(user_id=uid).delete()
    db.query(User).filter_by(user_id=uid).delete()
    db.commit()


# ---------------------------------------------------------------------------
# Reusable PHI test data
# ---------------------------------------------------------------------------

SAMPLE_TEXT_WITH_PHI = (
    "Patient: Emily Moore\n"
    "DOB: 1972-03-14\n"
    "MRN: MRN100003\n"
    "Diagnosis: Asthma (ICD: J45)\n"
    "Prescribing physician: Dr. David Thompson\n"
    "Date: 2025-04-22"
)

PHI_SPANS_PERSON = [{"type": "PERSON", "start": 9, "end": 20, "confidence": 0.85}]
PHI_SPANS_JSON = '[{"type": "PERSON", "start": 9, "end": 20, "confidence": 0.85}]'
