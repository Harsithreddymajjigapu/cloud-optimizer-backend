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

    # resource_id was globally unique, which made the product single-tenant by
    # accident: if two users linked the same Azure subscription, only the first
    # could ever own a row for a given VM. The second user's sync silently
    # updated the first user's records and created none of their own.
    #
    # The same VM seen by two users is two rows, one each.
    __table_args__ = (
        UniqueConstraint("owner_id", "resource_id", name="uq_owner_resource"),
    )

    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(String, index=True, nullable=False)
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
    # datetime.utcnow is deprecated in Python 3.12 (it returns a naive datetime
    # that claims to be UTC) and is the source of the warnings in every test run.
    created_at = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

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