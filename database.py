import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# The fallback is what you get when DATABASE_URL is unset, so it has to be
# right. The previous one named a database that docker-compose never creates
# (cloud_optimizer_db, not cloud_db), used a truncated password, and omitted the
# driver.
#
# That last part matters: SQLAlchemy 2.1 changed the default driver for a bare
# 'postgresql://' from psycopg2 to psycopg3, which is not in requirements.txt.
# Naming the driver explicitly means a new SQLAlchemy release cannot silently
# switch it again.
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:huhuhu%40123@db:5432/cloud_db",
)

engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()