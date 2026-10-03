from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List
import models
import schemas
from database import engine, get_db
from tasks import analyze_server_efficiency
from auth import router as auth_router, get_current_user
from tasks import fetch_azure_vms_for_user
from azure_client import verify_azure_credentials, AzureCredentialError
from crypto import encrypt_secret, decrypt_secret
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cloud Optimizer API")

app.include_router(auth_router)

models.Base.metadata.create_all(bind=engine)


@app.post("/users/", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    user: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
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
def get_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    try:
        users = db.query(models.User).all()
        return users

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching users"
        )


@app.post("/api/v1/accounts/link-azure", status_code=status.HTTP_201_CREATED)
def link_azure_account(
    account_data: schemas.CloudAccountCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Link an Azure subscription to the logged-in user.

    The credentials are proved against Azure before anything is written, and the
    client secret is encrypted at rest.
    """
    try:
        # Scoped to this user and this subscription. Two colleagues sharing a
        # tenant can both link; the same person cannot link one twice.
        existing_account = db.query(models.CloudAccount).filter(
            models.CloudAccount.user_id == current_user.id,
            models.CloudAccount.subscription_id == account_data.subscription_id
        ).first()

        if existing_account:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already linked this subscription."
            )

        # Fail now, with a message the user can act on, rather than silently
        # hours later inside a background worker.
        try:
            verify_azure_credentials(
                account_data.tenant_id,
                account_data.client_id,
                account_data.client_secret,
                account_data.subscription_id,
            )
        except AzureCredentialError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=exc.message
            )

        new_account = models.CloudAccount(
            user_id=current_user.id,
            company_name=account_data.company_name,
            tenant_id=account_data.tenant_id,
            client_id=account_data.client_id,
            client_secret=encrypt_secret(account_data.client_secret),
            subscription_id=account_data.subscription_id
        )

        db.add(new_account)
        db.commit()
        db.refresh(new_account)

        # Log the subscription, never the credentials.
        logger.info(
            "User %s linked subscription %s",
            current_user.email, new_account.subscription_id
        )

        return {
            "status": "success",
            "message": f"Azure account for {new_account.company_name} successfully linked.",
            "account_id": new_account.id
        }

    except HTTPException:
        raise

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error while linking Azure account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while saving cloud credentials"
        )


@app.get("/api/v1/accounts", response_model=list[schemas.CloudAccountResponse])
def list_linked_accounts(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """List this user's linked subscriptions. Secrets are never returned."""
    return db.query(models.CloudAccount).filter(
        models.CloudAccount.user_id == current_user.id
    ).all()


@app.put("/api/v1/accounts/{account_id}", response_model=schemas.CloudAccountResponse)
def update_azure_account(
    account_id: int,
    updates: schemas.CloudAccountUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Update a linked account — most often rotating a client secret that Azure
    has expired. Without this, an expired secret meant a permanently broken
    sync with no way to recover.
    """
    account = db.query(models.CloudAccount).filter(
        models.CloudAccount.id == account_id,
        models.CloudAccount.user_id == current_user.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Linked account not found"
        )

    # Verify the combination that will exist after the update, not just the
    # fields supplied — a new secret has to work against the existing tenant.
    merged = {
        "tenant_id": updates.tenant_id or account.tenant_id,
        "client_id": updates.client_id or account.client_id,
        "subscription_id": updates.subscription_id or account.subscription_id,
    }
    plain_secret = updates.client_secret or decrypt_secret(account.client_secret)

    try:
        verify_azure_credentials(
            merged["tenant_id"],
            merged["client_id"],
            plain_secret,
            merged["subscription_id"],
        )
    except AzureCredentialError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)

    try:
        if updates.company_name is not None:
            account.company_name = updates.company_name
        account.tenant_id = merged["tenant_id"]
        account.client_id = merged["client_id"]
        account.subscription_id = merged["subscription_id"]
        if updates.client_secret is not None:
            account.client_secret = encrypt_secret(updates.client_secret)

        db.commit()
        db.refresh(account)

        logger.info("User %s updated linked account %s", current_user.email, account_id)
        return account

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error while updating Azure account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while updating cloud credentials"
        )


@app.delete("/api/v1/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_azure_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Unlink a subscription and discard its stored credentials.

    Without this, a customer who stopped using the product had no way to make
    us stop holding live credentials to their cloud.
    """
    account = db.query(models.CloudAccount).filter(
        models.CloudAccount.id == account_id,
        models.CloudAccount.user_id == current_user.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Linked account not found"
        )

    try:
        db.delete(account)
        db.commit()
        logger.info("User %s unlinked account %s", current_user.email, account_id)

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error while unlinking Azure account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while unlinking the account"
        )

@app.post("/api/v1/accounts/sync", status_code=status.HTTP_202_ACCEPTED)
def trigger_azure_sync(
    current_user: models.User = Depends(get_current_user)
):
    """
    Triggers the Celery background worker to log into Azure and fetch VMs.
    """
    fetch_azure_vms_for_user.delay(current_user.id)
    
    return {"message": "Azure sync started in the background!"}


@app.get("/api/v1/resources", response_model=list[schemas.CloudResourceResponse])
def get_user_resources(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Returns all Azure servers saved in the database for the logged-in user.
    """
    try:
        servers = db.query(models.CloudResource).filter(
            models.CloudResource.owner_id == current_user.id
        ).all()
        
        return servers

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching resources: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching resources"
        )


@app.post("/servers/", response_model=schemas.CloudResourceResponse, status_code=status.HTTP_201_CREATED)
def create_server(
    resource: schemas.CloudResourceCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
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
    current_user: models.User = Depends(get_current_user)
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
    current_user: models.User = Depends(get_current_user)
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
    current_user: models.User = Depends(get_current_user)
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

@app.get("/api/v1/alerts")
def get_ai_recommendations(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fetches all Gemini AI optimization alerts for the user's servers."""
    
    alerts = db.query(models.OptimizationAlert)\
        .join(models.CloudResource)\
        .filter(models.CloudResource.owner_id == user.id)\
        .all()
        
    return alerts