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

class CloudResourceResponse(BaseModel):
    id: int
    owner_id: int
    resource_id: str
    resource_type: str
    # Unknown until Azure Monitor reports metrics and pricing is resolved,
    # so these are nullable on the way out while staying required on create.
    allocated_cpu_cores: Optional[int] = None
    average_cpu_usage_percent: Optional[float] = None
    cost_per_hour: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)

class OptimizationAlertBase(BaseModel):
    ai_recommendation: str
    estimated_monthly_savings: Optional[float] = None
    cli_command_to_fix: Optional[str] = None

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
    subscription_id: str

    model_config = ConfigDict(from_attributes=True)


class CloudAccountUpdate(BaseModel):
    
    company_name: Optional[str] = None
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    subscription_id: Optional[str] = None


class CloudAccountResponse(BaseModel):

    id: int
    company_name: str
    tenant_id: str
    client_id: str
    subscription_id: str

    model_config = ConfigDict(from_attributes=True)