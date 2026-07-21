import os
import logging
from fastapi import FastAPI, Depends, HTTPException, status, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional

from backend.database import engine, Base, SessionLocal, get_db
from backend.models import User, Role, Permission, Organisation, Product, Workspace, Feedback, Notification
from backend.schemas import (
    LoginRequest, Token, UserResponse, UserCreate, UserUpdate,
    RoleResponse, RoleCreate, RoleUpdate, PermissionResponse, DashboardStatsResponse, StatItem,
    OrganisationResponse, OrganisationCreate, OrganisationUpdate,
    ProductResponse, ProductCreate, ProductUpdate,
    WorkspaceResponse, WorkspaceCreate, WorkspaceUpdate, ApiCatalogResponse, ApiCatalogItem,
    CliCatalogResponse, CliCommandItem, FeedbackCreate, FeedbackResponse, FeedbackUpdate,
    NotificationCreate, NotificationResponse, NotificationUpdate,
    AiChatRequest, AiChatResponse
)
import requests as _http
from backend.auth import (
    verify_password, get_password_hash, create_access_token, get_current_user
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main_app")

# Create database tables (no-op if they already exist)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Z9S-AI HQ Portal API",
    description="Backend API endpoints for managing the HQ workspace, Config (Users & Roles), and User accounts",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database seeding on startup
@app.on_event("startup")
def seed_database():
    db = SessionLocal()
    try:
        # Check if default organisation exists
        org = db.query(Organisation).filter(Organisation.slug == "z9s-ai").first()
        if not org:
            logger.info("Seeding default organisation Z9S-AI...")
            org = Organisation(
                name="Z9S-AI",
                slug="z9s-ai",
                industry="AI Implementation",
                initials="Z",
                color="#C8B6FF",
                note="Z9S-AI operating system."
            )
            db.add(org)
            db.commit()
            db.refresh(org)
            logger.info("Default organisation Z9S-AI seeded.")

        # Check if default product exists
        product = db.query(Product).filter(Product.code == "hq").first()
        if not product:
            logger.info("Seeding default product HQ Portal...")
            product = Product(
                organisation_id=org.id,
                name="HQ Portal",
                code="hq",
                description="Core HQ platform product",
                status="Active"
            )
            db.add(product)
            db.commit()
            db.refresh(product)
            logger.info("Default product HQ Portal seeded.")

        # Check if default workspaces exist
        if db.query(Workspace).filter(Workspace.organisation_id == org.id).count() == 0:
            logger.info("Seeding default workspaces...")
            hq_ws = Workspace(
                organisation_id=org.id,
                product_id=product.id,
                name="HQ",
                slug="hq",
                icon="grid",
                description="HQ main workspace",
                status="Active"
            )
            config_ws = Workspace(
                organisation_id=org.id,
                product_id=product.id,
                name="Config",
                slug="config",
                icon="sliders",
                description="Configuration workspace",
                status="Active"
            )
            users_ws = Workspace(
                organisation_id=org.id,
                product_id=product.id,
                name="Users",
                slug="users",
                icon="users",
                description="User management workspace",
                status="Active"
            )
            db.add_all([hq_ws, config_ws, users_ws])
            db.commit()
            logger.info("Default workspaces seeded.")

        # Check if roles are seeded
        if db.query(Role).filter(Role.organisation_id == org.id).count() == 0:
            logger.info("Seeding default roles...")
            admin_role = Role(
                organisation_id=org.id,
                name="Admin",
                description="Administrator with full permissions across all workspaces"
            )
            operator_role = Role(
                organisation_id=org.id,
                name="Operator",
                description="Standard operator with access to general operations"
            )
            viewer_role = Role(
                organisation_id=org.id,
                name="Viewer",
                description="Read-only access to workspaces"
            )
            db.add_all([admin_role, operator_role, viewer_role])
            db.commit()
            
            logger.info("Seeding default permissions...")
            permissions_list = [
                Permission(name="Read Users", code="users:read", description="Ability to list and view users"),
                Permission(name="Create Users", code="users:write", description="Ability to create or modify users"),
                Permission(name="Delete Users", code="users:delete", description="Ability to delete users"),
                Permission(name="Read Roles", code="roles:read", description="Ability to view roles list"),
                Permission(name="Write Roles", code="roles:write", description="Ability to create and manage roles"),
                Permission(name="Read Permissions", code="permissions:read", description="Ability to view permissions list"),
                Permission(name="Grant Permissions", code="permissions:grant", description="Ability to grant permissions to roles"),
                Permission(name="Revoke Permissions", code="permissions:revoke", description="Ability to revoke permissions from roles"),
                Permission(name="Read Dashboard", code="dashboard:read", description="Ability to view HQ dashboard metrics"),
                Permission(name="Read Organisations", code="organisations:read", description="Ability to view organisations"),
                Permission(name="Write Organisations", code="organisations:write", description="Ability to create and manage organisations"),
                Permission(name="Read Products", code="products:read", description="Ability to view products"),
                Permission(name="Write Products", code="products:write", description="Ability to create and manage products"),
                Permission(name="Read Workspaces", code="workspaces:read", description="Ability to view workspaces"),
                Permission(name="Write Workspaces", code="workspaces:write", description="Ability to create and manage workspaces")
            ]
            
            for perm in permissions_list:
                if not db.query(Permission).filter(Permission.code == perm.code).first():
                    db.add(perm)
            db.commit()
            
            # Fetch fresh objects to link
            admin_role = db.query(Role).filter(Role.name == "Admin", Role.organisation_id == org.id).first()
            all_perms = db.query(Permission).all()
            admin_role.permissions.extend(all_perms)
            db.commit()
            logger.info("Database default roles and permissions successfully linked and seeded.")
            
        # Check if default admin user is seeded
        if db.query(User).filter(User.email == "meet@dotsai.in").count() == 0:
            logger.info("Seeding default admin user meet@dotsai.in...")
            admin_role = db.query(Role).filter(Role.name == "Admin", Role.organisation_id == org.id).first()
            admin_user = User(
                email="meet@dotsai.in",
                name="Meet Deshani",
                password_hash=get_password_hash("meetdeshani123"),
                role_id=admin_role.id if admin_role else None,
                organisation_id=org.id,
                status="Active"
            )
            db.add(admin_user)
            db.commit()
            # Seed welcome notifications so the bell reflects real (DB-backed) data.
            db.add_all([
                Notification(user_id=admin_user.id, category="platform",
                    title="Welcome to Z9S-AI HQ — your operating system is ready.",
                    path="/hq/hq/dashboard", product="hq", module="HQ", tab="Dashboard"),
                Notification(user_id=admin_user.id, category="update",
                    title="Your Admin role has full access to every workspace.",
                    path="/hq/config/roles", product="hq", module="Config", tab="Roles"),
            ])
            db.commit()
            logger.info("Default Admin user 'meet@dotsai.in' successfully seeded.")
            
    except Exception as e:
        logger.error(f"Error seeding database: {e}")
    finally:
        db.close()

# ── API ROUTES ──

# Auth
@app.post("/api/auth/login", response_model=Token)
def login(login_data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == login_data.email).first()
    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": user.email})
    
    # Set HTTP-only cookie for easy frontend browser access
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=60 * 24 * 7 * 60,  # 1 week in seconds
        samesite="lax",
        secure=False  # Set to True in production with HTTPS
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"detail": "Logged out successfully"}

