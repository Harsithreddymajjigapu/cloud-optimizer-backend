from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
import datetime

# ==========================================
# 1. THE USERS TABLE
# ==========================================
class User(Base):
    __tablename__ = "users"  # This is the actual name PostgreSQL will use

    # The Columns
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    department = Column(String)

    resources = relationship("CloudResource", back_populates="owner")


# ==========================================
# 2. THE SERVERS TABLE (Cloud Resources)
# ==========================================
class CloudResource(Base):
    __tablename__ = "cloud_resources"

    # The Columns
    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(String, unique=True, index=True) # e.g., i-1234567890abcdef0
    resource_type = Column(String) # e.g., EC2, RDS
    allocated_cpu_cores = Column(Integer)
    average_cpu_usage_percent = Column(Float)
    cost_per_hour = Column(Float)
    
    # The Link Back to the User (Foreign Key)
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="resources")


# ==========================================
# 3. THE AI ALERTS TABLE
# ==========================================
class OptimizationAlert(Base):
    __tablename__ = "optimization_alerts"

    # The Columns
    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(Integer, ForeignKey("cloud_resources.id"))
    ai_recommendation = Column(String) # e.g., "Downsize to t3.micro"
    estimated_monthly_savings = Column(Float)
    cli_command_to_fix = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)