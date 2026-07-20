#!/usr/bin/env python3
import os
import sys
import json
import click
import requests

API_URL = os.getenv("HQ_API_URL", "http://localhost:8000")
TOKEN_FILE = os.path.expanduser("~/.hq_token")

def get_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()
    return None

def get_headers():
    token = get_token()
    if not token:
        click.echo("Error: Not logged in. Run 'hq-cli login' first.", err=True)
        sys.exit(1)
    return {"Authorization": f"Bearer {token}"}

def format_table(headers, rows):
    # Find max width for each column
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, val in enumerate(row):
            widths[idx] = max(widths[idx], len(str(val)))
            
    # Print header
    header_str = " | ".join(f"{str(headers[i]).ljust(widths[i])}" for i in range(len(headers)))
    click.echo(header_str)
    click.echo("-" * (sum(widths) + 3 * (len(headers) - 1)))
    
    # Print rows
    for row in rows:
        row_str = " | ".join(f"{str(row[i]).ljust(widths[i])}" for i in range(len(row)))
        click.echo(row_str)

@click.group()
def cli():
    """Z9S-AI HQ CLI - Automation tool for AI agents and developers."""
    pass

@cli.command()
@click.option("--email", prompt=True, help="Admin Email")
@click.option("--password", prompt=True, hide_input=True, help="Password")
def login(email, password):
    """Authenticate with the HQ backend and save JWT locally."""
    try:
        res = requests.post(
            f"{API_URL}/api/auth/login",
            json={"email": email, "password": password}
        )
        if res.status_code == 200:
            token = res.json()["access_token"]
            with open(TOKEN_FILE, "w") as f:
                f.write(token)
            click.echo("Successfully logged in! Token saved to ~/.hq_token")
        else:
            click.echo(f"Login failed: {res.json().get('detail', 'Unknown error')}", err=True)
    except Exception as e:
        click.echo(f"Connection error: {e}", err=True)

@cli.command()
def logout():
    """Clear local authentication token."""
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        click.echo("Logged out successfully.")
    else:
        click.echo("Already logged out.")

