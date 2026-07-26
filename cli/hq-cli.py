#!/usr/bin/env python3
import os
import sys
import json
import click
import requests

API_URL = os.getenv("HQ_API_URL", "http://localhost:8000")
TOKEN_FILE = os.path.expanduser("~/.hq_token")

# Every request carries this so the audit trail can tell a CLI write apart from
# a browser write (backend/audit.py::actor_kind).
CLIENT_TAG = "cli"

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
    return {"Authorization": f"Bearer {token}", "X-HQ-Client": CLIENT_TAG}

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
    """Z9S-AI HQ CLI - Automation tool for AI agents and developers.

    The generic commands (ls / get / create / update / delete / remark /
    remarks) work on any entity in the backend registry. Run 'hq-cli entities'
    to see them and 'hq-cli describe <entity>' for its fields and saved views.
    """
    pass

@cli.command()
@click.option("--email", prompt=True, help="Admin Email")
@click.option("--password", prompt=True, hide_input=True, help="Password")
def login(email, password):
    """Authenticate with the HQ backend and save JWT locally."""
    try:
        res = requests.post(
            f"{API_URL}/api/auth/login",
            json={"email": email, "password": password},
            headers={"X-HQ-Client": CLIENT_TAG},
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
@click.option("--password", default=None, help="Set an explicit password (default: server auto-generates a strong one)")
def create_user(email, name, role, status, password):
    """Create a new user. A strong password is auto-generated unless --password is given."""
    try:
        payload = {"email": email, "name": name, "role_name": role, "status": status}
        if password:
            payload["password"] = password
        res = requests.post(f"{API_URL}/api/users", headers=get_headers(), json=payload)
        if res.status_code == 200:
            u = res.json()
            click.echo(f"User {u['name']} ({u['email']}) created successfully with role {role}!")
            if u.get("initial_password"):
                click.echo(f"Initial password (share securely): {u['initial_password']}")
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

# ---------------------------------------------------------------------------
# Registry-driven surface
#
# Everything below is built from GET /api/meta/entities at runtime. No entity
# name is hardcoded, so an entity added to backend/registry.py is immediately
# addressable here (ls / get / create / update / delete / remark / remarks /
# describe) with no change to this file.
# ---------------------------------------------------------------------------

def fail(msg):
    click.echo(f"Error: {msg}", err=True)
    sys.exit(1)

def error_detail(res):
    """The server's own explanation, if it gave one."""
    try:
        body = res.json()
    except ValueError:
        return (res.text or "").strip()[:300] or f"HTTP {res.status_code}"
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, list):  # FastAPI validation errors
            return "; ".join(str(d.get("msg", d)) for d in detail)
        if detail:
            return str(detail)
    return json.dumps(body)[:300]

def api(method, path, auth=True, **kwargs):
    """Single request path for the registry commands: auth, client tag, errors."""
    headers = {"X-HQ-Client": CLIENT_TAG}
    if auth is True:
        headers.update(get_headers())
    elif auth == "optional":
        token = get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    try:
        res = requests.request(method, f"{API_URL}{path}", headers=headers, **kwargs)
    except requests.RequestException as e:
        fail(f"Connection error: {e}")
    if res.status_code in (200, 201):
        try:
            return res.json()
        except ValueError:
            fail(f"Server returned a non-JSON response ({res.status_code}).")
    if res.status_code in (401, 403):
        fail("Not authorised - your token is missing or expired. Run 'hq-cli login'.")
    if res.status_code == 404:
        fail(f"Not found: {error_detail(res)}")
    fail(error_detail(res))

_REGISTRY = None

def registry():
    """The entity registry, fetched once per invocation."""
    global _REGISTRY
    if _REGISTRY is None:
        data = api("GET", "/api/meta/entities", auth="optional")
        _REGISTRY = {e["key"]: e for e in data.get("entities", [])}
    return _REGISTRY

def entity_or_fail(key):
    reg = registry()
    ent = reg.get(key)
    if not ent:
        fail(f"Unknown entity '{key}'.\nAvailable entities: {', '.join(sorted(reg))}")
    return ent

def fields_of(ent):
    return {f["k"]: f for f in ent.get("fields", [])}

def specs_of(ent):
    """Every registry-known key for the entity - writable fields plus list columns."""
    out = dict(fields_of(ent))
    for col in ent.get("columns", []):
        out.setdefault(col["k"], col)
    return out

