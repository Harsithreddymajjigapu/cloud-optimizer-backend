from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import models
import schemas
from database import engine, get_db
from worker import analyze_server_efficiency
from auth import router as auth_router, get_current_user
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cloud Optimizer API")



app.include_router(auth_router)


models.Base.metadata.create_all(bind=engine)



@app.post("/users/", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    try:
        existing_user = db.query(models.User).filter(
            models.User.email == user.email
        ).first()

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email '{user.email}' is already registered"
            )

        db_user = models.User(**user.model_dump())
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        logger.info(f"New user created: {user.email}")
        return db_user

    except HTTPException:
        raise

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error while creating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while creating user"
        )


@app.get("/users/", response_model=list[schemas.UserResponse])
def get_users(db: Session = Depends(get_db)):
    try:
        users = db.query(models.User).all()
        return users

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching users"
        )


@app.post("/servers/", response_model=schemas.CloudResourceResponse, status_code=status.HTTP_201_CREATED)
def create_server(
    resource: schemas.CloudResourceCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)  # ← auth protection
):
    try:
        user = db.query(models.User).filter(
            models.User.id == resource.owner_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with id {resource.owner_id} not found"
            )

        existing = db.query(models.CloudResource).filter(
            models.CloudResource.resource_id == resource.resource_id
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Resource '{resource.resource_id}' is already registered"
            )

        db_resource = models.CloudResource(**resource.model_dump())
        db.add(db_resource)
        db.commit()
        db.refresh(db_resource)

        try:
            analyze_server_efficiency.delay(
                db_resource.id,
                db_resource.average_cpu_usage_percent,
                db_resource.resource_id,
                db_resource.resource_type,
                db_resource.cost_per_hour
            )
            logger.info(f"Analysis task queued for: {db_resource.resource_id}")

        except Exception as e:
            logger.warning(f"Could not queue task (Redis may be down): {e}")

        return db_resource

    except HTTPException:
        raise

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error while creating server: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while creating server"
        )


@app.get("/servers/", response_model=list[schemas.CloudResourceResponse])
def get_servers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)  # ← auth protection
):
    try:
        servers = db.query(models.CloudResource).all()
        return servers

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching servers: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching servers"
        )


@app.get("/alerts/", response_model=list[schemas.OptimizationAlertResponse])
def get_alerts(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)  # ← auth protection
):
    try:
        alerts = db.query(models.OptimizationAlert).all()
        return alerts

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching alerts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching alerts"
        )


@app.get("/alerts/{resource_id}", response_model=list[schemas.OptimizationAlertResponse])
def get_alerts_for_resource(
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)  # ← auth protection
):
    try:
        resource = db.query(models.CloudResource).filter(
            models.CloudResource.id == resource_id
        ).first()

        if not resource:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Resource with id {resource_id} not found"
            )

        alerts = db.query(models.OptimizationAlert).filter(
            models.OptimizationAlert.resource_id == resource_id
        ).all()

        return alerts

    except HTTPException:
        raise

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching alerts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred"
        )