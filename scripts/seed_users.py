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
        "username": "research_analyst",
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
        old_nontreating = db.query(User).filter_by(username="dr_jones").first()
        existing_research = db.query(User).filter_by(username="research_analyst").first()
        if existing_research:
            existing_research.password_hash = AuthService.hash_password("test_pass_nontreating")
            existing_research.role = UserRole.NON_TREATING_CLINICIAN
            existing_research.department = "research"
            existing_research.is_active = True
            if old_nontreating and old_nontreating.user_id != existing_research.user_id:
                old_nontreating.username = f"dr_jones_legacy_{old_nontreating.user_id[:8]}"
                old_nontreating.is_active = False
                print("  Archived old user 'dr_jones'.")
        elif old_nontreating:
            old_nontreating.username = "research_analyst"
            old_nontreating.password_hash = AuthService.hash_password("test_pass_nontreating")
            old_nontreating.role = UserRole.NON_TREATING_CLINICIAN
            old_nontreating.department = "research"
            old_nontreating.is_active = True
            print("  Renamed user 'dr_jones' to 'research_analyst'.")
        db.flush()

        for u in SEED_USERS:
            existing = db.query(User).filter_by(username=u["username"]).first()
            if existing:
                existing.password_hash = AuthService.hash_password(u["password"])
                existing.role = u["role"]
                existing.department = u["department"]
                existing.is_active = True
                print(f"  User '{u['username']}' already exists - updated.")
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
