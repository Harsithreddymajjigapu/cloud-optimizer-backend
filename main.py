from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import models
import schemas
from database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Cloud Optimizer API")


@app.post("/users/", response_model=schemas.UserResponse)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    
    existing_user = db.query(models.User).filter(models.User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = models.User(email=user.email, department=user.department)
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user

@app.get("/users/", response_model=List[schemas.UserResponse])
def get_all_users(db: Session = Depends(get_db)):
    
    return db.query(models.User).all()


@app.post("/servers/", response_model=schemas.CloudResourceResponse)
def create_server(server: schemas.CloudResourceCreate, db: Session = Depends(get_db)):
    
    owner = db.query(models.User).filter(models.User.id == server.owner_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="User not found! Cannot assign a server to nobody.")
    
    new_server = models.CloudResource(**server.model_dump())
    
    db.add(new_server)
    db.commit()
    db.refresh(new_server)
    
    return new_server
