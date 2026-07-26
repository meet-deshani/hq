"""TabDesk authorisation — the security boundary of the subsystem.

Every TabDesk route resolves access through this module before it does anything.
The UI hides affordances a user lacks; these functions are what actually refuse.

Two layers, because one is not enough:

**Layer 1, the global gate** — ordinary HQ permissions (``tabdesk:read``,
``tabdesk:create``, ``tabdesk:update``, ``tabdesk:delete``) answer *may this
person use TabDesk at all, and may they make a new table*. They come from the
user's role in ``permissions.py`` like every other permission in the platform.

**Layer 2, per-table access** — one of four ordered levels answering *what may
they do with THIS table*:

    viewer      → read rows
    contributor → + add entries, and edit/delete their OWN
    editor      → + edit/delete anyone's
    manager     → + change columns, settings and sharing

The floor, and why it is set there: **a table with ``visibility="workspace"`` is
readable by anyone holding ``tabdesk:read``, with no membership row.** That
follows the rule already written into ``permissions.py`` — *read is generous,
delete is not* — and it satisfies the standing requirement that Nishant and
Hemish see everything without anyone having to remember to share with them. A
membership row only ever raises a user ABOVE that floor; it never lowers them.
``visibility="private"`` removes the floor entirely.

Two overrides sit above the scheme, both deliberate:

* A holder of ``tabdesk:delete`` (Admin, Partner) is ``manager`` on every table.
  Someone has to be able to fix a table whose only manager has left the company.
* The creator is permanently ``manager`` on their own table. Without this, two
  managers can demote each other and lock everyone out.
"""

from fastapi import HTTPException, status
from sqlalchemy import or_

from backend import permissions
from backend.tabdesk_models import ACCESS_LEVELS, TabDeskMember, TabDeskTable

# What each level is allowed to do, as a single source of truth. The router asks
# `allows(access, "rows:create")` rather than re-deriving the ladder.
CAPABILITIES = {
    "viewer": {"rows:read"},
    "contributor": {"rows:read", "rows:create", "rows:update:own", "rows:delete:own"},
    "editor": {
        "rows:read", "rows:create", "rows:update:own", "rows:delete:own",
        "rows:update:any", "rows:delete:any",
    },
    "manager": {
        "rows:read", "rows:create", "rows:update:own", "rows:delete:own",
        "rows:update:any", "rows:delete:any",
        "schema:manage", "table:manage", "members:manage", "views:manage",
    },
}

ACCESS_LABELS = {
    "viewer": "Can view",
    "contributor": "Can add entries",
    "editor": "Can edit everything",
    "manager": "Full control",
}


def _rank(access):
    return ACCESS_LEVELS.index(access) if access in ACCESS_LEVELS else -1


def _strongest(*levels):
    """The highest of several applicable levels. None if none apply."""
    found = [lvl for lvl in levels if lvl in ACCESS_LEVELS]
    return max(found, key=_rank) if found else None


def is_platform_admin(user):
    """Holds TabDesk at the platform level — manager on every table.

    Keyed on ``tabdesk:delete`` because deletion is the permission the platform
    already treats as the irreversible one, and the roles that hold it (Admin,
    Partner) are exactly the ones that should be able to repair any table.
    """
    return permissions.has(user, "tabdesk", "delete")


def access_for(db, user, table):
    """The caller's effective access to one table, or None if they have none.

    This is the only function that decides visibility. Everything else in the
    subsystem asks it.
    """
    if user is None:
        return None

    if is_platform_admin(user):
        return "manager"

    # No global read means no TabDesk at all, whatever the table says.
    if not permissions.has(user, "tabdesk", "read"):
        return None

    creator = "manager" if table.created_by_id and table.created_by_id == user.id else None

    membership = (
        db.query(TabDeskMember)
        .filter(TabDeskMember.table_id == table.id, TabDeskMember.user_id == user.id)
        .first()
    )
    granted = membership.access if membership and membership.access in ACCESS_LEVELS else None

    # The workspace floor. A private table has no floor — only the creator and
    # explicit members reach it.
    floor = "viewer" if table.visibility == "workspace" else None

    return _strongest(creator, granted, floor)


def allows(access, capability):
    return capability in CAPABILITIES.get(access, set())


def require_access(db, user, table, capability):
    """Raise unless the caller's access to this table covers `capability`.

    A user with no access at all gets 404, not 403: confirming that a private
    table exists is itself a leak, and the table is genuinely not there as far as
    they are concerned.
    """
    access = access_for(db, user, table)
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such table.")
    if not allows(access, capability):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your access to '%s' (%s) does not allow that."
                   % (table.name, ACCESS_LABELS.get(access, access)),
        )
    return access


def require_row_write(db, user, table, row, action):
    """Authorise editing or deleting one row. `action` is "update" or "delete".

    This is where `contributor` differs from `editor`: a contributor may only
    touch rows they created, which is the shape almost every real data-collection
    table wants — a field team that files entries without being able to rewrite
    each other's.
    """
    access = access_for(db, user, table)
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such table.")

    if allows(access, "rows:%s:any" % action):
        return access
    if allows(access, "rows:%s:own" % action) and row.created_by_id == user.id:
        return access

    if allows(access, "rows:%s:own" % action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only %s entries you created. Ask a manager of '%s' for edit access."
                   % (action, table.name),
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Your access to '%s' (%s) does not allow you to %s entries."
               % (table.name, ACCESS_LABELS.get(access, access), action),
    )


def visible_tables_query(db, user):
    """A query for every table the caller may see. None means "nothing".

    Written as a query rather than a filter over fetched rows so the sidebar does
    not load every table in the organisation to decide what to show.
    """
    if user is None or not permissions.has(user, "tabdesk", "read"):
        return None

    query = db.query(TabDeskTable).filter(TabDeskTable.status != "Deleted")
    if is_platform_admin(user):
        return query

    mine = db.query(TabDeskMember.table_id).filter(TabDeskMember.user_id == user.id)
    return query.filter(
        or_(
            TabDeskTable.visibility == "workspace",
            TabDeskTable.created_by_id == user.id,
            TabDeskTable.id.in_(mine),
        )
    )


def require_global(user, action):
    """The layer-1 gate, for actions that are not about a specific table."""
    return permissions.require(user, "tabdesk", action)