@cli.command()
def status():
    """Fetch and display current HQ dashboard metrics."""
    try:
        res = requests.get(f"{API_URL}/api/dashboard/stats", headers=get_headers())
        if res.status_code == 200:
            stats = res.json()["stats"]
            click.echo("\n=== HQ Dashboard Status ===")
            headers = ["Metric", "Value", "Trend / Info"]
            rows = [[s["l"], s["v"], s["d"]] for s in stats]
            format_table(headers, rows)
            click.echo("")
        else:
            click.echo(f"Error fetching status: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

# User commands group
@cli.group(name="users")
def users_group():
    """Manage platform users."""
    pass

@users_group.command(name="list")
@click.option("--role", help="Filter users by role name")
def list_users(role):
    """List all registered users."""
    try:
        params = {}
        if role:
            params["role"] = role
        res = requests.get(f"{API_URL}/api/users", headers=get_headers(), params=params)
        if res.status_code == 200:
            users = res.json()
            headers = ["ID", "Name", "Email", "Role", "Status"]
            rows = [
                [u["id"], u["name"], u["email"], u["role"]["name"] if u["role"] else "None", u["status"]]
                for u in users
            ]
            click.echo("\n--- Registered Users ---")
            format_table(headers, rows)
            click.echo("")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@users_group.command(name="create")
@click.option("--email", required=True, help="User email address")
@click.option("--name", required=True, help="User display name")
@click.option("--role", default="Admin", help="Role name (default: Admin)")
@click.option("--status", default="Active", type=click.Choice(["Active", "Invited", "Disabled"]), help="User status")
def create_user(email, name, role, status):
    """Create a new user."""
    try:
        payload = {"email": email, "name": name, "role_name": role, "status": status, "password": "password123"}
        res = requests.post(f"{API_URL}/api/users", headers=get_headers(), json=payload)
        if res.status_code == 200:
            u = res.json()
            click.echo(f"User {u['name']} ({u['email']}) created successfully with role {role}!")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@users_group.command(name="delete")
@click.argument("user_id", type=int)
def delete_user(user_id):
    """Delete a user by their numeric ID."""
    try:
        res = requests.delete(f"{API_URL}/api/users/{user_id}", headers=get_headers())
        if res.status_code == 200:
            click.echo(f"User ID {user_id} deleted successfully.")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

# Roles and Permissions commands group
@cli.group(name="roles")
def roles_group():
    """Manage roles and permissions."""
    pass

@roles_group.command(name="list")
def list_roles():
    """List all configured roles."""
    try:
        res = requests.get(f"{API_URL}/api/roles", headers=get_headers())
        if res.status_code == 200:
            roles = res.json()
            headers = ["ID", "Role Name", "Description"]
            rows = [[r["id"], r["name"], r["description"] or ""] for r in roles]
            click.echo("\n--- Configured Roles ---")
            format_table(headers, rows)
            click.echo("")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@roles_group.command(name="create")
@click.option("--name", required=True, help="Role name")
@click.option("--description", help="Role description")
def create_role(name, description):
    """Create a new role."""
    try:
        res = requests.post(
            f"{API_URL}/api/roles",
            headers=get_headers(),
            json={"name": name, "description": description}
        )
        if res.status_code == 200:
            click.echo(f"Role '{name}' created successfully!")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@roles_group.command(name="permissions")
def list_permissions():
    """List all available permission policies."""
    try:
        res = requests.get(f"{API_URL}/api/permissions", headers=get_headers())
        if res.status_code == 200:
            perms = res.json()
            headers = ["ID", "Permission Name", "Code Tag", "Description"]
            rows = [[p["id"], p["name"], p["code"], p["description"] or ""] for p in perms]
            click.echo("\n--- Available Permissions ---")
            format_table(headers, rows)
            click.echo("")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@roles_group.command(name="grant")
@click.option("--role-id", required=True, type=int, help="Role ID")
@click.option("--permissions", required=True, help="Comma-separated permission code tags")
def grant_permissions(role_id, permissions):
    """Grant comma-separated list of permissions to a role."""
    try:
        codes = [c.strip() for c in permissions.split(",") if c.strip()]
        res = requests.post(
            f"{API_URL}/api/roles/{role_id}/permissions",
            headers=get_headers(),
            json=codes
        )
        if res.status_code == 200:
            click.echo(f"Permissions updated successfully for Role ID {role_id}.")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

# Organisations command group
@cli.group(name="orgs")
def orgs_group():
    """Manage organisations."""
    pass

@orgs_group.command(name="list")
def list_orgs():
    """List all registered organisations."""
    try:
        res = requests.get(f"{API_URL}/api/organisations", headers=get_headers())
        if res.status_code == 200:
            orgs = res.json()
            headers = ["ID", "Name", "Slug", "Industry", "Initials", "Color"]
            rows = [[o["id"], o["name"], o["slug"], o["industry"] or "", o["initials"] or "", o["color"]] for o in orgs]
            click.echo("\n--- Registered Organisations ---")
            format_table(headers, rows)
            click.echo("")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@orgs_group.command(name="create")
@click.option("--name", required=True, help="Organisation name")
@click.option("--slug", required=True, help="Unique organisation slug")
@click.option("--industry", help="Industry sector")
@click.option("--initials", help="Initials logo tag")
@click.option("--color", default="#C8B6FF", help="Brand color hex")
def create_org(name, slug, industry, initials, color):
    """Create a new organisation."""
    try:
        payload = {"name": name, "slug": slug, "industry": industry, "initials": initials, "color": color}
        res = requests.post(f"{API_URL}/api/organisations", headers=get_headers(), json=payload)
        if res.status_code == 200:
            o = res.json()
            click.echo(f"Organisation '{o['name']}' ({o['slug']}) created successfully!")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

# Products command group
@cli.group(name="products")
def products_group():
    """Manage products."""
    pass

@products_group.command(name="list")
@click.option("--org-id", type=int, help="Filter by organisation ID")
def list_products(org_id):
    """List all configured products."""
    try:
        params = {}
        if org_id:
            params["organisation_id"] = org_id
        res = requests.get(f"{API_URL}/api/products", headers=get_headers(), params=params)
        if res.status_code == 200:
            prods = res.json()
            headers = ["ID", "Name", "Code", "Org ID", "Status"]
            rows = [[p["id"], p["name"], p["code"], p["organisation_id"] or "", p["status"]] for p in prods]
            click.echo("\n--- Configured Products ---")
            format_table(headers, rows)
            click.echo("")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@products_group.command(name="create")
@click.option("--name", required=True, help="Product name")
@click.option("--code", required=True, help="Unique product code")
@click.option("--org-id", type=int, help="Organisation ID")
@click.option("--description", help="Product description")
def create_product(name, code, org_id, description):
    """Create a new product."""
    try:
        payload = {"name": name, "code": code, "organisation_id": org_id, "description": description}
        res = requests.post(f"{API_URL}/api/products", headers=get_headers(), json=payload)
        if res.status_code == 200:
            p = res.json()
            click.echo(f"Product '{p['name']}' ({p['code']}) created successfully!")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

# Workspaces command group
@cli.group(name="workspaces")
def workspaces_group():
    """Manage workspaces."""
    pass

@workspaces_group.command(name="list")
@click.option("--org-id", type=int, help="Filter by organisation ID")
@click.option("--product-id", type=int, help="Filter by product ID")
def list_workspaces(org_id, product_id):
    """List all active workspaces."""
    try:
        params = {}
        if org_id:
            params["organisation_id"] = org_id
        if product_id:
            params["product_id"] = product_id
        res = requests.get(f"{API_URL}/api/workspaces", headers=get_headers(), params=params)
        if res.status_code == 200:
            wss = res.json()
            headers = ["ID", "Name", "Slug", "Icon", "Org ID", "Product ID", "Status"]
            rows = [[w["id"], w["name"], w["slug"] or "", w["icon"] or "", w["organisation_id"] or "", w["product_id"] or "", w["status"]] for w in wss]
            click.echo("\n--- Active Workspaces ---")
            format_table(headers, rows)
            click.echo("")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@workspaces_group.command(name="create")
@click.option("--name", required=True, help="Workspace name")
@click.option("--slug", help="Workspace slug")
@click.option("--icon", default="grid", help="Icon name")
@click.option("--org-id", type=int, help="Organisation ID")
@click.option("--product-id", type=int, help="Product ID")
def create_workspace(name, slug, icon, org_id, product_id):
    """Create a new workspace."""
    try:
        payload = {"name": name, "slug": slug, "icon": icon, "organisation_id": org_id, "product_id": product_id}
        res = requests.post(f"{API_URL}/api/workspaces", headers=get_headers(), json=payload)
        if res.status_code == 200:
            w = res.json()
            click.echo(f"Workspace '{w['name']}' created successfully!")
        else:
            click.echo(f"Error: {res.json().get('detail')}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

if __name__ == "__main__":
    cli()