def coerce(spec, key, raw):
    """Turn a `key=value` string into the type the registry declares."""
    ftype = (spec or {}).get("type", "text")
    if raw == "" or raw.lower() in ("null", "none"):
        return None
    if ftype == "boolean":
        if raw.lower() in ("1", "true", "yes", "y", "on"):
            return True
        if raw.lower() in ("0", "false", "no", "n", "off"):
            return False
        fail(f"'{key}' is a boolean - use true or false, got '{raw}'.")
    if ftype == "ref":
        try:
            return int(raw)
        except ValueError:
            fail(f"'{key}' is a reference to {spec.get('ref')} - pass a numeric id, got '{raw}'.")
    if ftype in ("number", "money", "percent"):
        try:
            return int(raw) if ftype == "number" and "." not in raw else float(raw)
        except ValueError:
            fail(f"'{key}' is a {ftype} - pass a number, got '{raw}'.")
    return raw  # text, textarea, select, email, phone, url, date, datetime

def parse_sets(ent, pairs, allowed=None, what="field"):
    """--set key=value ... -> a typed payload, rejecting unknown keys."""
    specs = fields_of(ent) if allowed is None else allowed
    payload = {}
    for pair in pairs:
        if "=" not in pair:
            fail(f"'{pair}' is not key=value.")
        key, raw = pair.split("=", 1)
        key = key.strip()
        if key not in specs:
            fail(f"Unknown {what} '{key}' for {ent['key']}.\n"
                 f"Valid keys: {', '.join(sorted(specs))}")
        payload[key] = coerce(specs[key], key, raw.strip())
    return payload

def cell(spec, row):
    """Display value for one column - refs resolve to their label."""
    key = spec["k"]
    val = row.get(key)
    if spec.get("type") == "ref":
        label = (row.get("_refs") or {}).get(key)
        if label:
            return label
    if val is None or val == "":
        return ""
    if isinstance(val, bool):
        return "yes" if val else "no"
    if spec.get("type") == "money" and isinstance(val, (int, float)):
        return f"{val:,.2f}"
    if spec.get("type") == "percent" and isinstance(val, (int, float)):
        return f"{val:g}%"
    text = str(val)
    if spec.get("type") in ("date", "datetime"):
        text = text[:10] if spec["type"] == "date" else text[:16].replace("T", " ")
    return text if len(text) <= 42 else text[:41] + "…"

def emit_json(data):
    click.echo(json.dumps(data, indent=2, default=str))


@cli.command(name="entities")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
def list_entities(as_json):
    """List every entity published by the backend registry."""
    reg = registry()
    if as_json:
        emit_json(list(reg.values()))
        return
    headers = ["Key", "Label", "Plural", "Workspace", "Module", "Path", "Fields", "Views"]
    rows = [
        [e["key"], e["label"], e["plural"], e.get("workspace", ""), e.get("module", ""),
         e["path"], len(e.get("fields", [])), len(e.get("saved_views", []))]
        for e in reg.values()
    ]
    click.echo(f"\n--- Registry Entities ({len(rows)}) ---")
    format_table(headers, rows)
    click.echo("")


@cli.command(name="describe")
@click.argument("entity")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
def describe_entity(entity, as_json):
    """Show an entity's columns, fields, saved views and actions."""
    ent = entity_or_fail(entity)
    if as_json:
        emit_json(ent)
        return

    click.echo(f"\n=== {ent['plural']} ({ent['key']}) ===")
    click.echo(f"Path        : {ent['path']}")
    click.echo(f"Label       : {ent['label']}  |  Workspace: {ent.get('workspace', '')}"
               f"  |  Module: {ent.get('module', '')}")
    click.echo(f"Title field : {ent.get('title_field', '')}")
    if ent.get("scope"):
        click.echo(f"Scope       : {json.dumps(ent['scope'])}")
    if ent.get("search"):
        click.echo(f"Searchable  : {', '.join(ent['search'])}")

    click.echo("\n--- List columns ---")
    format_table(
        ["Key", "Label", "Type", "Ref"],
        [[c["k"], c["label"], c.get("type", ""), c.get("ref", "")] for c in ent.get("columns", [])],
    )

    click.echo("\n--- Fields (valid --set keys) ---")
    rows = []
    for f in ent.get("fields", []):
        extra = f.get("ref", "")
        if f.get("options"):
            extra = "|".join(str(o) for o in f["options"])
        rows.append([
            f["k"], f["label"], f.get("type", ""),
            "yes" if f.get("required") else "",
            "" if f.get("default") is None else str(f["default"]),
            f.get("group", ""), extra,
        ])
    format_table(["Key", "Label", "Type", "Required", "Default", "Group", "Ref / Options"], rows)

    views = ent.get("saved_views", [])
    if views:
        click.echo("\n--- Saved views ---")
        format_table(["Name", "Filters"],
                     [[v["name"], json.dumps(v.get("filters", {}))] for v in views])

    if ent.get("relations"):
        click.echo("\n--- Related lists ---")
        format_table(["Key", "Label", "Entity", "FK"],
                     [[r["key"], r["label"], r["entity"], r.get("fk", "")] for r in ent["relations"]])

    if ent.get("actions"):
        click.echo("\n--- Actions ---")
        format_table(["Key", "Label", "Method", "Path"],
                     [[a["key"], a["label"], a.get("method", ""), a.get("path", "")]
                      for a in ent["actions"]])
    click.echo("")


