from pydantic import BaseModel, EmailStr, ConfigDict
from datetime import datetime
from typing import Optional

class UserBase(BaseModel):
    email: EmailStr 
    department: str

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
        
class CloudResourceBase(BaseModel):
    resource_id: str
    resource_type: str
    allocated_cpu_cores: int
    average_cpu_usage_percent: float
    cost_per_hour: float

class CloudResourceCreate(CloudResourceBase):
    owner_id: int 

class CloudResourceResponse(CloudResourceBase):
    id: int
    owner_id: int

    model_config = ConfigDict(from_attributes=True)

class OptimizationAlertBase(BaseModel):
    ai_recommendation: str
    estimated_monthly_savings: float
    cli_command_to_fix: str

class OptimizationAlertCreate(OptimizationAlertBase):
    resource_id: int

class OptimizationAlertResponse(OptimizationAlertBase):
    id: int
    resource_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
    
class CloudAccountCreate(BaseModel):
    company_name: str
    tenant_id: str
    client_id: str
    client_secret: str

    class Config:
        from_attributes = True