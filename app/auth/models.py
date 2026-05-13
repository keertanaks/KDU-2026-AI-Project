from sqlalchemy import Column, String, Integer, DateTime, Boolean, Enum, LargeBinary
from sqlalchemy.orm import declarative_base
from datetime import datetime
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    TREATING_CLINICIAN = "treating_clinician"
    NON_TREATING_CLINICIAN = "non_treating_clinician"
    ADMINISTRATOR = "administrator"


class User(Base):
    __tablename__ = "users"

    user_id = Column(String(36), primary_key=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(LargeBinary, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    department = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    role = Column(Enum(UserRole), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    is_valid = Column(Boolean, default=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    audit_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    role = Column(Enum(UserRole), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    query_hash = Column(String(64), nullable=False)
    document_ids_returned = Column(String(4096), nullable=True)
    masking_applied = Column(String(255), nullable=True)
    result_count = Column(Integer, default=0)
    latency_ms = Column(Integer, nullable=True)
