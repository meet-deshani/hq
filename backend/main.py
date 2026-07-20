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
    WorkspaceResponse, WorkspaceCreate, ApiCatalogResponse, ApiCatalogItem,
    CliCatalogResponse, CliCommandItem
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
        "method": "GET", "path": "/api/catalog", "auth": "Public",
        "summary": "This catalog — every endpoint with usage + response. Start here.",
        "usage": "curl __BASE__/api/catalog",
        "response": "{\n  \"base_url\": \"__BASE__\",\n  \"count\": 18,\n  \"endpoints\": [ ... ]\n}",
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
