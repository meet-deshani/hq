import os
import secrets
import hashlib
import logging
from fastapi import FastAPI, Depends, HTTPException, status, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional

from backend.database import engine, Base, SessionLocal, get_db
from backend.models import User, Role, Permission, Organisation, Product, Workspace, Feedback, Notification
from backend.crm_models import Conversation
# Imported for the side effect of registering the CRM tables on Base.metadata
# before create_all runs below.
from backend import crm_models  # noqa: F401
# Same reason: registers the TabDesk tables on Base.metadata before create_all.
from backend import tabdesk_models  # noqa: F401
from backend import (
    audit, comms, crud, dashboards, permissions, registry, seed_crm, tabdesk,
    whatsapp, zoho, zoho_sync,
)
from sqlalchemy import or_
from backend.schemas import (
    LoginRequest, Token, UserResponse, UserCreate, UserCreateResponse, UserUpdate, PasswordSet,
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
    verify_password, get_password_hash, create_access_token, get_current_user,
    get_user_from_token
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
                organisation_id=org.id, product_id=product.id,
                name="HQ", slug="hq", icon="hq",
                description="HQ main workspace", status="Active"
            )
            config_ws = Workspace(
                organisation_id=org.id, product_id=product.id,
                name="Config", slug="config", icon="config",
                description="Configuration workspace", status="Active"
            )
            users_ws = Workspace(
                organisation_id=org.id, product_id=product.id,
                name="Users", slug="users", icon="admin",
                description="User management workspace", status="Active"
            )
            document_ws = Workspace(
                organisation_id=org.id, product_id=product.id,
                name="Document", slug="document", icon="document",
                description="API & CLI reference workspace", status="Active"
            )
            db.add_all([hq_ws, config_ws, users_ws, document_ws])
            db.commit()
            logger.info("Default workspaces seeded.")

        # Roles, the permission catalogue and every grant are derived from the
        # entity registry in backend/permissions.py, so a new entity is covered
        # automatically rather than silently shipping unprotected. Idempotent:
        # it rebuilds the catalogue each boot, which also removes dead policies.
        permissions.seed(db, org.id)

        # Check if default admin user is seeded
        if db.query(User).filter(User.email == "meet@dotsai.in").count() == 0:
            # Admin password comes from the environment — never commit a real one
            # to the repo. If unset, skip the seed rather than ship a weak default.
            seed_admin_password = os.getenv("SEED_ADMIN_PASSWORD")
            if not seed_admin_password or not seed_admin_password.strip():
                logger.warning(
                    "SEED_ADMIN_PASSWORD is not set — skipping default admin seed. "
                    "Set it in the app's .env and restart to create meet@dotsai.in."
                )
                return
            logger.info("Seeding default admin user meet@dotsai.in...")
            admin_role = db.query(Role).filter(Role.name == "Admin", Role.organisation_id == org.id).first()
            admin_user = User(
                email="meet@dotsai.in",
                name="Meet Deshani",
                password_hash=get_password_hash(seed_admin_password),
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

        # CRM config, the team and the real book of work. Idempotent — it
        # re-checks every natural key, so a restart never duplicates a row.
        admin_user = db.query(User).filter(User.email == "meet@dotsai.in").first()
        if admin_user:
            seed_crm.seed(db, org, admin_user, get_password_hash)

    except Exception as e:
        # exc_info, because a bare message hid a UNIQUE violation in permission
        # seeding that left the org with no roles at all — every user then held
        # no permissions and the whole platform answered 403.
        logger.error("Error seeding database: %s", e, exc_info=True)
        db.rollback()
    finally:
        _assert_authorisation_usable(db)
        db.close()


def _assert_authorisation_usable(db):
    """Shout if seeding left authorisation in an unusable state.

    Seeding is caught rather than fatal — a half-seeded database should not
    stop the app booting at 2am. But a silent partial seed is how the roles
    went missing in the first place, so the outcome is always checked and the
    failure is impossible to miss in the logs.
    """
    try:
        expected = set(permissions.ROLES)
        found = {r.name for r in db.query(Role).all()}
        missing = sorted(expected - found)
        if missing:
            logger.error(
                "AUTHORISATION INCOMPLETE — roles missing: %s. Users holding them have NO "
                "permissions and every request will be refused. Fix the seeding error above "
                "and restart.", ", ".join(missing),
            )
        else:
            logger.info("Authorisation ready: %d roles, %d permissions.",
                        len(found), db.query(Permission).count())
    except Exception as exc:  # pragma: no cover - diagnostics must never break boot
        logger.error("Could not verify authorisation state: %s", exc)

# ── API ROUTES ──

# Auth
@app.post("/api/auth/login", response_model=Token)
def login(login_data: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == login_data.email).first()
    if not user or not verify_password(login_data.password, user.password_hash):
        # Failed attempts are audited too — an unexplained lockout or a probe
        # is only diagnosable if the misses are on the record, not just the hits.
        audit.record(
            db, action="login_failed", entity_type="users", entity_label=login_data.email,
            actor=None, request=request, commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    audit.record(
        db, action="login", entity_type="users", entity_id=user.id, entity_label=user.email,
        actor=user, request=request, organisation_id=user.organisation_id, commit=True,
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

@app.get("/api/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    """The signed-in user, plus what they are allowed to do.

    The UI gates its New / Edit / Delete affordances on `can`, so a button that
    would 403 is never shown. The server still enforces every action — this is
    for honesty in the interface, not security.
    """
    # from_attributes must be explicit here: without it the nested `role`
    # relationship is rejected as "not a dict or RoleBase".
    data = UserResponse.model_validate(current_user, from_attributes=True).model_dump()
    data["permissions"] = sorted(permissions.permissions_for(current_user))
    data["can"] = permissions.can_map(current_user)
    return data

# Users
@app.get("/api/users", response_model=List[UserResponse])
def list_users(
    role: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    permissions.require(current_user, "users", "read")
    query = db.query(User)
    if role:
        query = query.join(Role).filter(Role.name == role)
    return query.all()

@app.post("/api/users", response_model=UserCreateResponse)
def create_user(
    user_data: UserCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    permissions.require(current_user, "users", "create")
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

    # Honour a caller-supplied password, else mint a strong random one so no
    # account is ever created with a committed/guessable default.
    supplied = (user_data.password or "").strip()
    raw_password = supplied or secrets.token_urlsafe(12)

    db_user = User(
        email=user_data.email,
        name=user_data.name,
        password_hash=get_password_hash(raw_password),
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
    # Surface the generated password ONCE (transient, never persisted) so an admin
    # can share it. Stays None when the caller set their own password.
    db_user.initial_password = None if supplied else raw_password
    return db_user

@app.patch("/api/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    permissions.require(current_user, "users", "update")
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
    permissions.require(current_user, "users", "delete")
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

@app.post("/api/users/{user_id}/password")
def set_user_password(
    user_id: int,
    payload: PasswordSet,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Admin-only: setting another user's password is a privileged action, so it
    # is gated on the Admin role rather than mere authentication.
    if not (current_user.role and current_user.role.name == "Admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can change user passwords"
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    new_password = (payload.password or "").strip()
    if len(new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters"
        )
    user.password_hash = get_password_hash(new_password)
    db.commit()
    return {"detail": f"Password updated for {user.email}"}

# Organisations
@app.get("/api/organisations", response_model=List[OrganisationResponse])
def list_organisations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    permissions.require(current_user, "organisations", "read")
    return db.query(Organisation).all()

@app.post("/api/organisations", response_model=OrganisationResponse)
def create_organisation(
    org_data: OrganisationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    permissions.require(current_user, "organisations", "create")
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
    permissions.require(current_user, "organisations", "update")
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
    permissions.require(current_user, "organisations", "delete")
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
    permissions.require(current_user, "products", "read")
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
    permissions.require(current_user, "products", "create")
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
    permissions.require(current_user, "products", "update")
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
    permissions.require(current_user, "products", "delete")
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
    permissions.require(current_user, "workspaces", "read")
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
    permissions.require(current_user, "workspaces", "create")
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
    permissions.require(current_user, "workspaces", "update")
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
    permissions.require(current_user, "workspaces", "delete")
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
    permissions.require(current_user, "roles", "read")
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
    permissions.require(current_user, "roles", "create")
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
    permissions.require(current_user, "roles", "update")
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
    permissions.require(current_user, "roles", "delete")
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
    permissions.require(current_user, "permissions", "read")
    return db.query(Permission).all()

@app.post("/api/roles/{role_id}/permissions")
def grant_permission_to_role(
    role_id: int,
    permission_codes: List[str],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    permissions.require(current_user, "permissions", "update")
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
# Dashboards are readable by any authenticated user by design: they aggregate
# only what the caller could already list, and Meet's requirement is that
# everyone sees the whole picture.
@app.get("/api/dashboard/stats", response_model=DashboardStatsResponse)
def get_dashboard_stats(
    workspace: str = "hq",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Metrics for one workspace.

    Each workspace answers its own question rather than repeating the platform's
    user/role counts, which told a CRM user nothing. See backend/dashboards.py.
    """
    return {"stats": [StatItem(**s) for s in dashboards.stats_for(db, current_user, workspace)]}


# Global search — searches real DB entities (not the static nav tree).
@app.get("/api/search")
def search(
    q: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Global search across every entity the caller may read.

    Driven by each entity's declared `search` columns, so a new entity becomes
    searchable with no change here. It previously covered only platform config —
    users, orgs, products, workspaces, roles — which meant searching for a
    customer by name found nothing at all.
    """
    q = (q or "").strip()
    if not q:
        return {"results": []}
    like = "%%%s%%" % q
    results = []

    for ent in registry.ENTITIES:
        if not permissions.has(current_user, ent["key"], "read"):
            continue
        model = ent["model"]
        clauses = [getattr(model, f).ilike(like) for f in ent.get("search", [])
                   if hasattr(model, f)]
        if not clauses:
            continue

        query = db.query(model).filter(or_(*clauses))
        for col, val in (ent.get("scope") or {}).items():
            query = query.filter(getattr(model, col) == val)

        title_field = ent.get("title_field") or "name"
        # The most useful second line is the first ref or text column that is
        # not the title itself.
        sub_field = next((c["k"] for c in ent.get("columns", [])
                          if c["k"] != title_field and c.get("type") in ("text", "mono", "badge")), None)

        for row in query.limit(5).all():
            results.append({
                "type": ent["label"],
                "label": getattr(row, title_field, None) or ("#%s" % row.id),
                "sub": (str(getattr(row, sub_field, "") or "") if sub_field else ""),
                "product": "hq",
                "workspace": ent["workspace"],
                "module": ent["module"],
                "tab": ent["plural"],
                "entity": ent["key"],
                "id": row.id,
            })

    # Platform config records keep their place in the results.
    for u in db.query(User).filter(User.name.ilike(like) | User.email.ilike(like)).limit(4).all():
        results.append({"type": "User", "label": u.name, "sub": u.email, "product": "hq",
                        "workspace": "Config", "module": "Platform", "tab": "Users"})
    for o in db.query(Organisation).filter(Organisation.name.ilike(like) | Organisation.slug.ilike(like)).limit(3).all():
        results.append({"type": "Organisation", "label": o.name, "sub": o.industry or o.slug,
                        "product": "hq", "workspace": "Config", "module": "Platform", "tab": "Organisations"})
    for r in db.query(Role).filter(Role.name.ilike(like)).limit(3).all():
        results.append({"type": "Role", "label": r.name, "sub": r.description or "", "product": "hq",
                        "workspace": "Config", "module": "Platform", "tab": "Roles"})

    # Whole-word matches first — searching "Pioneer" should surface Pioneer
    # Engineering above a project that merely mentions it.
    needle = q.lower()
    results.sort(key=lambda r: (not str(r["label"]).lower().startswith(needle),
                                str(r["label"]).lower()))
    return {"results": results[:20]}


@app.get("/api/dashboard/trend")
def dashboard_trend(
    workspace: str = "hq",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cumulative growth of the workspace's primary record over six months."""
    return dashboards.trend_for(db, workspace)


# Feedback
@app.post("/api/feedback", response_model=FeedbackResponse)
def create_feedback(
    fb: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    permissions.require(current_user, "feedback", "create")
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
    permissions.require(current_user, "feedback", "read")
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
    permissions.require(current_user, "feedback", "update")
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
    permissions.require(current_user, "feedback", "delete")
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

# Notifications are inherently self-scoped — every query below filters by
# current_user.id, so a caller can only ever reach their own. A permission check
# would add a second, weaker expression of the same rule.
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

# ── COMMUNICATION ──

@app.post("/api/comms/inbound")
def comms_inbound(payload: dict, request: Request, db: Session = Depends(get_db)):
    """Carrier webhook — land a message against its thread.

    Authenticated with a shared secret rather than a JWT, because the WhatsApp
    bot is a service, not a person. It FAILS CLOSED: with no COMMS_WEBHOOK_TOKEN
    set the route refuses everything, so an unconfigured deployment cannot
    accept anonymous writes into the message store.
    """
    expected = comms.webhook_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Inbound messaging is not configured. Set COMMS_WEBHOOK_TOKEN in the "
                   "server environment and send it as the X-HQ-Webhook-Token header.",
        )
    if request.headers.get("X-HQ-Webhook-Token", "") != expected:
        # Deliberately not saying which part was wrong.
        raise HTTPException(status_code=401, detail="Invalid webhook token.")

    org = db.query(Organisation).filter(Organisation.slug == "z9s-ai").first()
    if org is None:
        raise HTTPException(status_code=503, detail="Organisation not initialised.")

    try:
        message, conversation, created = comms.ingest(db, org.id, payload or {})
    except comms.Ignored as exc:
        # Not an error: the carrier did its job and HQ chose not to keep this.
        # A 200 stops the bot retrying something it will never deliver.
        return {"created": False, "ignored": True, "reason": str(exc)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.commit()
    return {
        "created": created,
        "duplicate": not created,
        "message_id": message.id,
        "conversation_id": conversation.id,
        "party_id": conversation.party_id,
        "linked": conversation.party_id is not None,
    }


@app.get("/api/conversations/{conversation_id}/thread")
def comms_thread(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A conversation with its messages, oldest first."""
    permissions.require(current_user, "conversations", "read")
    data = comms.thread(db, current_user.organisation_id, conversation_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Whether a reply on this thread will actually leave the building, so the
    # composer can offer to Send instead of quietly promising one and recording
    # the other. comms stays carrier-agnostic; only this layer knows the bot.
    data["sending_enabled"] = data["channel_type"] == "whatsapp" and whatsapp.is_configured()
    return data


@app.post("/api/conversations/{conversation_id}/messages")
def comms_reply(
    conversation_id: int,
    payload: dict,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send an outbound message on a thread, and record what actually happened.

    On a WhatsApp thread this really sends, through the bot at wa.dotsai.cloud.
    The stored delivery_status is the truth of that one attempt: `sent` only when
    the bot took the message, `failed` when it did not, `recorded` when no bot is
    wired up at all. A thread must never claim a delivery HQ cannot stand behind.

    A failed send is still a 200 with the message recorded and `delivered: false`
    — the text was written and belongs in the thread. Losing it *and* the reason
    would leave the operator with nothing to act on.

    The send is attempted before the record is written so the status stored is
    the outcome that actually occurred, never an optimistic guess awaiting a
    correction that may never arrive.
    """
    permissions.require(current_user, "conversations", "update")
    convo = db.query(Conversation).filter(
        Conversation.organisation_id == current_user.organisation_id,
        Conversation.id == conversation_id,
    ).first()
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    body = (payload or {}).get("body", "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="'body' is required")

    channel_type = convo.channel.channel_type if convo.channel else None
    delivery_status, external_id, detail = "recorded", None, None

    if channel_type == "whatsapp" and whatsapp.is_configured():
        number = whatsapp.dial_address(db, convo)
        if not number:
            delivery_status = "failed"
            detail = (
                "No dialable number for this thread. HQ holds '%s', which carries no "
                "country code, and the linked contact has none either. Add the full "
                "international number to the contact and send again."
                % convo.contact_identifier
            )
        else:
            try:
                external_id = whatsapp.send_text(number, body)
                delivery_status = "sent"
            except whatsapp.WhatsAppError as exc:
                delivery_status, detail = "failed", str(exc)
                logger.warning("WhatsApp send failed on conversation %s: %s", convo.id, exc)
    elif channel_type == "whatsapp":
        detail = (
            "Recorded only — WhatsApp sending is not configured on this server, so "
            "nothing was delivered. " + whatsapp.SETUP_HINT
        )

    message, _, _ = comms.ingest(db, current_user.organisation_id, {
        "channel_id": convo.channel_id,
        "from": convo.contact_identifier,
        "direction": "outbound",
        "body": body,
        "author_id": current_user.id,
        # The bot's own id, so the copy WhatsApp echoes back to the bot as a
        # sent message is recognised as this message rather than a second one.
        "external_id": external_id or (payload or {}).get("external_id"),
        "delivery_status": delivery_status,
    })
    db.commit()
    audit.record(
        db, action="reply", entity_type="conversations", entity_id=convo.id,
        entity_label=convo.contact_name, actor=current_user, request=request,
        changes={"message": {"from": None, "to": body[:500]},
                 "delivery": {"from": None, "to": delivery_status}},
        organisation_id=convo.organisation_id, commit=True,
    )
    return {
        "id": message.id,
        "conversation_id": convo.id,
        "sent_at": message.sent_at.isoformat() + "Z",
        "delivery_status": delivery_status,
        "delivered": delivery_status == "sent",
        "detail": detail,
    }


@app.post("/api/conversations/{conversation_id}/read")
def comms_mark_read(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    permissions.require(current_user, "conversations", "update")
    convo = db.query(Conversation).filter(
        Conversation.organisation_id == current_user.organisation_id,
        Conversation.id == conversation_id,
    ).first()
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    comms.mark_read(db, convo)
    db.commit()
    return {"detail": "Marked read", "id": convo.id}


# ── ZOHO BOOKS ──
# One-directional: HQ reads Zoho and mirrors it. There is deliberately no route
# here that writes anything back — Zoho Books is where an invoice is raised.

@app.get("/api/zoho/status")
def zoho_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Whether the integration is connected, and when it last pulled."""
    permissions.require(current_user, "invoices", "read")
    return zoho.status(last_sync=zoho_sync.last_sync(db, current_user.organisation_id))


@app.get("/api/zoho/preview")
def zoho_preview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """What a sync would change, without changing anything.

    The first question about a freshly connected integration is "what is it
    about to do to my data?", so it gets a real answer rather than a leap.
    """
    permissions.require(current_user, "invoices", "read")
    try:
        return zoho_sync.preview(db, current_user.organisation_id)
    except zoho.ZohoError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/zoho/sync")
def zoho_pull(
    request: Request,
    apply_links: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pull contacts and invoices into the read-only mirror.

    `apply_links=true` additionally links customers Zoho and HQ agree on by
    EMAIL. Name-only matches are never applied automatically, however identical
    they look — they come back as proposals for a human.
    """
    # Writing the mirror is a configuration-level act, not day-to-day data entry.
    permissions.require(current_user, "invoices", "read")
    permissions.require(current_user, "customers", "update")
    try:
        report = zoho_sync.sync(db, current_user.organisation_id,
                                actor=current_user, apply_links=apply_links)
    except zoho.ZohoError as exc:
        # Not configured, or Zoho refused. Either way it is an upstream
        # condition the operator can fix, not a bug in HQ.
        raise HTTPException(status_code=503, detail=str(exc))

    audit.record(
        db, action="sync", entity_type="zoho_invoices",
        entity_label="Zoho Books pull",
        actor=current_user, request=request,
        changes={"summary": {"from": None, "to": {
            "contacts": report["contacts_seen"], "invoices": report["invoices_written"],
            "receivables_updated": report["receivables_updated"],
            "links_applied": len(report["links_applied"]),
        }}},
        organisation_id=current_user.organisation_id, commit=True,
    )
    return report


# ── API CATALOG ──
# A self-documenting reference of every endpoint on the platform. Public by
# design so AI agents and CLIs can discover the full surface before authing.
# __BASE__ is swapped for the live base URL at request time.
API_CATALOG = [
    {
        "method": "POST", "path": "/api/auth/login", "auth": "Public",
        "summary": "Authenticate with email + password. Returns a JWT and sets an httpOnly access_token cookie.",
        "usage": "curl -X POST __BASE__/api/auth/login \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"email\":\"meet@dotsai.in\",\"password\":\"<your-password>\"}'",
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
        "summary": "Create a user. role_name defaults to Admin. Omit \"password\" to auto-generate a strong one, returned once as initial_password.",
        "usage": "curl -X POST __BASE__/api/users \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"email\":\"jane@acme.com\",\"name\":\"Jane\",\"role_name\":\"Operator\",\"status\":\"Active\"}'",
        "response": "{\n  \"id\": 2, \"email\": \"jane@acme.com\",\n  \"name\": \"Jane\", \"status\": \"Active\",\n  \"initial_password\": \"tqf7Kd2pRxM_\"\n}",
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
        "method": "GET", "path": "/api/search", "auth": "Bearer / Cookie",
        "summary": "Search real DB entities (users, orgs, products, workspaces, roles) by ?q=.",
        "usage": "curl \"__BASE__/api/search?q=meet\" \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"results\": [\n    { \"type\": \"User\", \"label\": \"Meet Deshani\", \"sub\": \"meet@dotsai.in\" }\n  ]\n}",
    },
    {
        "method": "GET", "path": "/api/dashboard/trend", "auth": "Bearer / Cookie",
        "summary": "Cumulative record growth over the last 6 months, derived from created_at.",
        "usage": "curl __BASE__/api/dashboard/trend \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"points\": [\n    { \"label\": \"Feb\", \"value\": 0 },\n    { \"label\": \"Jul\", \"value\": 21 }\n  ]\n}",
    },
    {
        "method": "POST", "path": "/api/ai/chat", "auth": "Bearer / Cookie",
        "summary": "Chat with the AI assistant. Proxies to the configured LLM (AI_PROVIDER) with the current page as context; returns a canned notice until a key is set.",
        "usage": "curl -X POST __BASE__/api/ai/chat \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"message\":\"What can I do on this page?\",\"context\":\"HQ · Config · Users\"}'",
        "response": "{\n  \"reply\": \"On the Users page you can ...\",\n  \"model\": \"claude-3-5-sonnet-20241022\",\n  \"configured\": true\n}",
    },
    {
        "method": "GET", "path": "/api/meta/entities", "auth": "Bearer / Cookie",
        "summary": "THE discovery endpoint. Every entity with its columns, form fields, saved views, "
                   "relations, actions and what YOU may do with it. Start here — the UI and the CLI "
                   "both build themselves from this.",
        "usage": "curl __BASE__/api/meta/entities \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"count\": 25,\n  \"entities\": [ { \"key\": \"customers\", \"path\": \"/api/customers\",\n"
                    "    \"columns\": [...], \"fields\": [...], \"can\": { \"read\": true, \"delete\": false } } ]\n}",
    },
    {
        "method": "GET", "path": "/api/meta/entities/{key}", "auth": "Bearer / Cookie",
        "summary": "One entity's definition.",
        "usage": "curl __BASE__/api/meta/entities/customers \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"key\": \"customers\", \"label\": \"Customer\", \"fields\": [ ... ] }",
    },
    {
        "method": "GET", "path": "/api/audit", "auth": "Bearer / Cookie",
        "summary": "The change history — who changed what, when, and from where. Filter by "
                   "?entity_type= (the TABLE name, e.g. parties) and ?entity_id=.",
        "usage": "curl \"__BASE__/api/audit?entity_type=parties&limit=25\" \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"count\": 3, \"entries\": [\n    { \"action\": \"update\", \"actor\": \"meet@dotsai.in\",\n"
                    "      \"actor_kind\": \"agent\", \"changes\": { \"city\": { \"from\": \"...\", \"to\": \"...\" } } }\n  ]\n}",
    },
    {
        "method": "POST", "path": "/api/leads/{lead_id}/convert", "auth": "Bearer / Cookie",
        "summary": "Convert a lead into a customer. The lead is kept and stamped, never deleted — "
                   "the funnel history is the point. Safe to retry: a second call returns the "
                   "customer already created. A name clash with an existing customer is a 409.",
        "usage": "curl -X POST __BASE__/api/leads/1/convert \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n  -d '{}'",
        "response": "{\n  \"detail\": \"Lead converted\", \"already_converted\": false,\n"
                    "  \"customer\": { \"id\": 18, \"display_name\": \"...\" }\n}",
    },
    {
        "method": "POST", "path": "/api/users/{user_id}/password", "auth": "Bearer / Cookie",
        "summary": "Set a user's password. Admin only.",
        "usage": "curl -X POST __BASE__/api/users/2/password \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                 "  -H 'Content-Type: application/json' \\\n  -d '{\"password\":\"...\"}'",
        "response": "{ \"detail\": \"Password updated\" }",
    },
    {
        "method": "GET", "path": "/api/cli", "auth": "Public",
        "summary": "The hq-cli command reference.",
        "usage": "curl __BASE__/api/cli",
        "response": "{ \"base_command\": \"hq-cli\", \"count\": 16, \"commands\": [ ... ] }",
    },
    {
        "method": "POST", "path": "/api/comms/inbound", "auth": "X-HQ-Webhook-Token",
        "summary": "Carrier webhook — land an inbound message against its thread. Authenticated "
                   "with a shared secret, not a JWT, because the sender is a service. FAILS "
                   "CLOSED: with no COMMS_WEBHOOK_TOKEN set it refuses everything. Idempotent on "
                   "external_id, so a retried delivery is one row. An address that matches no "
                   "customer still gets a thread rather than being dropped — unless "
                   "COMMS_KNOWN_SENDERS_ONLY is on, which drops strangers and answers "
                   "{\"ignored\": true}. That is set where the carrier is also a personal number.",
        "usage": "curl -X POST __BASE__/api/comms/inbound \\\n  -H \"X-HQ-Webhook-Token: $HOOK\" \\\n"
                 "  -H 'Content-Type: application/json' \\\n"
                 "  -d '{\"channel_type\":\"whatsapp\",\"from\":\"919825115308\",\n"
                 "       \"body\":\"Revised scope attached.\",\"external_id\":\"wa-1\"}'",
        "response": "{\n  \"created\": true, \"duplicate\": false, \"message_id\": 1,\n"
                    "  \"conversation_id\": 1, \"party_id\": 1, \"linked\": true\n}",
    },
    {
        "method": "GET", "path": "/api/conversations/{conversation_id}/thread", "auth": "Bearer / Cookie",
        "summary": "One conversation with its messages, oldest first, plus the customer it belongs to.",
        "usage": "curl __BASE__/api/conversations/1/thread \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"contact_name\": \"Hemish\", \"party\": \"NeoNir Engineering\",\n"
                    "  \"messages\": [ { \"direction\": \"inbound\", \"body\": \"...\" } ]\n}",
    },
    {
        "method": "POST", "path": "/api/conversations/{conversation_id}/messages", "auth": "Bearer / Cookie",
        "summary": "Send an outbound message on a thread and record what actually happened. On a "
                   "WhatsApp channel it really sends, via the bot at wa.dotsai.cloud; on any "
                   "other channel it only records. delivery_status is the truth of that one "
                   "attempt — sent, failed, or recorded — and a failed send is still a 200 with "
                   "delivered:false and the reason, because the text belongs in the thread "
                   "either way. Never read a stored message as proof of delivery.",
        "usage": "curl -X POST __BASE__/api/conversations/1/messages \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                 "  -H 'Content-Type: application/json' \\\n  -d '{\"body\":\"Thanks, reviewing now.\"}'",
        "response": "{\n  \"id\": 2, \"conversation_id\": 1, \"sent_at\": \"...Z\",\n"
                    "  \"delivery_status\": \"sent\", \"delivered\": true, \"detail\": null\n}",
    },
    {
        "method": "POST", "path": "/api/conversations/{conversation_id}/read", "auth": "Bearer / Cookie",
        "summary": "Clear a thread's unread count.",
        "usage": "curl -X POST __BASE__/api/conversations/1/read \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"Marked read\", \"id\": 1 }",
    },
    {
        "method": "GET", "path": "/api/zoho/status", "auth": "Bearer / Cookie",
        "summary": "Whether Zoho Books is connected and when it last pulled. Never raises — an "
                   "unconfigured integration is a state, not an error.",
        "usage": "curl __BASE__/api/zoho/status \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"configured\": false, \"state\": \"not configured\", \"organisation_id\": \"60078183686\" }",
    },
    {
        "method": "GET", "path": "/api/zoho/preview", "auth": "Bearer / Cookie",
        "summary": "What a sync would change, without changing anything. Includes proposed "
                   "customer links with a confidence and a reason.",
        "usage": "curl __BASE__/api/zoho/preview \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"zoho_contacts\": 10, \"already_linked\": 6, \"proposals\": [ ... ] }",
    },
    {
        "method": "POST", "path": "/api/zoho/sync", "auth": "Bearer / Cookie",
        "summary": "Pull contacts and invoices into the read-only mirror. ?apply_links=true also "
                   "links customers that match by EMAIL; name-only matches are never applied "
                   "automatically. A figure edited by hand since the last sync is reported, "
                   "not overwritten. Writes nothing back to Zoho Books.",
        "usage": "curl -X POST \"__BASE__/api/zoho/sync?apply_links=true\" \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"contacts_seen\": 10, \"invoices_written\": 11,\n"
                    "  \"receivables_updated\": 4, \"links_applied\": [ ... ],\n"
                    "  \"receivables_skipped_edited\": [ ... ], \"proposals\": [ ... ]\n}",
    },
    # ── TabDesk · user-defined tables ───────────────────────────────────────
    # Documented here rather than generated from the registry, because TabDesk
    # tables are not registry entities — they are rows a user created at runtime.
    # An agent discovers the TABLES from /api/tabdesk/tables and their COLUMNS
    # from /api/tabdesk/tables/{id}; these entries describe the fixed surface
    # those live shapes are fetched through. See docs/TABDESK.md.
    {
        "method": "GET", "path": "/api/tabdesk/meta", "auth": "Bearer / Cookie",
        "summary": "The column type catalogue (16 types with their filter operators), the four "
                   "per-table access levels, and every registry entity a relation column can "
                   "point at. Read this before creating a table or a column.",
        "usage": "curl __BASE__/api/tabdesk/meta \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"types\": [ { \"type\": \"money\", \"ops\": [ \"eq\", \"gte\", ... ] } ],\n"
                    "  \"access_levels\": [ ... ], \"can_create\": true\n}",
    },
    {
        "method": "GET", "path": "/api/tabdesk/tables", "auth": "Bearer / Cookie",
        "summary": "Every table you may see, with row counts and your access to each, grouped for "
                   "the sidebar. A table set to private appears only for its members.",
        "usage": "curl __BASE__/api/tabdesk/tables \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"count\": 2,\n  \"tables\": [ { \"id\": 1, \"name\": \"Site visits\",\n"
                    "    \"my_access\": \"manager\", \"row_count\": 12, \"can\": { ... } } ]\n}",
    },
    {
        "method": "POST", "path": "/api/tabdesk/tables", "auth": "Bearer / Cookie",
        "summary": "Create a table. Needs tabdesk:create. Pass `columns` to define the schema in "
                   "the same request; omit it and you get one text column to start from. "
                   "visibility is 'workspace' (anyone with tabdesk:read can view) or 'private'.",
        "usage": "curl -X POST __BASE__/api/tabdesk/tables \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                 "  -H 'Content-Type: application/json' \\\n"
                 "  -d '{\"name\":\"Site visits\",\"group_name\":\"Operations\",\"columns\":["
                 "{\"label\":\"Site\",\"type\":\"text\",\"is_primary\":true},"
                 "{\"label\":\"Amount\",\"type\":\"money\"}]}'",
        "response": "{ \"id\": 1, \"slug\": \"site-visits\", \"columns\": [ ... ] }",
    },
    {
        "method": "GET", "path": "/api/tabdesk/tables/{table_id}", "auth": "Bearer / Cookie",
        "summary": "One table with its full column definitions, saved views, your access, and — "
                   "for a manager — its member list. This is the shape to render from.",
        "usage": "curl __BASE__/api/tabdesk/tables/1 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"id\": 1, \"name\": \"Site visits\", \"my_access\": \"manager\",\n"
                    "  \"columns\": [ { \"key\": \"site\", \"type\": \"text\", \"ops\": [ ... ] } ]\n}",
    },
    {
        "method": "PATCH", "path": "/api/tabdesk/tables/{table_id}", "auth": "Bearer / Cookie",
        "summary": "Rename a table, move it to another sidebar group, or change its visibility. "
                   "Needs manager access to that table.",
        "usage": "curl -X PATCH __BASE__/api/tabdesk/tables/1 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                 "  -H 'Content-Type: application/json' \\\n  -d '{\"visibility\":\"private\"}'",
        "response": "{ \"id\": 1, \"visibility\": \"private\" }",
    },
    {
        "method": "DELETE", "path": "/api/tabdesk/tables/{table_id}", "auth": "Bearer / Cookie",
        "summary": "Delete a table and every entry in it. Takes BOTH manager access to the table "
                   "and the global tabdesk:delete permission — the most destructive call here.",
        "usage": "curl -X DELETE __BASE__/api/tabdesk/tables/1 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"Table deleted\", \"id\": 1, \"rows_deleted\": 12 }",
    },
    {
        "method": "POST", "path": "/api/tabdesk/tables/{table_id}/columns", "auth": "Bearer / Cookie",
        "summary": "Add a column. Needs manager access. A select/multiselect needs `options`; a "
                   "relation needs ref_kind ('tabdesk' or 'entity') and ref_target.",
        "usage": "curl -X POST __BASE__/api/tabdesk/tables/1/columns \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                 "  -H 'Content-Type: application/json' \\\n"
                 "  -d '{\"label\":\"Customer\",\"type\":\"relation\","
                 "\"ref_kind\":\"entity\",\"ref_target\":\"customers\"}'",
        "response": "{ \"id\": 4, \"key\": \"customer\", \"type\": \"relation\" }",
    },
    {
        "method": "PATCH", "path": "/api/tabdesk/tables/{table_id}/columns/{column_id}",
        "auth": "Bearer / Cookie",
        "summary": "Relabel, retype, reorder or re-option a column. A type change re-reads every "
                   "existing value; anything that cannot convert is set to null and counted in "
                   "`values_cleared`. The column's storage key never changes.",
        "usage": "curl -X PATCH __BASE__/api/tabdesk/tables/1/columns/2 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                 "  -H 'Content-Type: application/json' \\\n  -d '{\"label\":\"Stage\"}'",
        "response": "{ \"id\": 2, \"label\": \"Stage\", \"values_cleared\": 0 }",
    },
    {
        "method": "DELETE", "path": "/api/tabdesk/tables/{table_id}/columns/{column_id}",
        "auth": "Bearer / Cookie",
        "summary": "Remove a column. Row values are left in place, so re-adding a column with the "
                   "same generated key brings them back. Removing the last column is refused.",
        "usage": "curl -X DELETE __BASE__/api/tabdesk/tables/1/columns/2 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"Column removed\", \"id\": 2 }",
    },
    {
        "method": "GET", "path": "/api/tabdesk/tables/{table_id}/rows", "auth": "Bearer / Cookie",
        "summary": "Entries, filtered and sorted. Filters are `f.<column key>.<op>=<value>` — ops "
                   "come from each column's `ops`. Different columns AND; a repeated parameter ORs. "
                   "?q= searches the text columns, ?sort=-key, ?group=key, ?view=<id>. An unknown "
                   "column or an operator the type rejects is a 400, never ignored.",
        "usage": "curl \"__BASE__/api/tabdesk/tables/1/rows?f.status.eq=Open&f.amount.gte=20000&sort=-amount\" \\\n"
                 "  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"total\": 3, \"rows\": [ { \"id\": 7, \"data\": { \"site\": \"Warangal\" } } ],\n"
                    "  \"_labels\": { \"entity:customers\": { \"5\": \"Sustro Oils\" } }\n}",
    },
    {
        "method": "POST", "path": "/api/tabdesk/tables/{table_id}/rows", "auth": "Bearer / Cookie",
        "summary": "Add an entry. Needs contributor access or better. Values are coerced per column "
                   "type — \"45,000\" becomes 45000 on a money column — and a value that cannot "
                   "convert is a 400 naming the column.",
        "usage": "curl -X POST __BASE__/api/tabdesk/tables/1/rows \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                 "  -H 'Content-Type: application/json' \\\n"
                 "  -d '{\"data\":{\"site\":\"Warangal\",\"amount\":\"45,000\",\"status\":\"Open\"}}'",
        "response": "{ \"id\": 7, \"data\": { \"site\": \"Warangal\", \"amount\": 45000 } }",
    },
    {
        "method": "PATCH", "path": "/api/tabdesk/tables/{table_id}/rows/{row_id}",
        "auth": "Bearer / Cookie",
        "summary": "Edit an entry. Only the keys you send are touched, so two people editing "
                   "different columns of one row do not clobber each other. A contributor may "
                   "edit only rows they created; an editor may edit any.",
        "usage": "curl -X PATCH __BASE__/api/tabdesk/tables/1/rows/7 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                 "  -H 'Content-Type: application/json' \\\n  -d '{\"data\":{\"status\":\"Closed\"}}'",
        "response": "{ \"id\": 7, \"data\": { \"status\": \"Closed\" } }",
    },
    {
        "method": "DELETE", "path": "/api/tabdesk/tables/{table_id}/rows/{row_id}",
        "auth": "Bearer / Cookie",
        "summary": "Delete one entry. A contributor may delete only their own; an editor any.",
        "usage": "curl -X DELETE __BASE__/api/tabdesk/tables/1/rows/7 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"Entry deleted\", \"id\": 7 }",
    },
    {
        "method": "GET", "path": "/api/tabdesk/tables/{table_id}/members", "auth": "Bearer / Cookie",
        "summary": "Who has explicit access to this table, plus every user who could be added. "
                   "Manager only. Remember the floor: on a workspace-visible table everyone with "
                   "tabdesk:read can already view it without appearing here.",
        "usage": "curl __BASE__/api/tabdesk/tables/1/members \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{\n  \"members\": [ { \"user_id\": 3, \"name\": \"Nishant\", \"access\": \"editor\" } ],\n"
                    "  \"candidates\": [ ... ]\n}",
    },
    {
        "method": "PUT", "path": "/api/tabdesk/tables/{table_id}/members/{user_id}",
        "auth": "Bearer / Cookie",
        "summary": "Grant or change someone's access: viewer · contributor · editor · manager. "
                   "Manager only. The table's creator cannot be demoted below manager.",
        "usage": "curl -X PUT __BASE__/api/tabdesk/tables/1/members/3 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                 "  -H 'Content-Type: application/json' \\\n  -d '{\"access\":\"contributor\"}'",
        "response": "{ \"table_id\": 1, \"members\": [ ... ] }",
    },
    {
        "method": "DELETE", "path": "/api/tabdesk/tables/{table_id}/members/{user_id}",
        "auth": "Bearer / Cookie",
        "summary": "Revoke an explicit grant. On a workspace-visible table this drops the person "
                   "back to view-only rather than blinding them — `still_visible` says which.",
        "usage": "curl -X DELETE __BASE__/api/tabdesk/tables/1/members/3 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"Access revoked\", \"still_visible\": true }",
    },
    {
        "method": "POST", "path": "/api/tabdesk/tables/{table_id}/views", "auth": "Bearer / Cookie",
        "summary": "Save the current filters, sort and grouping as a named view. Anyone who can "
                   "read the table may save a private one; only a manager may share one with "
                   "everybody (is_shared).",
        "usage": "curl -X POST __BASE__/api/tabdesk/tables/1/views \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                 "  -H 'Content-Type: application/json' \\\n"
                 "  -d '{\"name\":\"Open this month\",\"filters\":{\"status.eq\":\"Open\"},\"sort\":\"-amount\"}'",
        "response": "{ \"id\": 2, \"name\": \"Open this month\", \"is_shared\": true }",
    },
    {
        "method": "DELETE", "path": "/api/tabdesk/tables/{table_id}/views/{view_id}",
        "auth": "Bearer / Cookie",
        "summary": "Delete a saved view. Your own, or any of them with manager access.",
        "usage": "curl -X DELETE __BASE__/api/tabdesk/tables/1/views/2 \\\n  -H \"Authorization: Bearer $TOKEN\"",
        "response": "{ \"detail\": \"View deleted\", \"id\": 2 }",
    },
    {
        "method": "GET", "path": "/api/catalog", "auth": "Public",
        "summary": "This catalog — every endpoint with usage + response. Start here.",
        "usage": "curl __BASE__/api/catalog",
        "response": "{\n  \"base_url\": \"__BASE__\",\n  \"count\": 39,\n  \"endpoints\": [ ... ]\n}",
    },
]

@app.get("/api/catalog", response_model=ApiCatalogResponse)
def get_api_catalog(request: Request):
    # Derive the live base URL so copy-paste examples target the right host.
    base = str(request.base_url).rstrip("/")
    # Hand-written entries cover the bespoke routes; the rest are generated from
    # the entity registry so the catalogue cannot drift from the actual surface.
    catalog = API_CATALOG + crud.catalog_entries()
    endpoints = [
        ApiCatalogItem(
            method=e["method"],
            path=e["path"],
            auth=e["auth"],
            summary=e["summary"],
            usage=e["usage"].replace("__BASE__", base),
            response=e["response"].replace("__BASE__", base),
        )
        for e in catalog
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
        "usage": "hq-cli login --email meet@dotsai.in --password <your-password>",
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
        "usage": "hq-cli users create --email jane@acme.com --name \"Jane\" --role Operator [--password ...]",
        "description": "Create a new user. A strong password is auto-generated and printed once; pass --password to set your own.",
        "output": "User Jane (jane@acme.com) created successfully with role Operator!\nInitial password (share securely): tqf7Kd2pRxM_",
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

# ── TABDESK ──
# MUST be registered before crud.router below. That router owns the catch-all
# `/api/{key}`, and Starlette matches in registration order — registered after,
# every /api/tabdesk/... path would resolve as entity "tabdesk", row "tables".
app.include_router(tabdesk.router)

# ── GENERIC CRM CRUD ──
# Registered here, AFTER every hand-written /api route, because this router
# owns the catch-all `/api/{key}`. Starlette matches in registration order, so
# moving this line earlier would let /api/{key} swallow /api/users, /api/catalog
# and friends. It must also stay BEFORE the frontend catch-all below, which
# would otherwise match /api/customers/5 as an org/product/workspace path.
app.include_router(crud.router)

# Refuse to boot on a registry that lies: a key shadowed by a literal /api route
# above, or a field/ref/relation that does not exist in the schema.
crud.check_route_collisions(app)
crud.validate_registry()

# ── SERVING FRONTEND PAGES ──

# Resolve relative paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "frontend", "static")
LOGIN_FILE = os.path.join(BASE_DIR, "frontend", "login.html")
HOME_FILE = os.path.join(BASE_DIR, "frontend", "home.html")

class RevalidatingStaticFiles(StaticFiles):
    """Static files that must be re-checked on every request.

    Nothing here is content-hashed, so a deploy reuses the same URLs. With no
    Cache-Control header a browser applies its own heuristic freshness and keeps
    serving the OLD file — which meant a shipped CSS or JS change silently did
    not reach anyone until they happened to hard-refresh. That is a very
    expensive class of bug to chase, because the server is serving the fix.

    `no-cache` does not mean "do not store": the file is still cached, but the
    browser must revalidate, so an unchanged file costs a 304 and a changed one
    is picked up immediately.

    This header alone is NOT enough, and the reason is worth keeping: it only
    governs entries cached *after* it shipped. Browsers that had already stored
    a copy under the old header-less response keep applying their own heuristic
    freshness to it and never revalidate, so the fix cannot reach exactly the
    people who need it. `asset_url` below is what actually closes that door.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache, must-revalidate")
        return response


# ── cache-busting ───────────────────────────────────────────────────────────
# A component is fetched by the dc runtime with a plain `fetch`, which consults
# the HTTP cache. On 2026-07-26 that served a *pre-deploy* PortalPage.dc.html to
# every returning browser: the file on disk was correct, the response was
# correct, and the app still rendered the previous release's UI — silently, with
# no error anywhere, because a stale component is a complete valid component.
#
# Stamping the content hash into the URL makes a changed file a URL the cache
# has never seen, so the question of whether it revalidates stops mattering.

_ASSET_HASHES = {}


def asset_url(relative_path):
    """`/static/<path>?v=<content hash>`, recomputed when the file changes.

    Keyed on (size, mtime) so a normal request costs one stat, not a re-read of
    the file. A missing file returns the bare path rather than raising — a
    cache-busting helper must never be the thing that takes the page down.
    """
    full = os.path.join(STATIC_DIR, relative_path)
    try:
        stat = os.stat(full)
    except OSError:
        return "/static/%s" % relative_path

    key = (stat.st_size, stat.st_mtime_ns)
    digest = _ASSET_HASHES.get(relative_path, (None, None))
    if digest[0] != key:
        with open(full, "rb") as handle:
            digest = (key, hashlib.sha1(handle.read()).hexdigest()[:12])
        _ASSET_HASHES[relative_path] = digest
    return "/static/%s?v=%s" % (relative_path, digest[1])


def render_shell(path):
    """Read a frontend page and version every static URL it hands the runtime.

    Only the resource map is rewritten. Everything else in the page is left
    exactly as authored, so this cannot change behaviour it does not intend to.
    """
    with open(path, "r", encoding="utf-8") as handle:
        html = handle.read()
    for name in ("PortalPage.dc.html", "TabDeskPage.dc.html", "hq-responsive.css", "hq-responsive.js"):
        html = html.replace('"/static/%s"' % name, '"%s"' % asset_url(name))
    return html


# Mount frontend/static directory to serve CSS, JS, and Fonts
app.mount("/static", RevalidatingStaticFiles(directory=STATIC_DIR), name="static")

@app.get("/login", response_class=HTMLResponse)
def serve_login(request: Request, db: Session = Depends(get_db)):
    # Redirect into the app only for a VALID session. Checking mere cookie
    # presence here — while the client redirects to /login on any 401 — created
    # an infinite /login <-> dashboard reload loop for expired/invalid tokens.
    token = request.cookies.get("access_token")
    if token and get_user_from_token(token, db):
        return RedirectResponse(url="/z9s-ai/hq/hq/operations/dashboard")

    response = HTMLResponse(content=render_shell(LOGIN_FILE))
    if token:
        # Clear the stale/invalid cookie so it stops bouncing on every request.
        response.delete_cookie("access_token")
    return response

@app.get("/home", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def serve_home_redirect(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not (token and get_user_from_token(token, db)):
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
    tab: Optional[str] = None,
    db: Session = Depends(get_db)
):
    # Enforce a VALID session (not just cookie presence) to avoid redirect loops.
    token = request.cookies.get("access_token")
    if not (token and get_user_from_token(token, db)):
        return RedirectResponse(url="/login")

    return HTMLResponse(content=render_shell(HOME_FILE))
