import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session as DBSession
from app.auth.models import User, Session, UserRole
import bcrypt


class AuthService:
    @staticmethod
    def hash_password(password: str) -> bytes:
        """Bcrypt hash."""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))

    @staticmethod
    def verify_password(password: str, password_hash: bytes) -> bool:
        """Verify bcrypt hash."""
        return bcrypt.checkpw(password.encode("utf-8"), password_hash)

    @staticmethod
    def create_session(db: DBSession, user_id: str, role: UserRole) -> str:
        """Create server-side session."""
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            user_id=user_id,
            role=role,
            expires_at=datetime.utcnow() + timedelta(hours=8),
        )
        db.add(session)
        db.commit()
        return session_id

    @staticmethod
    def validate_session(db: DBSession, session_id: str) -> dict | None:
        """Validate session."""
        session = (
            db.query(Session)
            .filter(
                Session.session_id == session_id,
                Session.is_valid == True,
                Session.expires_at > datetime.utcnow(),
            )
            .first()
        )

        if not session:
            return None

        return {
            "user_id": session.user_id,
            "role": session.role,
            "session_id": session_id,
        }

    @staticmethod
    def revoke_session(db: DBSession, session_id: str):
        """Revoke session on logout."""
        session = db.query(Session).filter_by(session_id=session_id).first()
        if session:
            session.is_valid = False
            db.commit()
