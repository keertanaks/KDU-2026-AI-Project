"""Seed one test user per role into PostgreSQL."""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

from app.database import SessionLocal
from app.auth.models import User, UserRole
from app.auth.service import AuthService

SEED_USERS = [
    {
        "username": "dr_smith",
        "password": "test_pass_treating",
        "role": UserRole.TREATING_CLINICIAN,
        "department": "cardiology",
    },
    {
        "username": "dr_jones",
        "password": "test_pass_nontreating",
        "role": UserRole.NON_TREATING_CLINICIAN,
        "department": "research",
    },
    {
        "username": "admin_user",
        "password": "test_pass_admin",
        "role": UserRole.ADMINISTRATOR,
        "department": None,
    },
]


def seed():
    db = SessionLocal()
    created = 0
    try:
        for u in SEED_USERS:
            existing = db.query(User).filter_by(username=u["username"]).first()
            if existing:
                print(f"  User '{u['username']}' already exists — skipping.")
                continue
            user = User(
                user_id=str(uuid.uuid4()),
                username=u["username"],
                password_hash=AuthService.hash_password(u["password"]),
                role=u["role"],
                department=u["department"],
                is_active=True,
            )
            db.add(user)
            created += 1
        db.commit()
        print(f"Seeded {created} user(s).")
        # Print summary
        all_users = db.query(User).all()
        for u in all_users:
            print(f"  {u.username:20s}  role={u.role.value}  dept={u.department}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
