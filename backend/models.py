from sqlalchemy import Table, Column, Integer, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from backend.database import Base

# Association table for Role <-> Permission (Many-to-Many)
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)
)

class Organisation(Base):
    __tablename__ = "organisations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), unique=True, nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    industry = Column(String(150), nullable=True)
    initials = Column(String(10), nullable=True)
    color = Column(String(50), default="#C8B6FF")
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    products = relationship("Product", back_populates="organisation", cascade="all, delete-orphan")
    workspaces = relationship("Workspace", back_populates="organisation", cascade="all, delete-orphan")
    roles = relationship("Role", back_populates="organisation", cascade="all, delete-orphan")
    users = relationship("User", back_populates="organisation")

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    organisation_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)
    status = Column(String(50), default="Active")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    organisation = relationship("Organisation", back_populates="products")
    workspaces = relationship("Workspace", back_populates="product")

class Workspace(Base):
    __tablename__ = "workspaces"
    
    id = Column(Integer, primary_key=True, index=True)
    organisation_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(150), nullable=False)
    slug = Column(String(100), nullable=True)
    icon = Column(String(100), default="grid")
    description = Column(String(255), nullable=True)
    status = Column(String(50), default="Active")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    organisation = relationship("Organisation", back_populates="workspaces")
    product = relationship("Product", back_populates="workspaces")

class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint('organisation_id', 'name', name='uq_roles_org_name'),)
    
    id = Column(Integer, primary_key=True, index=True)
    organisation_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    organisation = relationship("Organisation", back_populates="roles")
    users = relationship("User", back_populates="role")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(150), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="SET NULL"), nullable=True, index=True)
    organisation_id = Column(Integer, ForeignKey("organisations.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(50), default="Active")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    role = relationship("Role", back_populates="users")
    organisation = relationship("Organisation", back_populates="users")

class Permission(Base):
    __tablename__ = "permissions"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    code = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")

