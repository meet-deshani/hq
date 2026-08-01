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

# ── the lockout rail ────────────────────────────────────────────────────────
# The permission that gates the Permissions screen itself. If everyone loses it,
# nobody can ever grant it back and the organisation is locked out of its own
# authorisation for good — there is no recovery path short of a DB console.
GATE = "permissions:update"

# What an Admin keeps no matter what the grid says. Admin is the role that
# repairs a mistake; taking its ability to reach this screen away is the one
# edit that cannot be undone from inside the app.
ADMIN_FLOOR = {GATE, "permissions:read", "users:read", "users:update", "roles:read"}


def policy_is_custom(user_or_db, organisation_id=None):
    """Has anyone saved the Permissions screen yet?

    Returns False (code patterns win) when there is no policy row, which is the
    state every organisation starts in and most stay in.
    """
    from backend.models import PermissionPolicy  # local: avoid an import cycle

    db = getattr(user_or_db, "query", None) and user_or_db
    if db is None:
        return False
    row = db.query(PermissionPolicy).filter(
        PermissionPolicy.organisation_id == organisation_id
    ).first() if organisation_id is not None else db.query(PermissionPolicy).first()
    return bool(row and row.custom)


def role_codes(user, db=None):
    """The codes a user's ROLE grants, before their personal exceptions.

    Two sources, and which one wins is the whole point of PermissionPolicy:
      * nobody has saved the Permissions screen -> the code patterns in ROLES,
        so a grant change ships with a deploy rather than needing a migration;
      * somebody has -> the role_permissions rows, because the screen said it
        would become the authority and silently ignoring it would be a lie.
    """
    role = getattr(user, "role", None)
    if role is None:
        return set()

    if db is not None and policy_is_custom(db, getattr(user, "organisation_id", None)):
        codes = {p.code for p in (role.permissions or [])}
        # Admin keeps the keys to the building even if the grid says otherwise.
        if role.name == "Admin":
            codes |= ADMIN_FLOOR
        return codes

    spec = ROLES.get(role.name)
    if spec:
        return expand(spec["patterns"])
    # A hand-made role has no code patterns; its rows are all it has.
    return {p.code for p in (role.permissions or [])}


def overrides_for(user, db):
    """{code: 'allow'|'deny'} — this person's exceptions to their role."""
    from backend.models import UserPermissionOverride  # local: avoid a cycle

    if db is None or getattr(user, "id", None) is None:
        return {}
    rows = db.query(UserPermissionOverride).filter(
        UserPermissionOverride.user_id == user.id
    ).all()
    return {r.code: r.effect for r in rows}


def permissions_for(user, db=None):
    """The concrete permission codes a user holds.

    Role grants first, then that person's own exceptions on top:

        inherit (no row) -> whatever the role says
        allow            -> held, even if the role does not grant it
        deny             -> not held, even if the role does grant it

    Deny beats allow because the reason to write a deny is to take something
    away from someone whose role hands it out, and a rule that loses to the
    thing it exists to override is not a rule.

    `db` is optional because almost every caller is a route with no session to
    hand over. Those callers get the set resolved at authentication time and
    cached on the user by `auth.get_current_user` — which is what makes an
    exception actually bite on the routes that enforce it, rather than only
    showing up in the UI. Passing `db` explicitly recomputes, which is what the
    admin screens do when previewing somebody else's access.
    """
    if db is None:
        cached = getattr(user, "_effective_permissions", None)
        if cached is not None:
            return set(cached)

    codes = role_codes(user, db)
    if db is None:
        return codes

    effects = overrides_for(user, db)
    if not effects:
        return codes

    codes = set(codes)
    for code, effect in effects.items():
        if effect == "allow":
            codes.add(code)
        elif effect == "deny":
            codes.discard(code)

    # The floor is a floor: an exception cannot lock an Admin out either.
    if getattr(getattr(user, "role", None), "name", None) == "Admin":
        codes |= ADMIN_FLOOR
    return codes


def has(user, entity_key, action):
    return ("%s:%s" % (entity_key, action)) in permissions_for(user)


