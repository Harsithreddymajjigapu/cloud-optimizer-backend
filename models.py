from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
import datetime

class User(Base):
    __tablename__ = "users"  
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    department = Column(String)

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