@app.get("/api/auth/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

# Users
@app.get("/api/users", response_model=List[UserResponse])
def list_users(
    role: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(User)
    if role:
        query = query.join(Role).filter(Role.name == role)
    return query.all()

@app.post("/api/users", response_model=UserResponse)
def create_user(
    user_data: UserCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists"
        )
        
    # Get role
    role = db.query(Role).filter(Role.name == user_data.role_name).first()
    if not role:
        # Fallback to Admin or create it
        role = db.query(Role).filter(Role.name == "Admin").first()
        
    db_user = User(
        email=user_data.email,
        name=user_data.name,
        password_hash=get_password_hash("password123"),  # default password
        role_id=role.id if role else None,
        organisation_id=user_data.organisation_id,
        status=user_data.status
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    # Real notifications: tell admins a user joined, welcome the new user.
    _notify(db, _admin_ids(db), f"New user {db_user.name} joined the platform",
            category="update", path="/hq/config/users", product="hq", module="Config", tab="Users")
    _notify(db, [db_user.id], "Welcome to Z9S-AI HQ — your account is ready.",
            category="platform", path="/hq/hq/dashboard", product="hq", module="HQ", tab="Dashboard")
    db.commit()
    return db_user

@app.patch("/api/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user_data.name is not None:
        user.name = user_data.name
    if user_data.status is not None:
        user.status = user_data.status
    if user_data.organisation_id is not None:
        user.organisation_id = user_data.organisation_id
    if user_data.role_name is not None:
        role = db.query(Role).filter(Role.name == user_data.role_name).first()
        if not role:
            raise HTTPException(status_code=400, detail=f"Role '{user_data.role_name}' not found")
        user.role_id = role.id
    db.commit()
    db.refresh(user)
    return user

@app.delete("/api/users/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    # Prevent deleting self
    if user.email == current_user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own admin account"
        )
        
    db.delete(user)
    db.commit()
    return {"detail": "User deleted successfully"}

# Organisations
@app.get("/api/organisations", response_model=List[OrganisationResponse])
def list_organisations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Organisation).all()

@app.post("/api/organisations", response_model=OrganisationResponse)
def create_organisation(
    org_data: OrganisationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    existing_org = db.query(Organisation).filter(Organisation.slug == org_data.slug).first()
    if existing_org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An organisation with this slug already exists"
        )
    db_org = Organisation(**org_data.model_dump())
    db.add(db_org)
    db.commit()
    db.refresh(db_org)
    return db_org

@app.patch("/api/organisations/{org_id}", response_model=OrganisationResponse)
def update_organisation(
    org_id: int,
    org_data: OrganisationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    org = db.query(Organisation).filter(Organisation.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    for field, value in org_data.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    db.commit()
    db.refresh(org)
    return org

@app.delete("/api/organisations/{org_id}")
def delete_organisation(
    org_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    org = db.query(Organisation).filter(Organisation.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    # Guard: don't orphan users (or nuke products/workspaces/roles) that still belong to it.
    assigned = db.query(User).filter(User.organisation_id == org_id).count()
    if assigned > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete organisation: {assigned} user(s) still belong to it. Reassign them first."
        )
    db.delete(org)
    db.commit()
    return {"detail": "Organisation deleted successfully"}

# Products
@app.get("/api/products", response_model=List[ProductResponse])
def list_products(
    organisation_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Product)
    if organisation_id:
        query = query.filter(Product.organisation_id == organisation_id)
    return query.all()

@app.post("/api/products", response_model=ProductResponse)
def create_product(
    product_data: ProductCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    existing_product = db.query(Product).filter(Product.code == product_data.code).first()
    if existing_product:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A product with this code already exists"
        )
    db_product = Product(**product_data.model_dump())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

@app.patch("/api/products/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    product_data: ProductUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for field, value in product_data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product

@app.delete("/api/products/{product_id}")
def delete_product(
    product_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()
    return {"detail": "Product deleted successfully"}

# Workspaces
@app.get("/api/workspaces", response_model=List[WorkspaceResponse])
def list_workspaces(
    organisation_id: Optional[int] = None,
    product_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Workspace)
    if organisation_id:
        query = query.filter(Workspace.organisation_id == organisation_id)
    if product_id:
        query = query.filter(Workspace.product_id == product_id)
    return query.all()

@app.post("/api/workspaces", response_model=WorkspaceResponse)
def create_workspace(
    workspace_data: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_workspace = Workspace(**workspace_data.model_dump())
    db.add(db_workspace)
    db.commit()
    db.refresh(db_workspace)
    return db_workspace

@app.patch("/api/workspaces/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: int,
    workspace_data: WorkspaceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    for field, value in workspace_data.model_dump(exclude_unset=True).items():
        setattr(workspace, field, value)
    db.commit()
    db.refresh(workspace)
    return workspace

@app.delete("/api/workspaces/{workspace_id}")
def delete_workspace(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    db.delete(workspace)
    db.commit()
    return {"detail": "Workspace deleted successfully"}

# Roles
@app.get("/api/roles", response_model=List[RoleResponse])
def list_roles(
    organisation_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Role)
    if organisation_id:
        query = query.filter(Role.organisation_id == organisation_id)
    return query.all()

@app.post("/api/roles", response_model=RoleResponse)
def create_role(
    role_data: RoleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Check if role exists
    existing_role = db.query(Role).filter(
        Role.name == role_data.name,
        Role.organisation_id == role_data.organisation_id
    ).first()
    if existing_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A role with this name already exists in the organisation"
        )
    db_role = Role(**role_data.model_dump())
    db.add(db_role)
    db.commit()
    db.refresh(db_role)
    return db_role

@app.patch("/api/roles/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: int,
    role_data: RoleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    for field, value in role_data.model_dump(exclude_unset=True).items():
        setattr(role, field, value)
    db.commit()
    db.refresh(role)
    return role

@app.delete("/api/roles/{role_id}")
def delete_role(
    role_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    # Guard: don't orphan users by deleting a role they're still assigned to.
    assigned = db.query(User).filter(User.role_id == role_id).count()
    if assigned > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete role: {assigned} user(s) are still assigned to it. Reassign them to another role first."
        )
    db.delete(role)
    db.commit()
    return {"detail": "Role deleted successfully"}

# Permissions
@app.get("/api/permissions", response_model=List[PermissionResponse])
def list_permissions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Permission).all()

@app.post("/api/roles/{role_id}/permissions")
def grant_permission_to_role(
    role_id: int,
    permission_codes: List[str],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
        
    # Get all permissions with these codes
    perms = db.query(Permission).filter(Permission.code.in_(permission_codes)).all()
    
    # Overwrite permissions link
    role.permissions = perms
    db.commit()
    return {"detail": f"Permissions updated successfully for role {role.name}"}

# Dashboard
@app.get("/api/dashboard/stats", response_model=DashboardStatsResponse)
def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.status == "Active").count()
    total_roles = db.query(Role).count()
    total_perms = db.query(Permission).count()
    total_orgs = db.query(Organisation).count()
    total_products = db.query(Product).count()
    total_workspaces = db.query(Workspace).count()
    
    return {
        "stats": [
            StatItem(l="Total Users", v=str(total_users), d=f"↗ Active: {active_users}"),
            StatItem(l="Total Roles", v=str(total_roles), d="↘ Configured Roles"),
            StatItem(l="Total Permissions", v=str(total_perms), d="→ Auth Policies"),
            StatItem(l="Organisations", v=str(total_orgs), d="→ Active Orgs"),
            StatItem(l="Products", v=str(total_products), d="→ HQ Products"),
            StatItem(l="Workspaces", v=str(total_workspaces), d="→ Resource Segments")
        ]
    }

# Feedback
@app.post("/api/feedback", response_model=FeedbackResponse)
def create_feedback(
    fb: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    entry = Feedback(
        user_id=current_user.id,
        category=fb.category or "general",
        text=fb.text,
        path=fb.path,
        product=fb.product,
        module=fb.module,
        tab=fb.tab,
        status="Open"
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    # Real notification: alert admins that new feedback arrived.
    _notify(db, _admin_ids(db), f"New {entry.category} feedback from {current_user.email}",
            category="alert", path="/hq/config/feedback", product="hq", module="Config", tab="Feedback")
    db.commit()
    return entry

@app.get("/api/feedback", response_model=List[FeedbackResponse])
def list_feedback(
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Feedback)
    if status:
        query = query.filter(Feedback.status == status)
    return query.order_by(Feedback.created_at.desc()).all()

@app.patch("/api/feedback/{feedback_id}", response_model=FeedbackResponse)
def update_feedback(
    feedback_id: int,
    fb_data: FeedbackUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")
    for field, value in fb_data.model_dump(exclude_unset=True).items():
        setattr(fb, field, value)
    db.commit()
    db.refresh(fb)
    return fb

@app.delete("/api/feedback/{feedback_id}")
def delete_feedback(
    feedback_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")
    db.delete(fb)
    db.commit()
    return {"detail": "Feedback deleted successfully"}

# Notifications
def _admin_ids(db: Session):
    return [u.id for u in db.query(User).join(Role).filter(Role.name == "Admin").all()]

def _notify(db: Session, user_ids, title, category="update", path=None, product=None, module=None, tab=None):
    """Queue notifications for the given users. Caller commits."""
    for uid in set(user_ids):
        db.add(Notification(user_id=uid, title=title, category=category,
                            path=path, product=product, module=module, tab=tab))

@app.get("/api/notifications", response_model=List[NotificationResponse])
def list_notifications(
    unread: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread is True:
        query = query.filter(Notification.read == False)
    return query.order_by(Notification.created_at.desc()).all()

@app.post("/api/notifications", response_model=NotificationResponse)
def create_notification(
    data: NotificationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    n = Notification(
        user_id=data.user_id, title=data.title, category=data.category or "update",
        path=data.path, product=data.product, module=data.module, tab=data.tab
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n

@app.post("/api/notifications/read-all")
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    updated = db.query(Notification).filter(
        Notification.user_id == current_user.id, Notification.read == False
    ).update({"read": True})
    db.commit()
    return {"detail": f"{updated} notification(s) marked as read"}

@app.patch("/api/notifications/{notification_id}", response_model=NotificationResponse)
def update_notification(
    notification_id: int,
    data: NotificationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    n = db.query(Notification).filter(
        Notification.id == notification_id, Notification.user_id == current_user.id
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if data.read is not None:
        n.read = data.read
    db.commit()
    db.refresh(n)
    return n

@app.delete("/api/notifications/{notification_id}")
def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    n = db.query(Notification).filter(
        Notification.id == notification_id, Notification.user_id == current_user.id
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.delete(n)
    db.commit()
    return {"detail": "Notification deleted successfully"}

# AI assistant — proxies to a real LLM. Provider + key come from env, so nothing
# secret is committed, and it degrades gracefully when no key is configured.
AI_SYSTEM = (
    "You are the AI assistant embedded in the Z9S-AI HQ portal — an internal "
    "operations platform with workspaces for HQ (dashboard), Config (organisations, "
    "products, workspaces, users, roles, permissions, feedback) and Document (API and "
    "CLI references). Be concise, accurate and genuinely helpful. When the user asks "
    "about the current screen, use the page context provided."
)

def _ai_unconfigured(var: str) -> str:
    return (f"The AI assistant isn't configured yet. Add {var} (and optionally AI_MODEL) "
            f"to the server's .env and restart to enable live answers.")

@app.post("/api/ai/chat", response_model=AiChatResponse)
def ai_chat(req: AiChatRequest, current_user: User = Depends(get_current_user)):
    provider = os.getenv("AI_PROVIDER", "anthropic").strip().lower()
    system = AI_SYSTEM + (("\n\nCurrent page — " + req.context) if req.context else "")
    history = [(m.role if m.role in ("user", "assistant") else "user", m.text)
               for m in (req.history or [])]

    if provider == "openai":
        key = os.getenv("OPENAI_API_KEY")
        model = os.getenv("AI_MODEL", "gpt-4o-mini")
        if not key:
            return AiChatResponse(reply=_ai_unconfigured("OPENAI_API_KEY"), model="none", configured=False)
        try:
            msgs = [{"role": "system", "content": system}]
            msgs += [{"role": r, "content": t} for r, t in history]
            msgs.append({"role": "user", "content": req.message})
            base = os.getenv("AI_BASE_URL", "https://api.openai.com").rstrip("/")
            resp = _http.post(
                base + "/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "messages": msgs, "max_tokens": 1024}, timeout=60,
            )
            resp.raise_for_status()
            reply = resp.json()["choices"][0]["message"]["content"]
            return AiChatResponse(reply=reply, model=model, configured=True)
        except Exception as e:
            logger.error(f"OpenAI call failed: {e}")
            return AiChatResponse(reply="The AI service returned an error. Please try again.", model=model, configured=True)

    # Default provider: Anthropic (Claude).
    key = os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("AI_MODEL", "claude-3-5-sonnet-20241022")
    if not key:
        return AiChatResponse(reply=_ai_unconfigured("ANTHROPIC_API_KEY"), model="none", configured=False)
    try:
        msgs = [{"role": r, "content": t} for r, t in history]
        msgs.append({"role": "user", "content": req.message})
        base = os.getenv("AI_BASE_URL", "https://api.anthropic.com").rstrip("/")
        resp = _http.post(
            base + "/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 1024, "system": system, "messages": msgs}, timeout=60,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        reply = "".join(b.get("text", "") for b in blocks if b.get("type") == "text") or "…"
        return AiChatResponse(reply=reply, model=model, configured=True)
    except Exception as e:
        logger.error(f"Anthropic call failed: {e}")
        return AiChatResponse(reply="The AI service returned an error. Please try again.", model=model, configured=True)

# ── API CATALOG ──
# A self-documenting reference of every endpoint on the platform. Public by
# design so AI agents and CLIs can discover the full surface before authing.
# __BASE__ is swapped for the live base URL at request time.
API_CATALOG = [
    {
        "method": "POST", "path": "/api/auth/login", "auth": "Public",
        "summary": "Authenticate with email + password. Returns a JWT and sets an httpOnly access_token cookie.",
        "usage": "curl -X POST __BASE__/api/auth/login \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"email\":\"meet@dotsai.in\",\"password\":\"meetdeshani123\"}'",
        "response": "{\n  \"access_token\": \"<jwt>\",\n  \"token_type\": \"bearer\"\n}",
    },
    {
        "method": "POST", "path": "/api/auth/logout", "auth": "Public",
        "summary": "Clear the access_token session cookie.",
        "usage": "curl -X POST __BASE__/api/auth/logout",
        "response": "{ \"detail\": \"Logged out successfully\" }",
    },
    {
        "method": "GET", "path": "/api/auth/me", "auth": "Bearer / Cookie",
        "summary": "Return the currently authenticated user.",
        "usage": "curl __BASE__/api/auth/me \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"id\": 1, \"email\": \"meet@dotsai.in\",\n  \"name\": \"Meet Deshani\", \"status\": \"Active\",\n  \"role\": { \"name\": \"Admin\" }\n}",
    },
    {
        "method": "GET", "path": "/api/users", "auth": "Bearer / Cookie",
        "summary": "List all users. Optional ?role=<name> filter.",
        "usage": "curl \"__BASE__/api/users?role=Admin\" \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "[\n  {\n    \"id\": 1, \"name\": \"Meet Deshani\",\n    \"email\": \"meet@dotsai.in\",\n    \"role\": { \"name\": \"Admin\" },\n    \"status\": \"Active\"\n  }\n]",
    },
    {
        "method": "POST", "path": "/api/users", "auth": "Bearer / Cookie",
        "summary": "Create a user. role_name defaults to Admin; a default password is assigned.",
        "usage": "curl -X POST __BASE__/api/users \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"email\":\"jane@acme.com\",\"name\":\"Jane\",\"role_name\":\"Operator\",\"status\":\"Active\"}'",
        "response": "{\n  \"id\": 2, \"email\": \"jane@acme.com\",\n  \"name\": \"Jane\", \"status\": \"Active\"\n}",
    },
    {
        "method": "PATCH", "path": "/api/users/{user_id}", "auth": "Bearer / Cookie",
        "summary": "Update a user's name, status, role (by name), or organisation.",
        "usage": "curl -X PATCH __BASE__/api/users/2 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"status\":\"Disabled\",\"role_name\":\"Viewer\"}'",
        "response": "{ \"id\": 2, \"status\": \"Disabled\", \"role\": { \"name\": \"Viewer\" } }",
    },
    {
        "method": "DELETE", "path": "/api/users/{user_id}", "auth": "Bearer / Cookie",
        "summary": "Delete a user by id. You cannot delete your own account.",
        "usage": "curl -X DELETE __BASE__/api/users/2 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"User deleted successfully\" }",
    },
    {
        "method": "GET", "path": "/api/organisations", "auth": "Bearer / Cookie",
        "summary": "List all organisations.",
        "usage": "curl __BASE__/api/organisations \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "[\n  {\n    \"id\": 1, \"name\": \"Z9S-AI\",\n    \"slug\": \"z9s-ai\",\n    \"industry\": \"AI Implementation\"\n  }\n]",
    },
    {
        "method": "POST", "path": "/api/organisations", "auth": "Bearer / Cookie",
        "summary": "Create an organisation. slug must be unique.",
        "usage": "curl -X POST __BASE__/api/organisations \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"name\":\"Acme\",\"slug\":\"acme\",\"industry\":\"SaaS\"}'",
        "response": "{\n  \"id\": 2, \"name\": \"Acme\", \"slug\": \"acme\"\n}",
    },
    {
        "method": "PATCH", "path": "/api/organisations/{org_id}", "auth": "Bearer / Cookie",
        "summary": "Update any organisation fields (name, slug, industry, color, ...).",
        "usage": "curl -X PATCH __BASE__/api/organisations/2 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"industry\":\"Fintech\"}'",
        "response": "{ \"id\": 2, \"name\": \"Acme\", \"industry\": \"Fintech\" }",
    },
    {
        "method": "DELETE", "path": "/api/organisations/{org_id}", "auth": "Bearer / Cookie",
        "summary": "Delete an organisation (cascades to its products/workspaces/roles).",
        "usage": "curl -X DELETE __BASE__/api/organisations/2 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"Organisation deleted successfully\" }",
    },
    {
        "method": "GET", "path": "/api/products", "auth": "Bearer / Cookie",
        "summary": "List products. Optional ?organisation_id=<id> filter.",
        "usage": "curl \"__BASE__/api/products?organisation_id=1\" \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "[\n  {\n    \"id\": 1, \"name\": \"HQ Portal\",\n    \"code\": \"hq\", \"status\": \"Active\"\n  }\n]",
    },
    {
        "method": "POST", "path": "/api/products", "auth": "Bearer / Cookie",
        "summary": "Create a product. code must be unique.",
        "usage": "curl -X POST __BASE__/api/products \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"name\":\"CRM\",\"code\":\"crm\",\"organisation_id\":1}'",
        "response": "{\n  \"id\": 2, \"name\": \"CRM\", \"code\": \"crm\"\n}",
    },
    {
        "method": "PATCH", "path": "/api/products/{product_id}", "auth": "Bearer / Cookie",
        "summary": "Update any product fields (name, code, status, description, ...).",
        "usage": "curl -X PATCH __BASE__/api/products/2 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"status\":\"Archived\"}'",
        "response": "{ \"id\": 2, \"name\": \"CRM\", \"status\": \"Archived\" }",
    },
    {
        "method": "DELETE", "path": "/api/products/{product_id}", "auth": "Bearer / Cookie",
        "summary": "Delete a product by id.",
        "usage": "curl -X DELETE __BASE__/api/products/2 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"Product deleted successfully\" }",
    },
    {
        "method": "GET", "path": "/api/workspaces", "auth": "Bearer / Cookie",
        "summary": "List workspaces. Optional ?organisation_id and ?product_id filters.",
        "usage": "curl \"__BASE__/api/workspaces?product_id=1\" \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "[\n  {\n    \"id\": 1, \"name\": \"HQ\",\n    \"slug\": \"hq\", \"icon\": \"grid\"\n  }\n]",
    },
    {
        "method": "POST", "path": "/api/workspaces", "auth": "Bearer / Cookie",
        "summary": "Create a workspace.",
        "usage": "curl -X POST __BASE__/api/workspaces \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"name\":\"Document\",\"slug\":\"document\",\"icon\":\"document\",\"organisation_id\":1,\"product_id\":1}'",
        "response": "{\n  \"id\": 4, \"name\": \"Document\",\n  \"icon\": \"document\"\n}",
    },
    {
        "method": "PATCH", "path": "/api/workspaces/{workspace_id}", "auth": "Bearer / Cookie",
        "summary": "Update any workspace fields (name, slug, icon, status, ...).",
        "usage": "curl -X PATCH __BASE__/api/workspaces/4 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"icon\":\"grid\"}'",
        "response": "{ \"id\": 4, \"name\": \"Document\", \"icon\": \"grid\" }",
    },
    {
        "method": "DELETE", "path": "/api/workspaces/{workspace_id}", "auth": "Bearer / Cookie",
        "summary": "Delete a workspace by id.",
        "usage": "curl -X DELETE __BASE__/api/workspaces/4 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"Workspace deleted successfully\" }",
    },
    {
        "method": "GET", "path": "/api/roles", "auth": "Bearer / Cookie",
        "summary": "List roles. Optional ?organisation_id filter. Includes linked permissions.",
        "usage": "curl __BASE__/api/roles \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "[\n  {\n    \"id\": 1, \"name\": \"Admin\",\n    \"description\": \"Full access\",\n    \"permissions\": [ ... ]\n  }\n]",
    },
    {
        "method": "POST", "path": "/api/roles", "auth": "Bearer / Cookie",
        "summary": "Create a role. name is unique per organisation.",
        "usage": "curl -X POST __BASE__/api/roles \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"name\":\"Analyst\",\"description\":\"Read-only analytics\",\"organisation_id\":1}'",
        "response": "{\n  \"id\": 4, \"name\": \"Analyst\"\n}",
    },
    {
        "method": "PATCH", "path": "/api/roles/{role_id}", "auth": "Bearer / Cookie",
        "summary": "Update a role's name or description.",
        "usage": "curl -X PATCH __BASE__/api/roles/4 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"description\":\"Read-only analytics access\"}'",
        "response": "{ \"id\": 4, \"name\": \"Analyst\", \"description\": \"Read-only analytics access\" }",
    },
    {
        "method": "DELETE", "path": "/api/roles/{role_id}", "auth": "Bearer / Cookie",
        "summary": "Delete a role by id.",
        "usage": "curl -X DELETE __BASE__/api/roles/4 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"Role deleted successfully\" }",
    },
    {
        "method": "GET", "path": "/api/permissions", "auth": "Bearer / Cookie",
        "summary": "List every permission policy on the platform.",
        "usage": "curl __BASE__/api/permissions \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "[\n  {\n    \"id\": 1, \"name\": \"Read Users\",\n    \"code\": \"users:read\"\n  }\n]",
    },
    {
        "method": "POST", "path": "/api/roles/{role_id}/permissions", "auth": "Bearer / Cookie",
        "summary": "Replace a role's permissions with the given list of codes.",
        "usage": "curl -X POST __BASE__/api/roles/1/permissions \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '[\"users:read\",\"users:write\"]'",
        "response": "{ \"detail\": \"Permissions updated successfully for role Admin\" }",
    },
    {
        "method": "GET", "path": "/api/dashboard/stats", "auth": "Bearer / Cookie",
        "summary": "Live platform metrics (user/role/permission/org/product/workspace counts).",
        "usage": "curl __BASE__/api/dashboard/stats \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"stats\": [\n    { \"l\": \"Total Users\", \"v\": \"1\", \"d\": \"↗ Active: 1\" }\n  ]\n}",
    },
    {
        "method": "POST", "path": "/api/feedback", "auth": "Bearer / Cookie",
        "summary": "Submit feedback. Automatically attributed to the signed-in user.",
        "usage": "curl -X POST __BASE__/api/feedback \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"category\":\"bug\",\"text\":\"Export button 404s\",\"path\":\"/hq/config/users\"}'",
        "response": "{\n  \"id\": 1, \"category\": \"bug\",\n  \"status\": \"Open\",\n  \"user\": { \"name\": \"Meet Deshani\", \"email\": \"meet@dotsai.in\" }\n}",
    },
    {
        "method": "GET", "path": "/api/feedback", "auth": "Bearer / Cookie",
        "summary": "List all feedback, newest first. Optional ?status=Open|Reviewed|Closed.",
        "usage": "curl \"__BASE__/api/feedback?status=Open\" \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "[\n  {\n    \"id\": 1, \"category\": \"bug\",\n    \"text\": \"Export button 404s\",\n    \"status\": \"Open\",\n    \"user\": { \"name\": \"Meet Deshani\" }\n  }\n]",
    },
    {
        "method": "PATCH", "path": "/api/feedback/{feedback_id}", "auth": "Bearer / Cookie",
        "summary": "Update feedback status (Open / Reviewed / Closed) or category.",
        "usage": "curl -X PATCH __BASE__/api/feedback/1 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"status\":\"Reviewed\"}'",
        "response": "{ \"id\": 1, \"status\": \"Reviewed\" }",
    },
    {
        "method": "DELETE", "path": "/api/feedback/{feedback_id}", "auth": "Bearer / Cookie",
        "summary": "Delete a feedback entry by id.",
        "usage": "curl -X DELETE __BASE__/api/feedback/1 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"Feedback deleted successfully\" }",
    },
    {
        "method": "GET", "path": "/api/notifications", "auth": "Bearer / Cookie",
        "summary": "List the signed-in user's notifications, newest first. Optional ?unread=true.",
        "usage": "curl \"__BASE__/api/notifications?unread=true\" \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "[\n  {\n    \"id\": 3, \"title\": \"New user Jane joined the platform\",\n    \"category\": \"update\", \"read\": false,\n    \"path\": \"/hq/config/users\"\n  }\n]",
    },
    {
        "method": "POST", "path": "/api/notifications", "auth": "Bearer / Cookie",
        "summary": "Create a notification targeting a specific user.",
        "usage": "curl -X POST __BASE__/api/notifications \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"user_id\":1,\"title\":\"Deploy finished\",\"category\":\"platform\"}'",
        "response": "{ \"id\": 4, \"title\": \"Deploy finished\", \"read\": false }",
    },
    {
        "method": "POST", "path": "/api/notifications/read-all", "auth": "Bearer / Cookie",
        "summary": "Mark all of the signed-in user's notifications as read.",
        "usage": "curl -X POST __BASE__/api/notifications/read-all \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"2 notification(s) marked as read\" }",
    },
    {
        "method": "PATCH", "path": "/api/notifications/{notification_id}", "auth": "Bearer / Cookie",
        "summary": "Mark one of your notifications read/unread.",
        "usage": "curl -X PATCH __BASE__/api/notifications/3 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"read\":true}'",
        "response": "{ \"id\": 3, \"read\": true }",
    },
    {
        "method": "DELETE", "path": "/api/notifications/{notification_id}", "auth": "Bearer / Cookie",
        "summary": "Delete one of your notifications.",
        "usage": "curl -X DELETE __BASE__/api/notifications/3 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"Notification deleted successfully\" }",
    },
    {
        "method": "POST", "path": "/api/ai/chat", "auth": "Bearer / Cookie",
        "summary": "Chat with the AI assistant. Proxies to the configured LLM (AI_PROVIDER) with the current page as context; returns a canned notice until a key is set.",
        "usage": "curl -X POST __BASE__/api/ai/chat \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"message\":\"What can I do on this page?\",\"context\":\"HQ · Config · Users\"}'",
        "response": "{\n  \"reply\": \"On the Users page you can ...\",\n  \"model\": \"claude-3-5-sonnet-20241022\",\n  \"configured\": true\n}",
    },
    {
        "method": "GET", "path": "/api/catalog", "auth": "Public",
        "summary": "This catalog — every endpoint with usage + response. Start here.",
        "usage": "curl __BASE__/api/catalog",
        "response": "{\n  \"base_url\": \"__BASE__\",\n  \"count\": 37,\n  \"endpoints\": [ ... ]\n}",
    },
]

@app.get("/api/catalog", response_model=ApiCatalogResponse)
def get_api_catalog(request: Request):
    # Derive the live base URL so copy-paste examples target the right host.
    base = str(request.base_url).rstrip("/")
    endpoints = [
        ApiCatalogItem(
            method=e["method"],
            path=e["path"],
            auth=e["auth"],
            summary=e["summary"],
            usage=e["usage"].replace("__BASE__", base),
            response=e["response"].replace("__BASE__", base),
        )
        for e in API_CATALOG
    ]
    return {"base_url": base, "count": len(endpoints), "endpoints": endpoints}

# ── CLI CATALOG ──
# A reference for the bundled hq-cli tool (cli/hq-cli.py) — every command with
# a copy-paste invocation and example output. Public, like /api/catalog, so
# agents can discover the CLI surface too. hq-cli targets the host in the
# HQ_API_URL env var (defaults to http://localhost:8000).
CLI_CATALOG = [
    {
        "group": "auth", "command": "hq-cli login",
        "usage": "hq-cli login --email meet@dotsai.in --password meetdeshani123",
        "description": "Authenticate with the HQ backend and cache the JWT at ~/.hq_token.",
        "output": "Successfully logged in! Token saved to ~/.hq_token",
    },
    {
        "group": "auth", "command": "hq-cli logout",
        "usage": "hq-cli logout",
        "description": "Clear the locally cached authentication token.",
        "output": "Logged out successfully.",
    },
    {
        "group": "system", "command": "hq-cli status",
        "usage": "hq-cli status",
        "description": "Fetch and display the current HQ dashboard metrics.",
        "output": "=== HQ Dashboard Status ===\nMetric      | Value | Trend / Info\n------------------------------------\nTotal Users | 1     | ↗ Active: 1",
    },
    {
        "group": "users", "command": "hq-cli users list",
        "usage": "hq-cli users list --role Admin",
        "description": "List all registered users. Optional --role filter.",
        "output": "--- Registered Users ---\nID | Name         | Email          | Role  | Status\n1  | Meet Deshani | meet@dotsai.in | Admin | Active",
    },
    {
        "group": "users", "command": "hq-cli users create",
        "usage": "hq-cli users create --email jane@acme.com --name \"Jane\" --role Operator",
        "description": "Create a new user (a default password is assigned).",
        "output": "User Jane (jane@acme.com) created successfully with role Operator!",
    },
    {
        "group": "users", "command": "hq-cli users delete",
        "usage": "hq-cli users delete 2",
        "description": "Delete a user by numeric ID.",
        "output": "User ID 2 deleted successfully.",
    },
    {
        "group": "roles", "command": "hq-cli roles list",
        "usage": "hq-cli roles list",
        "description": "List all configured roles.",
        "output": "--- Configured Roles ---\nID | Role Name | Description\n1  | Admin     | Administrator with full permissions",
    },
    {
        "group": "roles", "command": "hq-cli roles create",
        "usage": "hq-cli roles create --name Analyst --description \"Read-only analytics\"",
        "description": "Create a new role.",
        "output": "Role 'Analyst' created successfully!",
    },
    {
        "group": "roles", "command": "hq-cli roles permissions",
        "usage": "hq-cli roles permissions",
        "description": "List all available permission policies.",
        "output": "--- Available Permissions ---\nID | Permission Name | Code Tag   | Description\n1  | Read Users      | users:read | List and view users",
    },
    {
        "group": "roles", "command": "hq-cli roles grant",
        "usage": "hq-cli roles grant --role-id 1 --permissions users:read,users:write",
        "description": "Grant a comma-separated list of permission codes to a role.",
        "output": "Permissions updated successfully for Role ID 1.",
    },
    {
        "group": "orgs", "command": "hq-cli orgs list",
        "usage": "hq-cli orgs list",
        "description": "List all registered organisations.",
        "output": "--- Registered Organisations ---\nID | Name   | Slug   | Industry          | Initials | Color\n1  | Z9S-AI | z9s-ai | AI Implementation | Z        | #C8B6FF",
    },
    {
        "group": "orgs", "command": "hq-cli orgs create",
        "usage": "hq-cli orgs create --name Acme --slug acme --industry SaaS",
        "description": "Create a new organisation.",
        "output": "Organisation 'Acme' (acme) created successfully!",
    },
    {
        "group": "products", "command": "hq-cli products list",
        "usage": "hq-cli products list --org-id 1",
        "description": "List all configured products. Optional --org-id filter.",
        "output": "--- Configured Products ---\nID | Name      | Code | Org ID | Status\n1  | HQ Portal | hq   | 1      | Active",
    },
    {
        "group": "products", "command": "hq-cli products create",
        "usage": "hq-cli products create --name CRM --code crm --org-id 1",
        "description": "Create a new product.",
        "output": "Product 'CRM' (crm) created successfully!",
    },
    {
        "group": "workspaces", "command": "hq-cli workspaces list",
        "usage": "hq-cli workspaces list --product-id 1",
        "description": "List all active workspaces. Optional --org-id / --product-id filters.",
        "output": "--- Active Workspaces ---\nID | Name | Slug | Icon | Org ID | Product ID | Status\n1  | HQ   | hq   | grid | 1      | 1          | Active",
    },
    {
        "group": "workspaces", "command": "hq-cli workspaces create",
        "usage": "hq-cli workspaces create --name Document --slug document --icon document --org-id 1 --product-id 1",
        "description": "Create a new workspace.",
        "output": "Workspace 'Document' created successfully!",
    },
]

@app.get("/api/cli", response_model=CliCatalogResponse)
def get_cli_catalog():
    commands = [CliCommandItem(**c) for c in CLI_CATALOG]
    return {"base_command": "hq-cli", "count": len(commands), "commands": commands}

# ── SERVING FRONTEND PAGES ──

# Resolve relative paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "frontend", "static")
LOGIN_FILE = os.path.join(BASE_DIR, "frontend", "login.html")
HOME_FILE = os.path.join(BASE_DIR, "frontend", "home.html")

# Mount frontend/static directory to serve CSS, JS, and Fonts
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/login", response_class=HTMLResponse)
def serve_login(request: Request):
    # Check if user already logged in via cookie
    token = request.cookies.get("access_token")
    if token:
        return RedirectResponse(url="/z9s-ai/hq/hq/operations/dashboard")
        
    with open(LOGIN_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/home", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def serve_home_redirect(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/z9s-ai/hq/hq/operations/dashboard")

@app.get("/{org}/{product}/{workspace}/{module}/{tab}", response_class=HTMLResponse)
@app.get("/{org}/{product}/{workspace}/{module}", response_class=HTMLResponse)
@app.get("/{org}/{product}/{workspace}", response_class=HTMLResponse)
def serve_portal_route(
    request: Request,
    org: str,
    product: str,
    workspace: str,
    module: Optional[str] = None,
    tab: Optional[str] = None
):
    # Enforce login redirect
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/login")
        
    with open(HOME_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)