@cli.command(name="ls")
@click.argument("entity")
@click.option("--view", help="Saved view name from the registry")
@click.option("--search", help="Full-text search across the entity's search fields")
@click.option("--limit", type=int, default=50, show_default=True, help="Max rows")
@click.option("--offset", type=int, default=0, help="Rows to skip")
@click.option("--filter", "filters", multiple=True, metavar="COL=VAL",
              help="Column filter, repeatable (use COL=null for empty)")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
def ls_rows(entity, view, search, limit, offset, filters, as_json):
    """List rows of any registry entity."""
    ent = entity_or_fail(entity)

    params = {"limit": limit, "offset": offset}
    if search:
        params["q"] = search
    if view:
        names = [v["name"] for v in ent.get("saved_views", [])]
        match = next((n for n in names if n.lower() == view.lower()), None)
        if not match:
            fail(f"Unknown view '{view}' for {ent['key']}.\nAvailable views: {', '.join(names) or 'none'}")
        params["view"] = match

    specs = specs_of(ent)
    specs.setdefault("overdue", {"k": "overdue", "type": "boolean"})
    for key, value in parse_sets(ent, filters, allowed=specs, what="filter column").items():
        if value is None:
            params[key] = "null"
        elif isinstance(value, bool):
            params[key] = "true" if value else "false"
        else:
            params[key] = value

    data = api("GET", f"/api/{ent['key']}", params=params)
    if as_json:
        emit_json(data)
        return

    columns = ent.get("columns", [])
    headers = ["ID"] + [c["label"] for c in columns]
    rows = [[r.get("id")] + [cell(c, r) for c in columns] for r in data.get("rows", [])]
    click.echo(f"\n--- {ent['plural']} ---")
    if rows:
        format_table(headers, rows)
    else:
        click.echo("(no rows)")
    click.echo(f"\n{data.get('count', 0)} of {data.get('total', 0)} row(s), offset {data.get('offset', 0)}\n")


