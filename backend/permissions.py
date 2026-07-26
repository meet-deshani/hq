"""Authorisation — who may do what, enforced on every route.

The model is the platform's own: a permission is a string ``<entity>:<action>``,
roles hold sets of them, and every CRUD route checks one before it runs. Grants
support wildcards (``*:read``, ``customers:*``, ``*:*``) so a role reads as a
short, reviewable list rather than a hundred rows.

The rule that shaped the defaults: **read is generous, delete is not.** Meet's
requirement is that Nishant and Hemish see everything — so every role above
Viewer reads everything. Deleting is different: it is the one irreversible
action, and an advisor having it was a real hole, not a feature.

Permissions are derived from the entity registry, so a new entity is
automatically covered instead of being accidentally unprotected.
"""

import logging

from fastapi import HTTPException, status

from backend import registry
from backend.models import Permission, Role

logger = logging.getLogger("permissions")

# `remark` is separate from `update` on purpose: an advisor should be able to
# add to a record's history without being able to alter the record.
ACTIONS = ["read", "create", "update", "delete", "remark"]

ACTION_LABELS = {
    "read": "View",
    "create": "Create",
    "update": "Edit",
    "delete": "Delete",
    "remark": "Comment on",
}

# Platform surfaces that predate the registry and keep their own routes.
PLATFORM_ENTITIES = {
    "users": "Users",
    "roles": "Roles",
    "permissions": "Permissions",
    "organisations": "Organisations",
    "products": "Products",
    "workspaces": "Workspaces",
    "feedback": "Feedback",
    "audit": "Audit log",
    # TabDesk is one permissioned surface here, not one per user-defined table:
    # tables are created at runtime, so a per-table permission row would mean
    # writing to the catalogue on every table creation. This gate answers "may
    # you use TabDesk, and may you make a table"; who may do what to a PARTICULAR
    # table is per-table membership in backend/tabdesk_access.py.
    "tabdesk": "TabDesk tables",
}

# Registry entities that configure the CRM rather than hold business records.
CONFIG_ENTITIES = {
    "party-groups", "lead-sources", "pipelines", "pipeline-stages",
    "lost-reasons", "item-categories",
}


def entity_keys():
    """Every key that can be permissioned — registry entities plus platform."""
    return sorted({e["key"] for e in registry.ENTITIES} | set(PLATFORM_ENTITIES))


def business_keys():
    return sorted({e["key"] for e in registry.ENTITIES} - CONFIG_ENTITIES)


def all_codes():
    return ["%s:%s" % (key, action) for key in entity_keys() for action in ACTIONS]


def _labels():
    """key -> display label, disambiguated where two keys share a name.

    The CRM catalog's `catalog-products` and the platform's own `products` are
    both "Products". `permissions.name` is unique, so an ambiguous label is not
    merely confusing — it makes the catalogue fail to seed.
    """
    raw = {}
    for e in registry.ENTITIES:
        raw[e["key"]] = e["plural"]
    for key, label in PLATFORM_ENTITIES.items():
        raw[key] = label

    seen = {}
    for key, label in raw.items():
        seen.setdefault(label, []).append(key)

    out = {}
    for key, label in raw.items():
        out[key] = "%s (%s)" % (label, key) if len(seen[label]) > 1 else label
    return out


LABELS = _labels()


def _label(key):
    return LABELS.get(key, key)


def describe(code):
    key, _, action = code.partition(":")
    return "%s %s" % (ACTION_LABELS.get(action, action.title()), _label(key))


# ── role definitions ────────────────────────────────────────────────────────
# Each entry is a list of grant patterns. Order does not matter; a permission is
# held if ANY pattern matches. There are no deny rules — absence is denial.

