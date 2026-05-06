import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

# 1. Load the passwords from the .env file
load_dotenv()
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# 2. Create the Engine (The core tunnel to the database)
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# 3. Create a Session Factory (This hands out temporary connections when needed)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. The Base Class (All our tables will inherit from this)
Base = declarative_base()

# 5. Dependency injection: Safely open and close the tunnel for every request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()