@cli.command(name="get")
@click.argument("entity")
@click.argument("row_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
def get_row(entity, row_id, as_json):
    """Show one row with its related lists, remarks and audit trail."""
    ent = entity_or_fail(entity)
    data = api("GET", f"/api/{ent['key']}/{row_id}")
    if as_json:
        emit_json(data)
        return

    click.echo(f"\n=== {ent['label']} #{row_id} - {data.get('_label')} ===")
    rows = []
    for f in ent.get("fields", []):
        value = cell(f, data)
        if value != "":
            rows.append([f.get("group", ""), f["label"], value])
    format_table(["Group", "Field", "Value"], rows)

    for rel in (data.get("_related") or {}).values():
        labels = [r.get("_label") or f"#{r.get('id')}" for r in rel.get("rows", [])]
        click.echo(f"\n{rel['label']} ({len(labels)}): "
                   + (", ".join(str(l) for l in labels[:6]) + ("..." if len(labels) > 6 else "") or "-"))

    remarks = data.get("_remarks") or []
    if remarks:
        click.echo(f"\n--- Remarks ({len(remarks)}) ---")
        format_table(["When", "Kind", "Source", "Author", "Remark"],
                     [[(r.get("created_at") or "")[:16].replace("T", " "), r.get("kind", ""),
                       r.get("source", ""), r.get("author") or "", (r.get("body") or "")[:60]]
                      for r in remarks[-5:]])

    entries = data.get("_audit") or []
    if entries:
        click.echo(f"\n--- Recent audit ({len(entries)}) ---")
        format_table(["When", "Action", "Actor", "Kind"],
                     [[(a.get("created_at") or "")[:19].replace("T", " "), a.get("action", ""),
                       a.get("actor") or "", a.get("actor_kind") or ""] for a in entries[:5]])
    click.echo("")


@cli.command(name="create")
@click.argument("entity")
@click.option("--set", "sets", multiple=True, required=True, metavar="KEY=VALUE",
              help="Field value, repeatable (see 'hq-cli describe <entity>')")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
def create_row(entity, sets, as_json):
    """Create a row of any registry entity."""
    ent = entity_or_fail(entity)
    payload = parse_sets(ent, sets)
    data = api("POST", f"/api/{ent['key']}", json=payload)
    if as_json:
        emit_json(data)
        return
    click.echo(f"{ent['label']} #{data['id']} '{data.get('_label')}' created.")


@cli.command(name="update")
@click.argument("entity")
@click.argument("row_id", type=int)
@click.option("--set", "sets", multiple=True, required=True, metavar="KEY=VALUE",
              help="Field value, repeatable")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
def update_row(entity, row_id, sets, as_json):
    """Update fields on one row."""
    ent = entity_or_fail(entity)
    payload = parse_sets(ent, sets)
    data = api("PATCH", f"/api/{ent['key']}/{row_id}", json=payload)
    if as_json:
        emit_json(data)
        return
    click.echo(f"{ent['label']} #{row_id} '{data.get('_label')}' updated: "
               f"{', '.join(sorted(payload))}.")


@cli.command(name="delete")
@click.argument("entity")
@click.argument("row_id", type=int)
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt")
def delete_row(entity, row_id, yes):
    """Delete one row."""
    ent = entity_or_fail(entity)
    if not yes:
        click.confirm(f"Delete {ent['label']} #{row_id}?", abort=True)
    data = api("DELETE", f"/api/{ent['key']}/{row_id}")
    click.echo(data.get("detail", f"{ent['label']} {row_id} deleted") + f" (id {row_id}).")


@cli.command(name="remark")
@click.argument("entity")
@click.argument("row_id", type=int)
@click.argument("body")
@click.option("--kind", type=click.Choice(["remark", "note", "reply", "correction"]),
              default="remark", show_default=True, help="Remark kind")
@click.option("--ref", "external_ref", help="External reference (makes the append idempotent)")
def add_remark(entity, row_id, body, kind, external_ref):
    """Append a remark to a row. Remarks are append-only."""
    ent = entity_or_fail(entity)
    payload = {"body": body, "kind": kind}
    if external_ref:
        payload["external_ref"] = external_ref
    data = api("POST", f"/api/{ent['key']}/{row_id}/remarks", json=payload)
    if data.get("duplicate"):
        click.echo(f"Remark already recorded (id {data['id']}) - external ref '{external_ref}'.")
    else:
        click.echo(f"Remark #{data['id']} added to {ent['label']} #{row_id}.")


@cli.command(name="remarks")
@click.argument("entity")
@click.argument("row_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
def list_remarks(entity, row_id, as_json):
    """Show the remark history of a row."""
    ent = entity_or_fail(entity)
    data = api("GET", f"/api/{ent['key']}/{row_id}/remarks")
    if as_json:
        emit_json(data)
        return
    remarks = data.get("remarks", [])
    click.echo(f"\n--- Remarks on {ent['label']} #{row_id} ({len(remarks)}) ---")
    if remarks:
        format_table(
            ["ID", "When", "Kind", "Source", "Author", "Ref", "Remark"],
            [[r["id"], (r.get("created_at") or "")[:16].replace("T", " "), r.get("kind", ""),
              r.get("source", ""), r.get("author") or "", r.get("external_ref") or "",
              (r.get("body") or "")[:70]] for r in remarks],
        )
    else:
        click.echo("(no remarks)")
    click.echo("")


@cli.command(name="convert-lead")
@click.argument("lead_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
def convert_lead(lead_id, as_json):
    """Convert a lead into a customer (the lead is kept and stamped won)."""
    # The path comes from the registry's declared action, not from a constant.
    ent = entity_or_fail("leads")
    action = next((a for a in ent.get("actions", []) if a["key"] == "convert"), None)
    if not action:
        fail("The registry declares no 'convert' action on leads.")
    data = api(action.get("method", "POST"), action["path"].format(id=lead_id), json={})
    if as_json:
        emit_json(data)
        return
    customer = data.get("customer") or {}
    prefix = "Lead already converted" if data.get("already_converted") else "Lead converted"
    click.echo(f"{prefix}: customer #{customer.get('id')} '{customer.get('display_name')}'.")


@cli.command(name="audit")
@click.option("--entity-type", help="Audit entity_type, e.g. tasks / parties / leads")
@click.option("--entity-id", type=int, help="Restrict to one row id")
@click.option("--limit", type=int, default=25, show_default=True, help="Max entries")
@click.option("--offset", type=int, default=0, help="Entries to skip")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
def audit_trail(entity_type, entity_id, limit, offset, as_json):
    """Show the platform-wide change history."""
    params = {"limit": limit, "offset": offset}
    if entity_type:
        params["entity_type"] = entity_type
    if entity_id is not None:
        params["entity_id"] = entity_id
    data = api("GET", "/api/audit", params=params)
    if as_json:
        emit_json(data)
        return
    entries = data.get("entries", [])
    click.echo(f"\n--- Audit trail ({len(entries)}) ---")
    if entries:
        format_table(
            ["When", "Action", "Entity type", "Row", "Label", "Actor", "Actor kind"],
            [[(a.get("created_at") or "")[:19].replace("T", " "), a.get("action", ""),
              a.get("entity_type", ""), a.get("entity_id", ""), (a.get("entity_label") or "")[:30],
              a.get("actor") or "", a.get("actor_kind") or ""] for a in entries],
        )
    else:
        click.echo("(no entries)")
    click.echo("")


if __name__ == "__main__":
    cli()

