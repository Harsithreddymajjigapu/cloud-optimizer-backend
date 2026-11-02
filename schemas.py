from pydantic import BaseModel, EmailStr, ConfigDict, Field
from datetime import datetime
from typing import Optional

class UserBase(BaseModel):
    email: EmailStr
    department: str | None = None

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
    pass

class CloudResourceResponse(BaseModel):
    id: int
    owner_id: int
    resource_id: str
    resource_type: str
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
    """
    Every field optional — send only what is changing.

    min_length=1 matters more than it looks. An empty string used to mean two
    different things in the same endpoint: the verification step read it as
    "unchanged" and checked the OLD secret (which passed), while the save step
    read it as "a value was supplied" and stored the empty string. The result
    was a 200 response that wiped the stored credential, after which every sync
    failed to authenticate — silently.

    Rejecting "" here means the two steps can no longer disagree.
    """

    company_name: Optional[str] = Field(default=None, min_length=1)
    tenant_id: Optional[str] = Field(default=None, min_length=1)
    client_id: Optional[str] = Field(default=None, min_length=1)
    client_secret: Optional[str] = Field(default=None, min_length=1)
    subscription_id: Optional[str] = Field(default=None, min_length=1)


class CloudAccountResponse(BaseModel):

    id: int
    company_name: str
    tenant_id: str
    client_id: str
    subscription_id: str

    model_config = ConfigDict(from_attributes=True)