def _grants():
    business = business_keys()
    config = sorted(CONFIG_ENTITIES)
    platform = sorted(PLATFORM_ENTITIES)

    return {
        "Admin": {
            "description": "Full control, including platform configuration and deletion.",
            "patterns": ["*:*"],
        },
        "Partner": {
            "description": (
                "Runs the business: full access to customers, leads, projects and tasks, "
                "including deletion. Cannot change platform configuration."
            ),
            "patterns": (
                ["*:read", "*:remark"]
                + ["%s:%s" % (k, a) for k in business for a in ("create", "update", "delete")]
                + ["%s:%s" % (k, a) for k in config for a in ("create", "update")]
                # TabDesk is a platform key, so the `business` sweep above misses
                # it. Granted explicitly: a Partner runs the business and must be
                # able to make and retire tables. Holding tabdesk:delete also
                # makes them a manager on every table — the documented override
                # for a table whose only manager has left.
                + ["tabdesk:create", "tabdesk:update", "tabdesk:delete"]
            ),
        },
        "Advisor": {
            "description": (
                "Sees everything and can comment on anything, and owns their own tasks. "
                "Cannot delete anything, and cannot edit other people's records."
            ),
            "patterns": (
                ["*:read", "*:remark"]
                + ["tasks:create", "tasks:update", "feedback:create"]
            ),
        },
        "Operator": {
            "description": "Day-to-day record keeping. No deletion, no configuration.",
            "patterns": (
                ["*:read", "*:remark"]
                + ["%s:%s" % (k, a) for k in business for a in ("create", "update")]
                # Can make their own tables and manage the ones they own, but
                # NOT delete — which also keeps them from becoming a manager on
                # everyone else's tables. That distinction is the whole reason
                # the override is keyed on tabdesk:delete.
                + ["tabdesk:create", "tabdesk:update"]
            ),
        },
        "Viewer": {
            "description": "Read-only across the platform, and can report a problem.",
            "patterns": ["*:read", "feedback:create"],
        },
    }


ROLES = _grants()


def expand(patterns):
    """Turn grant patterns into the concrete set of codes they cover."""
    keys = entity_keys()
    out = set()
    for pattern in patterns:
        key_pat, _, action_pat = pattern.partition(":")
        for key in keys:
            if key_pat not in ("*", key):
                continue
            for action in ACTIONS:
                if action_pat in ("*", action):
                    out.add("%s:%s" % (key, action))
    return out


# ── runtime checks ──────────────────────────────────────────────────────────

def permissions_for(user):
    """The concrete permission codes a user holds, from their role's grants."""
    role = getattr(user, "role", None)
    if role is None:
        return set()
    # Roles the platform defines get their patterns from code, so a grant change
    # ships with the code rather than needing a data migration. A hand-made role
    # falls back to whatever rows are linked to it.
    spec = ROLES.get(role.name)
    if spec:
        return expand(spec["patterns"])
    return {p.code for p in (role.permissions or [])}


def has(user, entity_key, action):
    return ("%s:%s" % (entity_key, action)) in permissions_for(user)


def require(user, entity_key, action):
    """Raise 403 unless the user holds <entity_key>:<action>."""
    if has(user, entity_key, action):
        return True
    role_name = getattr(getattr(user, "role", None), "name", "no role")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Your role (%s) cannot %s %s." % (role_name, action, _label(entity_key)),
    )


def can_map(user):
    """{entity_key: {action: bool}} — used by the UI to hide what it cannot do."""
    held = permissions_for(user)
    return {
        key: {action: ("%s:%s" % (key, action)) in held for action in ACTIONS}
        for key in entity_keys()
    }


# ── seeding ─────────────────────────────────────────────────────────────────

def seed(db, organisation_id):
    """Sync the permission catalogue and role grants. Idempotent.

    The catalogue is derived from the registry, so it is rebuilt rather than
    accumulated: codes that no longer correspond to an entity are removed, which
    keeps the Permissions screen honest instead of showing dead policies.
    """
    wanted = set(all_codes())
    existing = {p.code: p for p in db.query(Permission).all()}

    # DELETE-then-flush BEFORE inserting. `permissions.name` is unique, and a
    # retired code can share a display name with a new one — the original
    # catalogue's `users:write` was "Create Users", which is exactly what
    # `users:create` is called now. SQLAlchemy flushes inserts before deletes
    # within one flush, so doing both together raised a UNIQUE violation on any
    # database that already had the old rows. That is every deployed database,
    # and the caller swallowed it, leaving the org with NO roles at all.
    for code, perm in existing.items():
        if code not in wanted:
            db.delete(perm)
    db.flush()

    for code in sorted(wanted - set(existing)):
        db.add(Permission(name=describe(code), code=code, description=describe(code)))
    db.flush()

    catalogue = {p.code: p for p in db.query(Permission).all()}

    for name, spec in ROLES.items():
        role = db.query(Role).filter(
            Role.organisation_id == organisation_id, Role.name == name
        ).first()
        if not role:
            role = Role(organisation_id=organisation_id, name=name, description=spec["description"])
            db.add(role)
            db.flush()
        elif not role.description:
            role.description = spec["description"]

        granted = [catalogue[c] for c in sorted(expand(spec["patterns"])) if c in catalogue]
        # Assigning the whole list keeps a role's grants in step with the code
        # above — a role that loses a grant here loses it in the database too.
        role.permissions = granted

    db.commit()
    logger.info("Permissions synced: %d codes across %d roles", len(wanted), len(ROLES))
