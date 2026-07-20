from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime

# Token Schemas
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

# Permission Schemas
class PermissionBase(BaseModel):
    name: str
    code: str
    description: Optional[str] = None

class PermissionCreate(PermissionBase):
    pass

class PermissionResponse(PermissionBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# Organisation Schemas
class OrganisationBase(BaseModel):
    name: str
    slug: str
    industry: Optional[str] = None
    initials: Optional[str] = None
    color: Optional[str] = "#C8B6FF"
    note: Optional[str] = None

class OrganisationCreate(OrganisationBase):
    pass

class OrganisationResponse(OrganisationBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# Product Schemas
class ProductBase(BaseModel):
    name: str
    code: str
    description: Optional[str] = None
    status: Optional[str] = "Active"
    organisation_id: Optional[int] = None

class ProductCreate(ProductBase):
    pass

class ProductResponse(ProductBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# Workspace Schemas
class WorkspaceBase(BaseModel):
    name: str
    slug: Optional[str] = None
    icon: Optional[str] = "grid"
    description: Optional[str] = None
    status: Optional[str] = "Active"
    organisation_id: Optional[int] = None
    product_id: Optional[int] = None

class WorkspaceCreate(WorkspaceBase):
    pass

class WorkspaceResponse(WorkspaceBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# Role Schemas
class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None
    organisation_id: Optional[int] = None

class RoleCreate(RoleBase):
    pass

class RoleResponse(RoleBase):
    id: int
    created_at: datetime
    permissions: List[PermissionResponse] = []
    
    class Config:
        from_attributes = True

# User Schemas
class UserBase(BaseModel):
    email: EmailStr
    name: str
    status: Optional[str] = "Active"
    organisation_id: Optional[int] = None

class UserCreate(UserBase):
    password: str
    role_name: Optional[str] = "Admin"
    organisation_id: Optional[int] = None

class UserUpdate(BaseModel):
    name: Optional[str] = None
    role_id: Optional[int] = None
    organisation_id: Optional[int] = None
    status: Optional[str] = None

class UserResponse(UserBase):
    id: int
    role_id: Optional[int] = None
    role: Optional[RoleBase] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

# Dashboard Stats Schemas
class StatItem(BaseModel):
    l: str  # Label
    v: str  # Value
    d: str  # Description

class DashboardStatsResponse(BaseModel):
    stats: List[StatItem]

