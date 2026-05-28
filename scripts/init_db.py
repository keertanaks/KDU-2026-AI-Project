"""Initialize PostgreSQL database — create all tables."""
import sys
import os
from pathlib import Path

# Load .env before any app imports
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from app.config import DATABASE_URL
from app.auth.models import Base


def init_db():
    print(f"Connecting to: {DATABASE_URL}")
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("✅ Database connection OK")

    Base.metadata.create_all(bind=engine)
    print("✅ All tables created:")

    for table in Base.metadata.sorted_tables:
        print(f"   - {table.name}")


if __name__ == "__main__":
    init_db()
