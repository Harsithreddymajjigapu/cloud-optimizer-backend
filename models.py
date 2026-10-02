from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base
import datetime

class User(Base):
    __tablename__ = "users"  
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    department = Column(String)
    hashed_password = Column(String, nullable=True)
    resources = relationship("CloudResource", back_populates="owner")

class CloudResource(Base):
    __tablename__ = "cloud_resources"

    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(String, unique=True, index=True) 
    resource_type = Column(String)
    allocated_cpu_cores = Column(Integer)
    average_cpu_usage_percent = Column(Float)
    cost_per_hour = Column(Float)
    
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="resources")

class OptimizationAlert(Base):
    __tablename__ = "optimization_alerts"

    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(Integer, ForeignKey("cloud_resources.id"))
    ai_recommendation = Column(String) 
    estimated_monthly_savings = Column(Float)
    cli_command_to_fix = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)    

class CloudAccount(Base):
    __tablename__ = "cloud_accounts"

    # A tenant is a whole company and a client_id is one app registration in it,
    # so neither is globally unique to a single user of this product — two
    # colleagues must both be able to link. What must not repeat is the same
    # person linking the same subscription twice.
    __table_args__ = (
        UniqueConstraint("user_id", "subscription_id", name="uq_user_subscription"),
    )

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String, index=True)
    tenant_id = Column(String, index=True, nullable=False)
    client_id = Column(String, nullable=False)
    client_secret = Column(String, nullable=False)
    subscription_id = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", backref="cloud_accounts")