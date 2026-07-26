"""TabDesk — the API.

Every route here is generated from column metadata rather than written per table,
which is the same property that makes the registry-driven CRM usable by an agent:
read one description, drive everything.

Registered in ``main.py`` **before** ``crud.router``. That router owns the
catch-all ``/api/{key}``, and Starlette matches in registration order, so
registering later would make ``/api/tabdesk/tables`` resolve as entity
``tabdesk``, row ``tables`` — a 404 with a confusing message, or worse, a 200 of
the wrong shape.

Authorisation is never done inline; every route calls into
``backend/tabdesk_access.py``. Read that module before changing anything here.
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional

from backend import audit, permissions, registry, tabdesk_access as access, tabdesk_sql as tsql
from backend.auth import get_current_user
from backend.database import get_db
from backend.models import User
from backend.tabdesk_models import (
    ACCESS_LEVELS, VISIBILITIES, TabDeskColumn, TabDeskMember, TabDeskRow,
    TabDeskSavedView, TabDeskTable,
)

logger = logging.getLogger("tabdesk")

router = APIRouter(prefix="/api/tabdesk", tags=["TabDesk"])

MAX_LIMIT = 500


# ── request bodies ──────────────────────────────────────────────────────────

class TableIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = None
    icon: Optional[str] = "grid"
    accent: Optional[str] = "#C8B6FF"
    group_name: Optional[str] = "Tables"
    visibility: Optional[str] = "workspace"
    # Optional starting schema, so "New table" can create something usable in one
    # request instead of leaving the user on an empty page with no columns.
    columns: Optional[List[Dict[str, Any]]] = None


class TablePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    description: Optional[str] = None
    icon: Optional[str] = None
    accent: Optional[str] = None
    group_name: Optional[str] = None
    visibility: Optional[str] = None
    position: Optional[int] = None


class ColumnIn(BaseModel):
    label: str = Field(min_length=1, max_length=150)
    type: str = "text"
    required: bool = False
    is_primary: bool = False
    options: Optional[List[str]] = None
    default_value: Optional[Any] = None
    help: Optional[str] = None
    width: Optional[str] = None
    ref_kind: Optional[str] = None
    ref_target: Optional[str] = None


class ColumnPatch(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=150)
    type: Optional[str] = None
    required: Optional[bool] = None
    is_primary: Optional[bool] = None
    options: Optional[List[str]] = None
    default_value: Optional[Any] = None
    help: Optional[str] = None
    width: Optional[str] = None
    position: Optional[int] = None
    ref_kind: Optional[str] = None
    ref_target: Optional[str] = None


class MemberIn(BaseModel):
    access: str


class ViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    filters: Optional[Dict[str, Any]] = None
    sort: Optional[str] = None
    group_by: Optional[str] = None
    visible_columns: Optional[List[str]] = None
    is_shared: bool = True


# ── helpers ─────────────────────────────────────────────────────────────────

def _slug(raw, fallback="table"):
    out = re.sub(r"[^a-z0-9]+", "-", str(raw or "").lower()).strip("-")
    return out[:100] or fallback


def _column_key(label, taken):
    """A stable JSON key from a label, unique within the table.

    Never recomputed after creation: every existing row is stored under this key,
    so deriving it from a mutable label on each read would orphan values the
    moment someone renamed a column.
    """
    base = re.sub(r"[^a-z0-9]+", "_", str(label or "").lower()).strip("_")[:60] or "field"
    if base[0].isdigit():
        base = "f_" + base
    key, n = base, 2
    while key in taken:
        key = "%s_%d" % (base, n)
        n += 1
    return key


def _get_table(db, table_id):
    table = db.query(TabDeskTable).filter(TabDeskTable.id == table_id).first()
    if not table or table.status == "Deleted":
        raise HTTPException(status_code=404, detail="No such table.")
    return table


def _columns(db, table_id):
    return (
        db.query(TabDeskColumn)
        .filter(TabDeskColumn.table_id == table_id)
        .order_by(TabDeskColumn.position, TabDeskColumn.id)
        .all()
    )


def _public_column(column):
    return {
        "id": column.id,
        "key": column.key,
        "label": column.label,
        "type": column.type,
        "position": column.position,
        "required": bool(column.required),
        "is_primary": bool(column.is_primary),
        "options": list(column.options or []),
        "default_value": column.default_value,
        "help": column.help,
        "width": column.width or "1fr",
        "ref_kind": column.ref_kind,
        "ref_target": column.ref_target,
        "modal_only": column.type in tsql.MODAL_ONLY,
        "ops": tsql.TYPES.get(column.type, {}).get("ops", []),
    }


def _public_table(table, my_access=None, columns=None, row_count=None):
    out = {
        "id": table.id,
        "name": table.name,
        "slug": table.slug,
        "description": table.description,
        "icon": table.icon,
        "accent": table.accent,
        "group_name": table.group_name or "Tables",
        "visibility": table.visibility,
        "position": table.position or 0,
        "created_by_id": table.created_by_id,
        "created_at": table.created_at.isoformat() + "Z" if table.created_at else None,
    }
    if my_access is not None:
        out["my_access"] = my_access
        # The UI renders from these rather than re-deriving the ladder, so the
        # affordances it shows cannot drift from what the routes enforce.
        out["can"] = {
            capability: access.allows(my_access, capability)
            for capability in (
                "rows:read", "rows:create", "rows:update:any", "rows:delete:any",
                "rows:update:own", "rows:delete:own",
                "schema:manage", "table:manage", "members:manage", "views:manage",
            )
        }
    if columns is not None:
        out["columns"] = [_public_column(c) for c in columns]
    if row_count is not None:
        out["row_count"] = row_count
    return out


def _validate_column_spec(spec_type, options, ref_kind, ref_target, label):
    """Refuse a column definition that cannot work, at definition time.

    A select with no choices or a relation pointing nowhere would be accepted
    silently and then fail on every single entry — much cheaper to catch here.
    """
    if spec_type not in tsql.TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unknown column type '%s'. Available: %s"
                   % (spec_type, ", ".join(sorted(tsql.TYPES))),
        )
    if spec_type in ("select", "multiselect") and not options:
        raise HTTPException(
            status_code=400,
            detail="'%s' is a %s, so it needs at least one choice." % (label, spec_type),
        )
    if spec_type == "relation":
        if ref_kind not in ("tabdesk", "entity"):
            raise HTTPException(
                status_code=400,
                detail="'%s' is a relation, so ref_kind must be 'tabdesk' or 'entity'." % label,
            )
        if not ref_target:
            raise HTTPException(
                status_code=400, detail="'%s' is a relation and needs a ref_target." % label,
            )
        if ref_kind == "entity" and ref_target not in registry.BY_KEY:
            raise HTTPException(
                status_code=400,
                detail="'%s' points at unknown entity '%s'." % (label, ref_target),
            )


def _resolve_labels(db, columns, rows):
    """Labels for every user and relation id referenced by these rows.

    Returned alongside the rows as ``_labels`` so the grid can render "Sustro
    Oils" instead of 41 without N+1 fetching. A missing target resolves to
    "(deleted)" rather than erroring: relation ids live in JSON and cannot have a
    foreign key, so a dangling id is a state the UI must survive, not a bug.
    """
    wanted = {}
    for column in columns:
        if column.type == "user":
            wanted.setdefault(("users", None), set())
        elif column.type == "relation":
            wanted.setdefault((column.ref_kind, column.ref_target), set())

    for row in rows:
        data = row.data or {}
        for column in columns:
            value = data.get(column.key)
            if value is None:
                continue
            if column.type == "user":
                wanted[("users", None)].add(value)
            elif column.type == "relation":
                wanted[(column.ref_kind, column.ref_target)].update(value or [])

    out = {}
    for (kind, target), ids in wanted.items():
        ids = {i for i in ids if isinstance(i, int)}
        if not ids:
            continue
        bucket = out.setdefault("users" if kind == "users" else "%s:%s" % (kind, target), {})

        if kind == "users":
            for user in db.query(User).filter(User.id.in_(ids)).all():
                bucket[str(user.id)] = user.name
        elif kind == "tabdesk":
            try:
                other_id = int(target)
            except (TypeError, ValueError):
                continue
            other_cols = _columns(db, other_id)
            primary = next((c for c in other_cols if c.is_primary), other_cols[0] if other_cols else None)
            for other in db.query(TabDeskRow).filter(TabDeskRow.id.in_(ids)).all():
                label = (other.data or {}).get(primary.key) if primary else None
                bucket[str(other.id)] = str(label) if label not in (None, "") else "Row %d" % other.id
        elif kind == "entity":
            ent = registry.BY_KEY.get(target)
            if not ent:
                continue
            model, title = ent["model"], ent.get("title_field") or "name"
            for record in db.query(model).filter(model.id.in_(ids)).all():
                bucket[str(record.id)] = str(getattr(record, title, None) or "#%d" % record.id)
    return out


def _public_row(row):
    return {
        "id": row.id,
        "data": row.data or {},
        "created_by_id": row.created_by_id,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None,
    }


def _apply_values(columns, payload, existing=None, partial=False):
    """Coerce a submitted entry against the column definitions.

    Keys with no column are dropped, not stored: that is what makes deleting a
    column non-destructive to the rest of the row, and lets a re-added column
    recover its old values.
    """
    by_key = {c.key: c for c in columns}
    data = dict(existing or {})
    problems = []

    for column in columns:
        if partial and column.key not in payload:
            continue
        raw = payload.get(column.key)
        if raw is None and not partial and column.default_value is not None:
            raw = column.default_value
        try:
            data[column.key] = tsql.coerce(column, raw)
        except tsql.BadValue as exc:
            problems.append(str(exc))

    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))

    return {k: v for k, v in data.items() if k in by_key}


# ── tables ──────────────────────────────────────────────────────────────────

@router.get("/meta")
def tabdesk_meta(current_user: User = Depends(get_current_user)):
    """The column type catalogue and access ladder — what the UI builds from."""
    access.require_global(current_user, "read")
    return {
        "types": tsql.public_types(),
        "access_levels": [
            {"value": level, "label": access.ACCESS_LABELS[level]} for level in ACCESS_LEVELS
        ],
        "visibilities": VISIBILITIES,
        # Relation targets: other TabDesk tables are listed per-request by the UI;
        # these are the real HQ entities a table can point at.
        "entities": [
            {"key": e["key"], "label": e["plural"]}
            for e in registry.ENTITIES if not e.get("read_only")
        ],
        "can_create": permissions.has(current_user, "tabdesk", "create"),
    }


@router.get("/tables")
def list_tables(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every table the caller may see, with row counts, grouped for the sidebar."""
    access.require_global(current_user, "read")
    query = access.visible_tables_query(db, current_user)
    if query is None:
        return {"count": 0, "tables": [], "groups": [], "can_create": False}

    tables = query.order_by(TabDeskTable.group_name, TabDeskTable.position, TabDeskTable.name).all()

    # One grouped count rather than a query per table — the sidebar shows counts,
    # and N tables must not mean N+1 queries.
    counts = dict(
        db.query(TabDeskRow.table_id, func.count(TabDeskRow.id))
        .filter(TabDeskRow.table_id.in_([t.id for t in tables] or [0]))
        .group_by(TabDeskRow.table_id)
        .all()
    )

    out, groups = [], {}
    for table in tables:
        my = access.access_for(db, current_user, table)
        if my is None:
            continue
        public = _public_table(table, my_access=my, row_count=counts.get(table.id, 0))
        out.append(public)
        groups.setdefault(table.group_name or "Tables", []).append(public["id"])

    return {
        "count": len(out),
        "tables": out,
        "groups": [{"name": name, "table_ids": ids} for name, ids in groups.items()],
        "can_create": permissions.has(current_user, "tabdesk", "create"),
    }


