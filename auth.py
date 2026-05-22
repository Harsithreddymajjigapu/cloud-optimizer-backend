from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from pydantic import BaseModel
import os
import models
from database import get_db
import logging

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# ──────────────────────────────────────────
# SETUP
# ──────────────────────────────────────────

# bcrypt for hashing passwords
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# tells FastAPI where the login endpoint is
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ──────────────────────────────────────────
# SCHEMAS
# ──────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    department: str | None = None


# ──────────────────────────────────────────
# HELPER FUNCTIONS
# ──────────────────────────────────────────

def hash_password(password: str) -> str:
    """Convert plain password to hashed version"""
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    """Check if plain password matches hashed password"""
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    """Create a JWT token with expiry"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> models.User:
    """Decode JWT token and return the current logged in user"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception

    return user


# ──────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    try:
        existing = db.query(models.User).filter(
            models.User.email == request.email
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

        hashed = hash_password(request.password)
        user = models.User(
            email=request.email,
            hashed_password=hashed,
            department=request.department
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        logger.info(f"New user registered: {request.email}")
        return {"message": "User registered successfully", "email": user.email}

    except HTTPException:
        raise

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"DB error during registration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error during registration"
        )


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(
        models.User.email == form_data.username
    ).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(data={"sub": user.email})
    logger.info(f"User logged in: {user.email}")

    return {"access_token": token, "token_type": "bearer"}