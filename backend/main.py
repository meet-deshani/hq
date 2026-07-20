import os
import logging
from fastapi import FastAPI, Depends, HTTPException, status, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional

from backend.database import engine, Base, SessionLocal, get_db
from backend.models import User, Role, Permission, Organisation, Product, Workspace
from backend.schemas import (
    LoginRequest, Token, UserResponse, UserCreate, UserUpdate,
    RoleResponse, RoleCreate, PermissionResponse, DashboardStatsResponse, StatItem,
    OrganisationResponse, OrganisationCreate, ProductResponse, ProductCreate,
    WorkspaceResponse, WorkspaceCreate
)
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
    return db_user

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