@router.post("/tables", status_code=status.HTTP_201_CREATED)
def create_table(
    body: TableIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access.require_global(current_user, "create")

    if body.visibility not in VISIBILITIES:
        raise HTTPException(status_code=400, detail="visibility must be one of %s" % VISIBILITIES)

    base, slug, n = _slug(body.name), _slug(body.name), 2
    while db.query(TabDeskTable).filter(
        TabDeskTable.organisation_id == current_user.organisation_id,
        TabDeskTable.slug == slug,
    ).first():
        slug = "%s-%d" % (base, n)
        n += 1

    table = TabDeskTable(
        organisation_id=current_user.organisation_id,
        name=body.name.strip(),
        slug=slug,
        description=body.description,
        icon=body.icon or "grid",
        accent=body.accent or "#C8B6FF",
        group_name=(body.group_name or "Tables").strip() or "Tables",
        visibility=body.visibility or "workspace",
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    db.add(table)
    db.flush()

    # A table with no columns cannot hold an entry, so a caller that supplies no
    # schema gets a single text column to start from rather than a dead page.
    specs = body.columns or [{"label": "Name", "type": "text", "is_primary": True}]
    taken = set()
    for position, spec in enumerate(specs):
        label = str(spec.get("label") or "Field").strip()
        spec_type = spec.get("type") or "text"
        options = spec.get("options") or []
        _validate_column_spec(spec_type, options, spec.get("ref_kind"), spec.get("ref_target"), label)
        key = _column_key(label, taken)
        taken.add(key)
        db.add(TabDeskColumn(
            table_id=table.id, key=key, label=label, type=spec_type, position=position,
            required=bool(spec.get("required")),
            is_primary=bool(spec.get("is_primary")) or position == 0,
            options=options, default_value=spec.get("default_value"),
            help=spec.get("help"), width=spec.get("width") or "1fr",
            ref_kind=spec.get("ref_kind"), ref_target=str(spec.get("ref_target") or "") or None,
        ))
    db.commit()
    db.refresh(table)

    _enforce_single_primary(db, table.id)
    tsql.sync_view(db, table, _columns(db, table.id))

    audit.record(
        db, action="create", entity_type="tabdesk_tables", entity_id=table.id,
        entity_label=table.name, actor=current_user, request=request,
        organisation_id=table.organisation_id, commit=True,
    )
    return _public_table(table, my_access="manager", columns=_columns(db, table.id), row_count=0)


@router.get("/tables/{table_id}")
def get_table(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = _get_table(db, table_id)
    my = access.require_access(db, current_user, table, "rows:read")
    columns = _columns(db, table_id)
    count = db.query(func.count(TabDeskRow.id)).filter(TabDeskRow.table_id == table_id).scalar()

    out = _public_table(table, my_access=my, columns=columns, row_count=count or 0)
    out["saved_views"] = [
        {
            "id": v.id, "name": v.name, "filters": v.filters or {}, "sort": v.sort,
            "group_by": v.group_by, "visible_columns": v.visible_columns,
            "is_shared": bool(v.is_shared), "created_by_id": v.created_by_id,
        }
        for v in db.query(TabDeskSavedView)
        .filter(TabDeskSavedView.table_id == table_id)
        .order_by(TabDeskSavedView.position, TabDeskSavedView.id)
        .all()
        if v.is_shared or v.created_by_id == current_user.id
    ]
    if access.allows(my, "members:manage"):
        out["members"] = _members_payload(db, table_id)
    return out


@router.patch("/tables/{table_id}")
def update_table(
    table_id: int,
    body: TablePatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = _get_table(db, table_id)
    access.require_access(db, current_user, table, "table:manage")

    before = audit.snapshot(table)
    payload = body.model_dump(exclude_unset=True)
    if "visibility" in payload and payload["visibility"] not in VISIBILITIES:
        raise HTTPException(status_code=400, detail="visibility must be one of %s" % VISIBILITIES)

    for field, value in payload.items():
        setattr(table, field, value)
    table.updated_by_id = current_user.id
    db.commit()
    db.refresh(table)

    audit.record(
        db, action="update", entity_type="tabdesk_tables", entity_id=table.id,
        entity_label=table.name, actor=current_user, request=request,
        changes=audit.diff(before, audit.snapshot(table)),
        organisation_id=table.organisation_id, commit=True,
    )
    my = access.access_for(db, current_user, table)
    return _public_table(table, my_access=my, columns=_columns(db, table_id))


@router.delete("/tables/{table_id}")
def delete_table(
    table_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a table and everything in it. Needs table management AND the global
    delete permission — deleting a table with 300 entries is the most destructive
    thing in this subsystem, so it takes both layers, not one."""
    table = _get_table(db, table_id)
    access.require_access(db, current_user, table, "table:manage")
    permissions.require(current_user, "tabdesk", "delete")

    label, org = table.name, table.organisation_id
    count = db.query(func.count(TabDeskRow.id)).filter(TabDeskRow.table_id == table_id).scalar()

    tsql.drop_view(db, table)
    db.delete(table)
    db.commit()

    audit.record(
        db, action="delete", entity_type="tabdesk_tables", entity_id=table_id,
        entity_label=label, actor=current_user, request=request,
        changes={"rows_deleted": {"from": count or 0, "to": 0}},
        organisation_id=org, commit=True,
    )
    return {"detail": "Table deleted", "id": table_id, "rows_deleted": count or 0}


# ── columns ─────────────────────────────────────────────────────────────────

def _enforce_single_primary(db, table_id):
    """Exactly one primary column — it is the row's title in the grid and modal."""
    columns = _columns(db, table_id)
    if not columns:
        return
    primaries = [c for c in columns if c.is_primary]
    if len(primaries) == 1:
        return
    keep = primaries[0] if primaries else columns[0]
    for column in columns:
        column.is_primary = column.id == keep.id
    db.commit()


@router.post("/tables/{table_id}/columns", status_code=status.HTTP_201_CREATED)
def add_column(
    table_id: int,
    body: ColumnIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = _get_table(db, table_id)
    access.require_access(db, current_user, table, "schema:manage")

    options = body.options or []
    _validate_column_spec(body.type, options, body.ref_kind, body.ref_target, body.label)

    existing = _columns(db, table_id)
    column = TabDeskColumn(
        table_id=table_id,
        key=_column_key(body.label, {c.key for c in existing}),
        label=body.label.strip(),
        type=body.type,
        position=(max([c.position for c in existing]) + 1) if existing else 0,
        required=body.required,
        is_primary=body.is_primary or not existing,
        options=options,
        default_value=body.default_value,
        help=body.help,
        width=body.width or "1fr",
        ref_kind=body.ref_kind,
        ref_target=str(body.ref_target) if body.ref_target else None,
    )
    db.add(column)
    db.commit()
    db.refresh(column)

    if body.is_primary:
        for other in existing:
            other.is_primary = False
        db.commit()
    _enforce_single_primary(db, table_id)
    tsql.sync_view(db, table, _columns(db, table_id))

    audit.record(
        db, action="update", entity_type="tabdesk_tables", entity_id=table_id,
        entity_label=table.name, actor=current_user, request=request,
        changes={"column_added": {"from": None, "to": "%s (%s)" % (column.label, column.type)}},
        organisation_id=table.organisation_id, commit=True,
    )
    return _public_column(column)


@router.patch("/tables/{table_id}/columns/{column_id}")
def update_column(
    table_id: int,
    column_id: int,
    body: ColumnPatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change a column. A type change re-coerces every existing value.

    Re-coercing is the whole point: leaving old values in the previous type's
    shape would break both the SQL view's cast and any filter on the column —
    a Postgres numeric cast over a leftover string raises for every reader at
    once. A value that cannot be converted is set to null rather than blocking
    the change, and the count of those is reported back so the manager knows.
    """
    table = _get_table(db, table_id)
    access.require_access(db, current_user, table, "schema:manage")

    column = db.query(TabDeskColumn).filter(
        TabDeskColumn.id == column_id, TabDeskColumn.table_id == table_id
    ).first()
    if not column:
        raise HTTPException(status_code=404, detail="No such column.")

    payload = body.model_dump(exclude_unset=True)
    new_type = payload.get("type", column.type)
    new_options = payload.get("options", column.options) or []
    _validate_column_spec(
        new_type, new_options,
        payload.get("ref_kind", column.ref_kind),
        payload.get("ref_target", column.ref_target),
        payload.get("label", column.label),
    )

    before = audit.snapshot(column)
    retyped = new_type != column.type

    for field, value in payload.items():
        if field == "ref_target" and value is not None:
            value = str(value)
        setattr(column, field, value)
    # `key` is deliberately absent from ColumnPatch — see _column_key.
    db.commit()

    cleared = 0
    if retyped:
        rows = db.query(TabDeskRow).filter(TabDeskRow.table_id == table_id).all()
        for row in rows:
            data = dict(row.data or {})
            if column.key not in data:
                continue
            try:
                data[column.key] = tsql.coerce(column, data.get(column.key))
            except tsql.BadValue:
                data[column.key] = None
                cleared += 1
            row.data = data
        db.commit()

    if payload.get("is_primary"):
        for other in _columns(db, table_id):
            if other.id != column.id:
                other.is_primary = False
        db.commit()
    _enforce_single_primary(db, table_id)
    tsql.sync_view(db, table, _columns(db, table_id))

    audit.record(
        db, action="update", entity_type="tabdesk_tables", entity_id=table_id,
        entity_label=table.name, actor=current_user, request=request,
        changes=audit.diff(before, audit.snapshot(column)),
        organisation_id=table.organisation_id, commit=True,
    )
    out = _public_column(column)
    out["values_cleared"] = cleared
    return out


@router.delete("/tables/{table_id}/columns/{column_id}")
def delete_column(
    table_id: int,
    column_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a column. Row values are left in place, not stripped.

    An orphaned key is ignored on read and dropped on the next write, which makes
    this recoverable: re-adding a column with the same generated key brings the
    old values back. Deleting the last column is refused — a table with no
    columns cannot hold an entry.
    """
    table = _get_table(db, table_id)
    access.require_access(db, current_user, table, "schema:manage")

    columns = _columns(db, table_id)
    column = next((c for c in columns if c.id == column_id), None)
    if not column:
        raise HTTPException(status_code=404, detail="No such column.")
    if len(columns) <= 1:
        raise HTTPException(
            status_code=400,
            detail="A table needs at least one column. Add another before removing this one.",
        )

    label = column.label
    db.delete(column)
    db.commit()

    _enforce_single_primary(db, table_id)
    tsql.sync_view(db, table, _columns(db, table_id))

    audit.record(
        db, action="update", entity_type="tabdesk_tables", entity_id=table_id,
        entity_label=table.name, actor=current_user, request=request,
        changes={"column_removed": {"from": label, "to": None}},
        organisation_id=table.organisation_id, commit=True,
    )
    return {"detail": "Column removed", "id": column_id}


# ── rows ────────────────────────────────────────────────────────────────────

@router.get("/tables/{table_id}/rows")
def list_rows(
    table_id: int,
    request: Request,
    q: Optional[str] = None,
    sort: Optional[str] = None,
    group: Optional[str] = None,
    view: Optional[int] = None,
    limit: int = Query(default=100, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rows, filtered and sorted.

    Filters arrive as ``f.<column key>.<op>=<value>`` query parameters, which
    keeps a filter set expressible in a URL, a saved view and a curl line without
    needing a request body. Repeating one parameter ORs its values; different
    columns AND.
    """
    table = _get_table(db, table_id)
    access.require_access(db, current_user, table, "rows:read")

    columns = _columns(db, table_id)
    by_key = {c.key: c for c in columns}

    saved = None
    if view is not None:
        saved = db.query(TabDeskSavedView).filter(
            TabDeskSavedView.id == view, TabDeskSavedView.table_id == table_id
        ).first()
        if not saved:
            raise HTTPException(status_code=404, detail="No such saved view.")
        sort = sort or saved.sort
        group = group or saved.group_by

    query = db.query(TabDeskRow).filter(TabDeskRow.table_id == table_id)

    # A saved view's filters are applied first, then any explicit ones on top.
    specs = {}
    for key, value in (saved.filters or {}).items() if saved else []:
        specs[key] = value if isinstance(value, list) else [value]
    for raw_key in request.query_params.keys():
        if not raw_key.startswith("f."):
            continue
        specs[raw_key[2:]] = request.query_params.getlist(raw_key)

    for spec, values in specs.items():
        column_key, _, op = spec.partition(".")
        op = op or "eq"
        column = by_key.get(column_key)
        if column is None:
            raise HTTPException(
                status_code=400,
                detail="Unknown filter column '%s'. This table has: %s"
                       % (column_key, ", ".join(sorted(by_key))),
            )
        try:
            query = query.filter(
                tsql.filter_clause(db, TabDeskRow, column, op, values, current_user)
            )
        except tsql.BadValue as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    search = tsql.search_clause(TabDeskRow, columns, q)
    if search is not None:
        query = query.filter(search)

    total = query.count()

    if sort:
        descending = sort.startswith("-")
        column = by_key.get(sort.lstrip("-"))
        if column is None:
            raise HTTPException(status_code=400, detail="Cannot sort by unknown column '%s'." % sort)
        query = query.order_by(tsql.sort_expression(TabDeskRow, column, descending))
    else:
        query = query.order_by(TabDeskRow.position, TabDeskRow.id)

    rows = query.limit(limit).offset(offset).all()

    out = {
        "table_id": table_id,
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "rows": [_public_row(r) for r in rows],
        "_labels": _resolve_labels(db, columns, rows),
    }
    if group:
        column = by_key.get(group)
        if column is None:
            raise HTTPException(status_code=400, detail="Cannot group by unknown column '%s'." % group)
        out["group_by"] = group
    return out


@router.post("/tables/{table_id}/rows", status_code=status.HTTP_201_CREATED)
def create_row(
    table_id: int,
    payload: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = _get_table(db, table_id)
    access.require_access(db, current_user, table, "rows:create")

    columns = _columns(db, table_id)
    if not columns:
        raise HTTPException(status_code=400, detail="This table has no columns yet.")

    data = _apply_values(columns, payload.get("data", payload))
    row = TabDeskRow(
        table_id=table_id,
        organisation_id=table.organisation_id,
        data=data,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    audit.record(
        db, action="create", entity_type="tabdesk_rows", entity_id=row.id,
        entity_label="%s entry" % table.name, actor=current_user, request=request,
        changes={"data": {"from": None, "to": data}},
        organisation_id=table.organisation_id, commit=True,
    )
    out = _public_row(row)
    out["_labels"] = _resolve_labels(db, columns, [row])
    return out


@router.patch("/tables/{table_id}/rows/{row_id}")
def update_row(
    table_id: int,
    row_id: int,
    payload: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = _get_table(db, table_id)
    row = db.query(TabDeskRow).filter(
        TabDeskRow.id == row_id, TabDeskRow.table_id == table_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No such entry.")
    access.require_row_write(db, current_user, table, row, "update")

    columns = _columns(db, table_id)
    before = dict(row.data or {})
    # Partial: only the keys sent are touched, so an inline cell edit does not
    # have to round-trip the whole row and risk clobbering a concurrent change
    # to a different column.
    data = _apply_values(columns, payload.get("data", payload), existing=before, partial=True)

    row.data = data
    row.updated_by_id = current_user.id
    db.commit()
    db.refresh(row)

    audit.record(
        db, action="update", entity_type="tabdesk_rows", entity_id=row.id,
        entity_label="%s entry" % table.name, actor=current_user, request=request,
        changes=audit.diff(before, data), organisation_id=table.organisation_id, commit=True,
    )
    out = _public_row(row)
    out["_labels"] = _resolve_labels(db, columns, [row])
    return out


@router.delete("/tables/{table_id}/rows/{row_id}")
def delete_row(
    table_id: int,
    row_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = _get_table(db, table_id)
    row = db.query(TabDeskRow).filter(
        TabDeskRow.id == row_id, TabDeskRow.table_id == table_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No such entry.")
    access.require_row_write(db, current_user, table, row, "delete")

    final = dict(row.data or {})
    db.delete(row)
    db.commit()

    audit.record(
        db, action="delete", entity_type="tabdesk_rows", entity_id=row_id,
        entity_label="%s entry" % table.name, actor=current_user, request=request,
        changes={"data": {"from": final, "to": None}},
        organisation_id=table.organisation_id, commit=True,
    )
    return {"detail": "Entry deleted", "id": row_id}


# ── members ─────────────────────────────────────────────────────────────────

def _members_payload(db, table_id):
    rows = (
        db.query(TabDeskMember, User)
        .join(User, User.id == TabDeskMember.user_id)
        .filter(TabDeskMember.table_id == table_id)
        .all()
    )
    return [
        {
            "user_id": member.user_id, "name": user.name, "email": user.email,
            "access": member.access, "access_label": access.ACCESS_LABELS.get(member.access),
        }
        for member, user in rows
    ]


@router.get("/tables/{table_id}/members")
def list_members(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = _get_table(db, table_id)
    access.require_access(db, current_user, table, "members:manage")
    return {
        "table_id": table_id,
        "visibility": table.visibility,
        "created_by_id": table.created_by_id,
        "members": _members_payload(db, table_id),
        # Everyone who could be added, so the sharing UI needs no second call.
        "candidates": [
            {"id": u.id, "name": u.name, "email": u.email}
            for u in db.query(User).filter(User.status == "Active").order_by(User.name).all()
        ],
    }


@router.put("/tables/{table_id}/members/{user_id}")
def set_member(
    table_id: int,
    user_id: int,
    body: MemberIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = _get_table(db, table_id)
    access.require_access(db, current_user, table, "members:manage")

    if body.access not in ACCESS_LEVELS:
        raise HTTPException(
            status_code=400, detail="access must be one of %s" % ", ".join(ACCESS_LEVELS)
        )
    if not db.query(User).filter(User.id == user_id).first():
        raise HTTPException(status_code=404, detail="No such user.")

    # The creator cannot be demoted by another manager. Without this, two managers
    # can demote each other and nobody is left who can fix the table.
    if user_id == table.created_by_id and body.access != "manager":
        raise HTTPException(
            status_code=400,
            detail="The person who created this table stays a manager of it.",
        )

    member = db.query(TabDeskMember).filter(
        TabDeskMember.table_id == table_id, TabDeskMember.user_id == user_id
    ).first()
    was = member.access if member else None
    if member:
        member.access = body.access
    else:
        db.add(TabDeskMember(
            table_id=table_id, user_id=user_id, access=body.access,
            created_by_id=current_user.id,
        ))
    db.commit()

    audit.record(
        db, action="update", entity_type="tabdesk_tables", entity_id=table_id,
        entity_label=table.name, actor=current_user, request=request,
        changes={"member_%d" % user_id: {"from": was, "to": body.access}},
        organisation_id=table.organisation_id, commit=True,
    )
    return {"table_id": table_id, "members": _members_payload(db, table_id)}


@router.delete("/tables/{table_id}/members/{user_id}")
def remove_member(
    table_id: int,
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = _get_table(db, table_id)
    access.require_access(db, current_user, table, "members:manage")

    member = db.query(TabDeskMember).filter(
        TabDeskMember.table_id == table_id, TabDeskMember.user_id == user_id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="That person has no explicit access here.")

    was = member.access
    db.delete(member)
    db.commit()

    audit.record(
        db, action="update", entity_type="tabdesk_tables", entity_id=table_id,
        entity_label=table.name, actor=current_user, request=request,
        changes={"member_%d" % user_id: {"from": was, "to": None}},
        organisation_id=table.organisation_id, commit=True,
    )
    # Note for the caller: on a workspace-visible table, revoking an explicit
    # grant drops the person back to the viewer floor, it does not blind them.
    return {
        "detail": "Access revoked", "user_id": user_id,
        "still_visible": table.visibility == "workspace",
        "members": _members_payload(db, table_id),
    }


# ── saved views ─────────────────────────────────────────────────────────────

@router.post("/tables/{table_id}/views", status_code=status.HTTP_201_CREATED)
def create_view(
    table_id: int,
    body: ViewIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = _get_table(db, table_id)
    my = access.require_access(db, current_user, table, "rows:read")

    # Anyone who can read may save a PRIVATE view for themselves; only a manager
    # may add one that appears for everybody.
    if body.is_shared and not access.allows(my, "views:manage"):
        raise HTTPException(
            status_code=403,
            detail="Only a manager of this table can save a view for everyone. "
                   "Save it as private instead.",
        )

    keys = {c.key for c in _columns(db, table_id)}
    for spec in (body.filters or {}):
        column_key = spec.partition(".")[0]
        if column_key not in keys:
            raise HTTPException(
                status_code=400, detail="Filter references unknown column '%s'." % column_key
            )
    if body.group_by and body.group_by not in keys:
        raise HTTPException(status_code=400, detail="Unknown group column '%s'." % body.group_by)

    saved = TabDeskSavedView(
        table_id=table_id, name=body.name.strip(), filters=body.filters or {},
        sort=body.sort, group_by=body.group_by, visible_columns=body.visible_columns,
        is_shared=body.is_shared, created_by_id=current_user.id,
        position=db.query(func.count(TabDeskSavedView.id))
                   .filter(TabDeskSavedView.table_id == table_id).scalar() or 0,
    )
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return {
        "id": saved.id, "name": saved.name, "filters": saved.filters,
        "sort": saved.sort, "group_by": saved.group_by,
        "visible_columns": saved.visible_columns, "is_shared": bool(saved.is_shared),
    }


@router.delete("/tables/{table_id}/views/{view_id}")
def delete_view(
    table_id: int,
    view_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = _get_table(db, table_id)
    my = access.require_access(db, current_user, table, "rows:read")

    saved = db.query(TabDeskSavedView).filter(
        TabDeskSavedView.id == view_id, TabDeskSavedView.table_id == table_id
    ).first()
    if not saved:
        raise HTTPException(status_code=404, detail="No such saved view.")
    if saved.created_by_id != current_user.id and not access.allows(my, "views:manage"):
        raise HTTPException(status_code=403, detail="That view is not yours to delete.")

    db.delete(saved)
    db.commit()
    return {"detail": "View deleted", "id": view_id}
