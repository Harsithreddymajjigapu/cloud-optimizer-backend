from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# --- HARDCODED URL FOR DOCKER ---
# Bypassing os.getenv entirely to force the connection to the 'db' container
SQLALCHEMY_DATABASE_URL = "postgresql://postgres:huhuhu%40123@db:5432/cloud_db"

engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()