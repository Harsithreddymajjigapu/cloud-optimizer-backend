import os
import pathlib

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "HjjFcNC_OtSMMTiAgFUonXp-HxXgNecLF7B5xyM-_gE=")

if os.environ["DATABASE_URL"].startswith("sqlite"):
    pathlib.Path("test.db").unlink(missing_ok=True)


def _assert_safe_to_wipe(engine):
    """
    Refuse to drop tables unless this is obviously a test database.

    The reset below is destructive. DATABASE_URL in .env points at cloud_db,
    the real local database — running pytest with that loaded (inside the web
    container, say) would delete every linked account and alert. A test suite
    should never be one stray environment variable away from that.
    """
    name = (engine.url.database or "")
    if "test" in name.lower() or name.endswith(".db"):
        return
    raise RuntimeError(
        f"Refusing to reset {name!r}: the test suite drops every table and this "
        "does not look like a test database. Point DATABASE_URL at one whose "
        "name contains 'test'."
    )


@pytest.fixture(scope="session", autouse=True)
def seed_users():
    """
    Create the two users the suite refers to by id.

    Tests hardcode owner_id 1 and 2 and never created those rows. SQLite ignores
    foreign keys by default, so the inserts were accepted and nobody noticed —
    until CI ran the same tests against Postgres, which rejected them.

    Foreign keys are now enforced on SQLite too, so the rows have to be real.
    """
    from sqlalchemy import text

    from database import SessionLocal, engine, Base
    import models

    _assert_safe_to_wipe(engine)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        for user_id, email in (
            (1, "test_admin@gmail.com"),
            (2, "intruder@example.com"),
        ):
            if db.get(models.User, user_id) is None:
                db.add(models.User(
                    id=user_id,
                    email=email,
                    department="Engineering",
                    hashed_password="not-a-real-hash",
                ))
        db.commit()
        if engine.dialect.name == "postgresql":
            db.execute(text(
                "SELECT setval(pg_get_serial_sequence('users', 'id'), "
                "COALESCE((SELECT MAX(id) FROM users), 1))"
            ))
            db.commit()
    finally:
        db.close()