def require(user, entity_key, action):
    """Raise 403 unless the user holds <entity_key>:<action>.

    The message distinguishes a role that never granted this from a personal
    exception that took it away. Without that, an admin asked "why can't Nishant
    delete a customer?" goes and reads the Partner role, finds that it DOES allow
    delete, and has nowhere left to look — the answer was on the Exceptions
    screen the whole time.
    """
    if has(user, entity_key, action):
        return True

    code = "%s:%s" % (entity_key, action)
    role = getattr(user, "role", None)
    role_name = getattr(role, "name", "no role")

    # Would the role alone have allowed it? If so, an exception is the reason.
    spec = ROLES.get(role_name)
    role_would_allow = code in expand(spec["patterns"]) if spec else code in {
        p.code for p in (getattr(role, "permissions", None) or [])
    }
    if role_would_allow:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You have a permission exception that blocks '%s %s'. Your role (%s) "
                   "would otherwise allow it — ask an admin to check Exceptions."
                   % (ACTION_LABELS.get(action, action).lower(), _label(entity_key), role_name),
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Your role (%s) cannot %s %s." % (role_name, action, _label(entity_key)),
    )


def can_map(user, db=None):
    """{entity_key: {action: bool}} — used by the UI to hide what it cannot do."""
    held = permissions_for(user, db)
    return {
        key: {action: ("%s:%s" % (key, action)) in held for action in ACTIONS}
        for key in entity_keys()
    }


# ── lockout prevention ──────────────────────────────────────────────────────

def who_can_open_the_gate(db, organisation_id, proposed_role_codes=None,
                          proposed_overrides=None):
    """Active users who would still hold `permissions:update` after a change.

    Called BEFORE a save is committed, with the proposed state, so a change that
    would leave nobody able to open the Permissions screen can be refused while
    it is still refusable. Afterwards there is no way back: the permission that
    grants the permission is the one being removed.

    `proposed_role_codes`   {role_name: set(codes)} replacing what those roles grant.
    `proposed_overrides`    {user_id: {code: 'allow'|'deny'}} replacing those users'
                            exceptions. A user absent from the dict keeps theirs.
    """
    from backend.models import User, UserPermissionOverride

    proposed_role_codes = proposed_role_codes or {}
    proposed_overrides = proposed_overrides or {}

    users = db.query(User).filter(
        User.organisation_id == organisation_id, User.status == "Active"
    ).all()

    survivors = []
    for user in users:
        role = getattr(user, "role", None)
        role_name = getattr(role, "name", None)

        if role_name in proposed_role_codes:
            codes = set(proposed_role_codes[role_name])
        else:
            codes = role_codes(user, db)
        if role_name == "Admin":
            codes |= ADMIN_FLOOR

        if user.id in proposed_overrides:
            effects = proposed_overrides[user.id]
        else:
            effects = {
                r.code: r.effect
                for r in db.query(UserPermissionOverride).filter(
                    UserPermissionOverride.user_id == user.id
                ).all()
            }
        for code, effect in effects.items():
            if effect == "allow":
                codes.add(code)
            elif effect == "deny":
                codes.discard(code)
        if role_name == "Admin":
            codes |= ADMIN_FLOOR

        if GATE in codes:
            survivors.append(user)
    return survivors


def refuse_if_locking_everyone_out(db, organisation_id, proposed_role_codes=None,
                                   proposed_overrides=None):
    """Raise 400 rather than let a save orphan the Permissions screen."""
    survivors = who_can_open_the_gate(
        db, organisation_id, proposed_role_codes, proposed_overrides
    )
    if not survivors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That would leave nobody able to open this screen, and there is no "
                   "way to grant it back from inside the app. Leave at least one "
                   "active person holding '%s'." % GATE,
        )
    return survivors


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

    # Once somebody has saved the Permissions screen, these tables are the
    # authority and this function must not touch the grants. Re-applying the
    # code patterns here would revert every edit on the next deploy — silently,
    # because a deploy is not something anyone connects to their permissions
    # changing. Roles are still CREATED below if missing; only the grants are
    # left alone.
    custom = policy_is_custom(db, organisation_id)

    for name, spec in ROLES.items():
        role = db.query(Role).filter(
            Role.organisation_id == organisation_id, Role.name == name
        ).first()
        if not role:
            role = Role(organisation_id=organisation_id, name=name, description=spec["description"])
            db.add(role)
            db.flush()
            # A role created after the matrix was customised has no rows yet, so
            # seed it from code once. Without this it would exist with no grants
            # at all, which reads as "this role can do nothing".
            role.permissions = [catalogue[c] for c in sorted(expand(spec["patterns"])) if c in catalogue]
            continue
        if not role.description:
            role.description = spec["description"]

        if custom:
            continue

        granted = [catalogue[c] for c in sorted(expand(spec["patterns"])) if c in catalogue]
        # Assigning the whole list keeps a role's grants in step with the code
        # above — a role that loses a grant here loses it in the database too.
        role.permissions = granted

    db.commit()
    logger.info(
        "Permissions synced: %d codes across %d roles%s",
        len(wanted), len(ROLES),
        " (grants left to the saved matrix)" if custom else "",
    )
