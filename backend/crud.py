"""Generic REST CRUD generated from the entity registry.

Every entity in ``backend/registry.py`` gets the same six routes without a line
of per-entity router code:

    GET    /api/{key}              list (filter · search · saved view · paginate)
    POST   /api/{key}              create
    GET    /api/{key}/{id}         detail, with related lists and remark history
    PATCH  /api/{key}/{id}         update
    DELETE /api/{key}/{id}         delete
    GET    /api/{key}/{id}/remarks append-only remark history
    POST   /api/{key}/{id}/remarks append a remark

Plus the discovery route the UI, the CLI and any agent build themselves from:

    GET    /api/meta/entities

Writes go through one path, so audit logging and provenance stamping cannot be
forgotten on a new entity.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import or_, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import audit, crm_hooks, permissions, registry
from backend.auth import get_current_user
from backend.crm_models import (
    Activity, Attachment, AuditLog, Comment, Lead, Party, Project, Task,
)
from backend.database import get_db
from backend.models import User

router = APIRouter()

# Query parameters that control the request rather than filter a column.
_CONTROL_PARAMS = {"q", "view", "limit", "offset", "order"}

# Filters that are not a plain column comparison.
_VIRTUAL_FILTERS = {"overdue"}


# ── value coercion ──────────────────────────────────────────────────────────

def _column(ent, name):
    return ent["model"].__table__.columns.get(name)


def _coerce(ent, name, value):
    """Turn a JSON/query value into something the column will accept."""
    col = _column(ent, name)
    if col is None or value is None:
        return value
    if isinstance(value, str) and value.strip() == "":
        return None

    py = col.type.python_type if hasattr(col.type, "python_type") else str
    try:
        if py is bool:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on")
        if py is int:
            return int(value)
        if py is Decimal:
            return Decimal(str(value))
        if py is float:
            return float(value)
        if py is date and not isinstance(value, date):
            return date.fromisoformat(str(value)[:10])
        if py is datetime and not isinstance(value, datetime):
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, InvalidOperation):
        raise HTTPException(status_code=400, detail="Invalid value for '%s': %r" % (name, value))
    return value


def _iso(value):
    """ISO-8601 with an explicit UTC marker.

    The database stores naive UTC (datetime.utcnow). A naive ISO string with no
    offset is parsed by browsers as LOCAL time, so in IST every timestamp came
    back 5h30m in the past — a remark added a second ago rendered "6h ago".
    Stamping the Z makes the wire format say what the value actually means.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat() + ("Z" if value.tzinfo is None else "")
    return value.isoformat()


def _plain(value):
    if isinstance(value, (datetime, date)):
        return _iso(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


# ── serialisation ───────────────────────────────────────────────────────────

def _ref_target(ref_key):
    if ref_key == "users":
        return registry.USER_REF
    return registry.BY_KEY.get(ref_key)


def _ref_fields(ent):
    """{column: ref_key} for every ref in the entity's columns and fields."""
    out = {}
    for spec in list(ent.get("columns", [])) + list(ent.get("fields", [])):
        if spec.get("type") == "ref" and spec.get("ref"):
            out[spec["k"]] = spec["ref"]
    return out


def _resolve_refs(db, ent, rows):
    """Batch-resolve every ref column to a label.

    Done as one query per referenced entity rather than per row, so a 200-row
    list with five ref columns costs five queries, not a thousand.
    """
    refs = _ref_fields(ent)
    if not refs or not rows:
        return {}

    wanted = {}
    for col, ref_key in refs.items():
        ids = {getattr(r, col, None) for r in rows}
        ids.discard(None)
        if ids:
            wanted.setdefault(ref_key, set()).update(ids)

    labels = {}
    for ref_key, ids in wanted.items():
        target = _ref_target(ref_key)
        if not target:
            continue
        model = target["model"]
        title = target.get("title_field") or "name"
        for obj in db.query(model).filter(model.id.in_(list(ids))).all():
            labels[(ref_key, obj.id)] = getattr(obj, title, None) or ("#%s" % obj.id)
    return labels


def serialize(obj, ent, ref_labels=None):
    out = {c.key: _plain(getattr(obj, c.key, None)) for c in obj.__table__.columns}
    out["_label"] = registry.label_for(obj, ent)
    out["_entity"] = ent["key"]
    if ref_labels is not None:
        resolved = {}
        for col, ref_key in _ref_fields(ent).items():
            val = getattr(obj, col, None)
            if val is not None:
                resolved[col] = ref_labels.get((ref_key, val))
        out["_refs"] = resolved
    return out


# ── filtering ───────────────────────────────────────────────────────────────

def _apply_scope(query, ent):
    """A scoped entity is one table shown as two tabs (Services / Products)."""
    for col, val in (ent.get("scope") or {}).items():
        query = query.filter(getattr(ent["model"], col) == val)
    return query


def _truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _apply_filter(query, ent, name, value, me):
    """Apply one filter. `value` may be a list — repeated params mean OR, not AND.

    Raises 400 on an unknown filter name rather than ignoring it. A silently
    dropped filter is the worst failure here: an agent asking "does this record
    exist?" with a typo'd column would get the full unfiltered list back and
    conclude yes.
    """
    model = ent["model"]

    if name == "overdue":
        due = getattr(model, "due_date", None)
        status = getattr(model, "status", None)
        if due is None:
            raise HTTPException(status_code=400, detail="'%s' has no due_date to be overdue against" % ent["key"])
        wanted = _truthy(value[0] if isinstance(value, list) else value)
        if wanted:
            query = query.filter(due < date.today())
            if status is not None:
                query = query.filter(~status.in_(["done", "cancelled"]))
        else:
            query = query.filter((due == None) | (due >= date.today()))  # noqa: E711
        return query

    col = getattr(model, name, None)
    if col is None or _column(ent, name) is None:
        valid = sorted(list(ent["model"].__table__.columns.keys()) + sorted(_VIRTUAL_FILTERS))
        raise HTTPException(
            status_code=400,
            detail="Unknown filter '%s' for %s. Valid filters: %s" % (name, ent["key"], ", ".join(valid)),
        )

    values = value if isinstance(value, list) else [value]

    def one(v):
        if v in (None, "null", "none", ""):
            return col.is_(None)
        if v == "me":
            return col == (me.id if me else None)
        if v == "today":
            return col == date.today()
        return col == _coerce(ent, name, v)

    # Repeating a parameter means "any of these" — ANDing them would always
    # return nothing, since one column cannot equal two values at once.
    if len(values) == 1:
        return query.filter(one(values[0]))
    return query.filter(or_(*[one(v) for v in values]))


def _apply_search(query, ent, term):
    fields = ent.get("search") or []
    if not term or not fields:
        return query
    like = "%%%s%%" % term.strip()
    clauses = [getattr(ent["model"], f).ilike(like) for f in fields if hasattr(ent["model"], f)]
    return query.filter(or_(*clauses)) if clauses else query


def _apply_order(query, ent, order):
    model = ent["model"]
    spec = order or ent.get("order_by") or "id"
    desc = spec.startswith("-")
    col = getattr(model, spec.lstrip("-"), None)
    if col is None:
        return query
    return query.order_by(col.desc() if desc else col.asc())


def _get_entity(key):
    ent = registry.BY_KEY.get(key)
    if not ent:
        raise HTTPException(status_code=404, detail="Unknown entity '%s'" % key)
    return ent


def _get_row(db, ent, row_id):
    obj = db.query(ent["model"]).filter(ent["model"].id == row_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="%s %s not found" % (ent["label"], row_id))
    for col, val in (ent.get("scope") or {}).items():
        if getattr(obj, col, None) != val:
            raise HTTPException(status_code=404, detail="%s %s not found" % (ent["label"], row_id))
    return obj


def _as_conflict(db, ent, exc):
    """Turn a constraint violation into a 409 instead of a 500.

    Most violations here are a duplicate natural key — a second customer with
    the same name, a second lead source called the same thing. That is a
    conflict the caller can act on, not a server fault.
    """
    db.rollback()
    detail = "That %s conflicts with an existing record." % ent["label"].lower()
    raw = str(getattr(exc, "orig", exc))
    if "UNIQUE" in raw.upper():
        detail = ("A %s with those details already exists. "
                  "Names must be unique within the organisation." % ent["label"].lower())
    return HTTPException(status_code=409, detail=detail)


def _flush(db, ent):
    """Flush so write hooks see a row with an id — same 409 handling as commit.

    This needs the conversion too: the flush happens BEFORE the commit, so
    without it a duplicate key surfaced here as a raw 500.
    """
    try:
        db.flush()
    except IntegrityError as exc:
        raise _as_conflict(db, ent, exc)


def _commit(db, ent, what="save"):
    try:
        db.commit()
    except IntegrityError as exc:
        raise _as_conflict(db, ent, exc)


def _run_hook(db, obj, ent, action, user):
    """Give an entity a chance to derive fields the caller should not type.

    Failures are logged, never raised: a derived convenience must not be able to
    reject a write the caller was entitled to make.
    """
    hook = crm_hooks.HOOKS.get(ent["key"])
    if hook is None:
        return
    try:
        hook(db, obj, ent, action, user)
    except Exception as exc:  # pragma: no cover - defensive
        import logging
        logging.getLogger("crud").error("Write hook for %s failed: %s", ent["key"], exc)


def _refuse_if_read_only(ent, action):
    """A mirrored entity has no write surface at all.

    `invoices` mirrors Zoho Books, which is the only place an invoice may be
    raised or changed. Allowing a write here would create a second, divergent
    set of books — the exact duplication the ownership rule exists to prevent.
    """
    if ent.get("read_only"):
        raise HTTPException(
            status_code=405,
            detail="%s is a read-only mirror of Zoho Books. Raise or edit it in Zoho Books; "
                   "HQ reflects it." % ent["plural"],
        )


def _writable(ent):
    """Field keys that are real, writable columns.

    Intersecting with the actual columns means a registry typo, or a field key
    that collides with a relationship name, is dropped rather than assigned onto
    a relationship attribute at runtime.
    """
    return {f["k"] for f in ent.get("fields", []) if _column(ent, f["k"]) is not None}


# ── discovery ───────────────────────────────────────────────────────────────

def check_route_collisions(app):
    """Fail loudly if a registry key is shadowed by a hand-written route.

    `/api/{key}` is a catch-all registered last, so any entity whose key matches
    an earlier literal route (e.g. `products` vs the platform's own
    /api/products) silently returns the wrong rows — the worst possible failure
    for an agent reading /api/meta/entities and trusting it. This turns that
    into a startup error instead of a data bug.
    """
    literal = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/") and "{" not in path:
            literal.add(path.rstrip("/"))

    collisions = [e["key"] for e in registry.ENTITIES if "/api/" + e["key"] in literal]
    if collisions:
        raise RuntimeError(
            "Registry key(s) shadowed by an existing literal route: %s. "
            "Rename the registry key (see `catalog-products`)." % ", ".join(sorted(collisions))
        )
    return True


def validate_registry():
    """Fail loudly if the registry describes something the schema does not have.

    A field key that is not a real column would be silently dropped on write —
    the user fills the form, the value vanishes, nothing errors. A ref pointing
    at an unknown entity would render as a bare integer. Both are caught here,
    at boot, instead of in production.
    """
    problems = []
    for ent in registry.ENTITIES:
        columns = set(ent["model"].__table__.columns.keys())

        for field in ent.get("fields", []):
            if field["k"] not in columns:
                problems.append("%s.fields['%s'] is not a column on %s"
                                % (ent["key"], field["k"], ent["model"].__tablename__))
        for col_spec in ent.get("columns", []):
            if col_spec["k"] not in columns:
                problems.append("%s.columns['%s'] is not a column on %s"
                                % (ent["key"], col_spec["k"], ent["model"].__tablename__))
        for fact in ent.get("key_facts", []):
            if fact not in columns:
                problems.append("%s.key_facts['%s'] is not a column" % (ent["key"], fact))
        for name in ent.get("search", []):
            if name not in columns:
                problems.append("%s.search['%s'] is not a column" % (ent["key"], name))
        for name in (ent.get("scope") or {}):
            if name not in columns:
                problems.append("%s.scope['%s'] is not a column" % (ent["key"], name))

        for spec in list(ent.get("columns", [])) + list(ent.get("fields", [])):
            ref = spec.get("ref")
            if spec.get("type") == "ref" and ref and ref != "users" and ref not in registry.BY_KEY:
                problems.append("%s.'%s' refs unknown entity '%s'" % (ent["key"], spec["k"], ref))

        for rel in ent.get("relations", []):
            child = registry.BY_KEY.get(rel["entity"])
            if not child:
                problems.append("%s.relations['%s'] targets unknown entity '%s'"
                                % (ent["key"], rel["key"], rel["entity"]))
            elif not rel.get("via") and rel["fk"] not in child["model"].__table__.columns:
                problems.append("%s.relations['%s'] fk '%s' is not a column on %s"
                                % (ent["key"], rel["key"], rel["fk"], child["model"].__tablename__))

    if problems:
        raise RuntimeError("Entity registry does not match the schema:\n  - " + "\n  - ".join(problems))
    return True


@router.get("/api/meta/entities")
def meta_entities(current_user: User = Depends(get_current_user)):
    """The registry, published. Everything else in the platform renders from this.

    Authenticated, unlike /api/catalog: this exposes every field of every table
    and the whole workspace layout, which is more than a discovery surface needs
    to be public on a live domain. The UI (cookie), the CLI and agents all
    authenticate before reading it anyway.
    """
    can = permissions.can_map(current_user)
    entities = []
    for e in registry.ENTITIES:
        pub = registry.public(e)
        # What THIS caller may do with it. The UI hides affordances it lacks;
        # the routes enforce it regardless.
        pub["can"] = can.get(e["key"], {})
        entities.append(pub)
    return {
        "count": len(entities),
        "entities": entities,
        "refs": {"users": {"path": "/api/users", "title_field": "name"}},
        "can": can,
    }


@router.get("/api/meta/entities/{key}")
def meta_entity(key: str):
    return registry.public(_get_entity(key))


# Declared before the generic /api/{key} route so it is not swallowed by it.
@router.get("/api/audit")
def audit_trail(
    entity_type: str = "",
    entity_id: int = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The platform-wide change history — who changed what, when, from where."""
    permissions.require(current_user, "audit", "read")
    entries = _audit_list(db, entity_type or None, entity_id, limit=limit, offset=offset)
    # `count` is how many came back, not how many were asked for — a client
    # paginating on the requested limit would never stop.
    return {"count": len(entries), "limit": limit, "offset": offset, "entries": entries}


# ── list ────────────────────────────────────────────────────────────────────

@router.get("/api/{key}")
def list_rows(
    key: str,
    request: Request,
    q: str = "",
    view: str = "",
    order: str = "",
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ent = _get_entity(key)
    permissions.require(current_user, key, "read")
    query = _apply_scope(db.query(ent["model"]), ent)

    if view:
        match = next((v for v in ent.get("saved_views", []) if v["name"].lower() == view.lower()), None)
        if not match:
            raise HTTPException(status_code=400, detail="Unknown view '%s' for %s" % (view, key))
        for name, value in (match.get("filters") or {}).items():
            query = _apply_filter(query, ent, name, value, current_user)

    grouped = {}
    for name, value in request.query_params.multi_items():
        if name in _CONTROL_PARAMS:
            continue
        grouped.setdefault(name, []).append(value)
    for name, values in grouped.items():
        query = _apply_filter(query, ent, name, values, current_user)

    query = _apply_search(query, ent, q)
    total = query.count()
    rows = _apply_order(query, ent, order).offset(offset).limit(limit).all()
    labels = _resolve_refs(db, ent, rows)

    return {
        "entity": key,
        "total": total,
        "count": len(rows),
        "offset": offset,
        "rows": [serialize(r, ent, labels) for r in rows],
    }


# ── detail ──────────────────────────────────────────────────────────────────

@router.get("/api/{key}/{row_id}")
def get_row(
    key: str,
    row_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ent = _get_entity(key)
    permissions.require(current_user, key, "read")
    obj = _get_row(db, ent, row_id)
    labels = _resolve_refs(db, ent, [obj])
    data = serialize(obj, ent, labels)

    # Related lists — the sections down the left of the detail archetype.
    related = {}
    for rel in ent.get("relations", []):
        child = registry.BY_KEY.get(rel["entity"])
        if not child or rel.get("via"):
            continue  # join-table relations are resolved by their own endpoint
        fk = getattr(child["model"], rel["fk"], None)
        if fk is None:
            continue
        child_rows = _apply_order(
            _apply_scope(db.query(child["model"]).filter(fk == row_id), child), child, None
        ).limit(100).all()
        child_labels = _resolve_refs(db, child, child_rows)
        related[rel["key"]] = {
            "label": rel["label"],
            "entity": rel["entity"],
            "rows": [serialize(r, child, child_labels) for r in child_rows],
        }

    data["_related"] = related
    data["_remarks"] = _remark_list(db, ent, row_id)
    data["_attachments"] = _attachment_list(db, ent, row_id)
    data["_audit"] = _audit_list(
        db, ent["entity_type"], row_id, limit=25, since=getattr(obj, "created_at", None)
    )
    return data


# ── create / update / delete ────────────────────────────────────────────────

@router.post("/api/{key}")
def create_row(
    key: str,
    payload: dict,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ent = _get_entity(key)
    permissions.require(current_user, key, "create")
    _refuse_if_read_only(ent, "create")
    allowed = _writable(ent)

    values = {}
    for name, value in (payload or {}).items():
        if name in allowed:
            values[name] = _coerce(ent, name, value)

    for field in ent.get("fields", []):
        if field.get("required") and values.get(field["k"]) in (None, ""):
            raise HTTPException(status_code=400, detail="'%s' is required" % field["label"])
        if field["k"] not in values and field.get("default") is not None:
            values[field["k"]] = field["default"]

    # A scoped entity forces its discriminator — creating a Product must never
    # be able to write item_type='service' by passing it in the body.
    values.update(ent.get("scope") or {})

    obj = ent["model"](**values)

    # Probe for real COLUMNS, never hasattr: `Lead.source` is a relationship to
    # lead_sources while `Task.source` is a string column, and hasattr cannot
    # tell them apart — assigning a string to the relationship blows up.
    if _column(ent, "organisation_id") is not None and getattr(obj, "organisation_id", None) is None:
        obj.organisation_id = current_user.organisation_id
    for col in ("created_by_id", "updated_by_id"):
        if _column(ent, col) is not None:
            setattr(obj, col, current_user.id)
    # `source` is derived from the X-HQ-Client header, never from the body — a
    # caller must not be able to claim a write came from somewhere it did not.
    if _column(ent, "source") is not None:
        obj.source = _source_of(request)

    db.add(obj)
    _flush(db, ent)
    _run_hook(db, obj, ent, "create", current_user)
    _commit(db, ent)
    db.refresh(obj)

    audit.record(
        db, action="create", entity_type=ent["entity_type"], entity_id=obj.id,
        entity_label=registry.label_for(obj, ent), actor=current_user, request=request,
        changes=None, organisation_id=getattr(obj, "organisation_id", None), commit=True,
    )
    return serialize(obj, ent, _resolve_refs(db, ent, [obj]))


@router.patch("/api/{key}/{row_id}")
def update_row(
    key: str,
    row_id: int,
    payload: dict,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ent = _get_entity(key)
    permissions.require(current_user, key, "update")
    _refuse_if_read_only(ent, "update")
    obj = _get_row(db, ent, row_id)
    allowed = _writable(ent)
    before = audit.snapshot(obj)

    for name, value in (payload or {}).items():
        if name in allowed and name not in (ent.get("scope") or {}):
            setattr(obj, name, _coerce(ent, name, value))

    if _column(ent, "updated_by_id") is not None:
        obj.updated_by_id = current_user.id

    _run_hook(db, obj, ent, "update", current_user)
    changes = audit.diff(before, audit.snapshot(obj))
    _commit(db, ent)
    db.refresh(obj)

    if changes:
        audit.record(
            db, action="update", entity_type=ent["entity_type"], entity_id=obj.id,
            entity_label=registry.label_for(obj, ent), actor=current_user, request=request,
            changes=changes, organisation_id=getattr(obj, "organisation_id", None), commit=True,
        )
    return serialize(obj, ent, _resolve_refs(db, ent, [obj]))


@router.delete("/api/{key}/{row_id}")
def delete_row(
    key: str,
    row_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ent = _get_entity(key)
    permissions.require(current_user, key, "delete")
    _refuse_if_read_only(ent, "delete")
    obj = _get_row(db, ent, row_id)
    label = registry.label_for(obj, ent)
    org_id = getattr(obj, "organisation_id", None)
    before = audit.snapshot(obj)

    # Polymorphic children are keyed by (entity_type, entity_id) with no FK, so
    # nothing cascades them. Left behind, they resurface on the NEXT row that
    # gets the same id — and databases do recycle ids. A new customer showing a
    # deleted customer's remarks is both wrong and a disclosure.
    # audit_logs is deliberately NOT purged: it is the record that the delete
    # happened. get_row scopes it by the row's creation time instead.
    for model in (Comment, Activity, Attachment):
        db.query(model).filter(
            model.entity_type == ent["entity_type"], model.entity_id == row_id
        ).delete(synchronize_session=False)

    db.delete(obj)
    db.commit()

    # The deleted row's final state is kept in the audit entry — otherwise a
    # delete is the one action whose trail tells you nothing about what was lost.
    audit.record(
        db, action="delete", entity_type=ent["entity_type"], entity_id=row_id,
        entity_label=label, actor=current_user, request=request,
        changes={"deleted": {"from": before, "to": None}},
        organisation_id=org_id, commit=True,
    )
    return {"detail": "%s deleted" % ent["label"], "id": row_id}


def _source_of(request):
    kind = audit.actor_kind(request)
    return {"user": "ui", "cli": "cli", "agent": "agent", "system": "api"}.get(kind, "api")


# ── attachments — links to the files a record lives on ──────────────────────
#
# A sub-resource of whatever it hangs off, deliberately NOT a registry entity of
# its own. A new entity key mints new permission codes, and on an organisation
# that has saved its Permissions matrix those ship DENIED — so attachments would
# arrive invisible to every role until an admin went and ticked them. Hanging off
# the parent means an attachment is readable by whoever can read the record and
# writable by whoever can change it, which is also just the correct answer.
#
# `storage_url` holds a LINK, which is what the column was always shaped for
# (String(600), no binary column anywhere). HQ's container has no volume — the
# filesystem is rebuilt on every deploy — so bytes could not live here even if
# the schema wanted them to. A Drive link outlives the container.

_GOOGLE_KINDS = [
    (r"docs\.google\.com/document/d/", "Google Doc"),
    (r"docs\.google\.com/spreadsheets/d/", "Google Sheet"),
    (r"docs\.google\.com/presentation/d/", "Google Slides"),
    (r"docs\.google\.com/forms/d/", "Google Form"),
    (r"drive\.google\.com/drive/folders/", "Drive folder"),
    (r"drive\.google\.com/(file/d/|open\?|uc\?)", "Drive file"),
]


def _link_kind(url):
    """What a link is, from its shape alone — no credentials, no guessing.

    A Google URL says which product it belongs to. The real filename, size and
    sharing state need an API call, and are left null rather than invented: a
    card claiming a name nobody read would be worse than one that says
    "Google Sheet".
    """
    import re as _re

    for pattern, label in _GOOGLE_KINDS:
        if _re.search(pattern, url or "", _re.I):
            return label
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").replace("www.", "")
        return host or "Link"
    except Exception:  # pragma: no cover - defensive
        return "Link"


def _attachment_list(db, ent, row_id):
    rows = (
        db.query(Attachment)
        .filter(Attachment.entity_type == ent["entity_type"], Attachment.entity_id == row_id)
        .order_by(Attachment.created_at.desc())
        .all()
    )
    return [
        {
            "id": a.id, "filename": a.filename, "url": a.storage_url,
            "kind": _link_kind(a.storage_url), "mime": a.mime, "size": a.size,
            "created_at": _iso(a.created_at), "created_by_id": a.created_by_id,
        }
        for a in rows
    ]


@router.get("/api/{key}/{row_id}/attachments")
def list_attachments(
    key: str,
    row_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ent = _get_entity(key)
    permissions.require(current_user, key, "read")
    _get_row(db, ent, row_id)
    return {"entity": key, "id": row_id, "attachments": _attachment_list(db, ent, row_id)}


@router.post("/api/{key}/{row_id}/attachments")
def add_attachment(
    key: str,
    row_id: int,
    payload: dict,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Attach a link to this record.

    Paste a Drive, Docs, Sheets or Slides URL — or any URL — and it is filed
    against the record, typed by its shape and given a name. With no name
    supplied the link's own kind is used, so an attachment is never nameless.
    """
    ent = _get_entity(key)
    # `update`, not `remark`: attaching a file changes what the record says about
    # itself, so it belongs with editing it rather than with commenting on it.
    # Two consequences, taken deliberately — someone with remark-only access
    # cannot attach, and someone with update but not delete CAN unlink.
    #
    # `_refuse_if_read_only` is deliberately NOT called. A Zoho-mirrored invoice
    # rejects field writes because Zoho owns those fields; it does not own HQ's
    # note of where the signed PDF lives, and refusing to file that against the
    # invoice it belongs to would help nobody.
    permissions.require(current_user, key, "update")
    obj = _get_row(db, ent, row_id)

    url = ((payload or {}).get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="'url' is required")
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="A link must start with http:// or https:// — %r does not." % url[:80],
        )
    if len(url) > 600:
        raise HTTPException(status_code=400, detail="That link is too long to store (600 characters max).")

    filename = ((payload or {}).get("filename") or "").strip()
    mime = (payload or {}).get("mime") or None
    size = (payload or {}).get("size")
    if not filename:
        # Ask Drive what the link actually is, when HQ has credentials and the
        # file is one it can see. That turns "Google Sheet" into the sheet's
        # real name. It returns None for every ordinary reason — not a Drive
        # link, not shared with us, Drive unreachable — and the shape-derived
        # label is the honest fallback rather than a failure.
        from backend import drive

        described = drive.describe(url)
        if described and described.get("filename"):
            filename = described["filename"]
            mime = mime or described.get("mime")
            size = size if size is not None else described.get("size")
    filename = filename or _link_kind(url)

    row = Attachment(
        # Taken from the record, falling back to the caller — the same order
        # add_remark uses. Identical while HQ is single-org, and the attachment
        # follows its parent rather than its author the day it is not.
        organisation_id=getattr(obj, "organisation_id", None) or current_user.organisation_id,
        entity_type=ent["entity_type"],
        entity_id=row_id,
        filename=filename[:300],
        storage_url=url,
        mime=mime,
        size=size,
        created_by_id=current_user.id,
    )
    db.add(row)
    db.commit()

    audit.record(
        db, action="attach", entity_type=ent["entity_type"], entity_id=row_id,
        entity_label=registry.label_for(obj, ent),
        actor=current_user, request=request,
        changes={"attachment": {"from": None, "to": filename}},
        organisation_id=row.organisation_id, commit=True,
    )
    return {
        "id": row.id, "filename": row.filename, "url": row.storage_url,
        "kind": _link_kind(row.storage_url), "mime": row.mime, "size": row.size,
        "created_at": _iso(row.created_at), "created_by_id": row.created_by_id,
    }


@router.post("/api/{key}/{row_id}/attachments/upload")
async def upload_attachment(
    key: str,
    row_id: int,
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a file to Drive and attach the link to this record.

    The bytes go straight from the browser to Google and are never written to
    HQ's filesystem, which does not survive a deploy. What HQ keeps is what it
    has always kept: a link.

    Refused with a 400 that names the fix when Drive is not configured — an
    upload button that accepts a file and silently loses it is worse than one
    that says it cannot take it yet.
    """
    from backend import drive

    ent = _get_entity(key)
    permissions.require(current_user, key, "update")
    obj = _get_row(db, ent, row_id)

    if not drive.is_configured():
        raise HTTPException(status_code=400, detail=(
            "Uploading is not configured on this server, so the file was not "
            "stored. Paste a link instead, or " + drive.SETUP_HINT[0].lower()
            + drive.SETUP_HINT[1:]))

    content = await file.read()
    try:
        stored = drive.upload(file.filename, content, file.content_type)
    except drive.DriveError as exc:
        # The reason is Google's or this module's, and both are written to be
        # actionable. Passing it through beats replacing it with "upload failed".
        raise HTTPException(status_code=400, detail=str(exc))

    row = Attachment(
        organisation_id=getattr(obj, "organisation_id", None) or current_user.organisation_id,
        entity_type=ent["entity_type"],
        entity_id=row_id,
        filename=(stored["filename"] or "Untitled")[:300],
        storage_url=stored["url"],
        mime=stored.get("mime"),
        size=stored.get("size"),
        created_by_id=current_user.id,
    )
    db.add(row)
    db.commit()

    audit.record(
        db, action="attach", entity_type=ent["entity_type"], entity_id=row_id,
        entity_label=registry.label_for(obj, ent), actor=current_user, request=request,
        changes={"uploaded": {"from": None, "to": row.filename}},
        organisation_id=row.organisation_id, commit=True,
    )
    return {
        "id": row.id, "filename": row.filename, "url": row.storage_url,
        "kind": _link_kind(row.storage_url), "mime": row.mime, "size": row.size,
        "created_at": _iso(row.created_at), "created_by_id": row.created_by_id,
    }


@router.delete("/api/{key}/{row_id}/attachments/{attachment_id}")
def remove_attachment(
    key: str,
    row_id: int,
    attachment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unlink a file from this record.

    Removes HQ's reference only — whatever the link points at is untouched. HQ
    never had the file, so it is not HQ's to delete.
    """
    ent = _get_entity(key)
    permissions.require(current_user, key, "update")
    _get_row(db, ent, row_id)

    row = (
        db.query(Attachment)
        .filter(
            Attachment.id == attachment_id,
            Attachment.entity_type == ent["entity_type"],
            Attachment.entity_id == row_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment %s not found on this record" % attachment_id)

    name = row.filename
    db.delete(row)
    db.commit()
    audit.record(
        db, action="detach", entity_type=ent["entity_type"], entity_id=row_id,
        entity_label=None, actor=current_user, request=request,
        changes={"attachment": {"from": name, "to": None}},
        organisation_id=current_user.organisation_id, commit=True,
    )
    return {"detail": "Attachment removed", "id": attachment_id}


# ── remarks — append-only history ───────────────────────────────────────────

def _remark_list(db, ent, row_id):
    rows = (
        db.query(Comment)
        .filter(Comment.entity_type == ent["entity_type"], Comment.entity_id == row_id)
        .order_by(Comment.created_at.asc())
        .all()
    )
    return [
        {
            "id": c.id, "body": c.body, "kind": c.kind, "source": c.source,
            "author_id": c.author_id,
            "author": c.author.name if c.author else None,
            "created_at": _iso(c.created_at),
            "external_ref": c.external_ref,
        }
        for c in rows
    ]


@router.get("/api/{key}/{row_id}/remarks")
def list_remarks(
    key: str,
    row_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ent = _get_entity(key)
    permissions.require(current_user, key, "read")
    _get_row(db, ent, row_id)
    return {"entity": key, "id": row_id, "remarks": _remark_list(db, ent, row_id)}


@router.post("/api/{key}/{row_id}/remarks")
def add_remark(
    key: str,
    row_id: int,
    payload: dict,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Append a remark. There is deliberately no edit or delete.

    History is never overwritten — a correction is a new remark, so the trail of
    what was believed when stays readable.
    """
    ent = _get_entity(key)
    permissions.require(current_user, key, "remark")
    obj = _get_row(db, ent, row_id)
    body = (payload or {}).get("body", "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="'body' is required")

    kind = (payload or {}).get("kind") or "remark"
    if kind not in ("remark", "note", "reply", "correction"):
        raise HTTPException(status_code=400, detail="kind must be remark, note, reply or correction")

    external_ref = (payload or {}).get("external_ref")
    if external_ref:
        # Idempotency for agents replaying the same wiki row: same ref on the
        # same record is a no-op, not a duplicate remark.
        existing = (
            db.query(Comment)
            .filter(
                Comment.entity_type == ent["entity_type"],
                Comment.entity_id == row_id,
                Comment.external_ref == external_ref,
            )
            .first()
        )
        if existing:
            return {"detail": "Remark already recorded", "id": existing.id, "duplicate": True}

    comment = Comment(
        organisation_id=getattr(obj, "organisation_id", None) or current_user.organisation_id,
        entity_type=ent["entity_type"], entity_id=row_id,
        author_id=current_user.id, body=body, kind=kind,
        source=_source_of(request), external_ref=external_ref,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    audit.record(
        db, action="remark", entity_type=ent["entity_type"], entity_id=row_id,
        entity_label=registry.label_for(obj, ent), actor=current_user, request=request,
        changes={"remark": {"from": None, "to": body[:500]}},
        organisation_id=comment.organisation_id, commit=True,
    )
    return {
        "id": comment.id, "body": comment.body, "kind": comment.kind, "source": comment.source,
        "author": current_user.name, "author_id": current_user.id,
        "created_at": comment.created_at.isoformat(), "duplicate": False,
    }


# ── audit trail ─────────────────────────────────────────────────────────────

def _audit_list(db, entity_type, entity_id=None, limit=100, offset=0, since=None):
    query = db.query(AuditLog)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditLog.entity_id == entity_id)
    if since is not None:
        # A recycled id would otherwise show a previous row's history on this
        # one. The global /api/audit view passes no `since` — there, seeing the
        # full ledger for an id is the point.
        query = query.filter(AuditLog.created_at >= since)
    rows = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": a.id, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
            "entity_label": a.entity_label, "actor": a.actor_email, "actor_kind": a.actor_kind,
            "actor_id": a.actor_user_id, "changes": a.changes,
            "created_at": _iso(a.created_at),
        }
        for a in rows
    ]


# ── lead conversion ─────────────────────────────────────────────────────────
#
# Leads, customers and projects are one web, not three lists. A lead is a piece
# of business being won; the company it is for may already be in the book, and
# winning it produces delivery. So conversion has three jobs — resolve the
# party, promote it, open the project — and every one of them is find-or-create,
# never blind-create.
#
# `resolve_party` used to 409 when a party of the same name existed, which is
# exactly backwards: a name match is the strongest evidence that this lead is
# for a company we already know. It links now.
#
# Everything here is written to be *total* — it does not raise. `_run_hook`
# swallows exceptions (see its docstring), so a conversion that could fail
# half-way would leave a lead marked won with no customer and nothing said about
# it. Idempotence carries the safety instead: re-running converges.


def _party_for_lead(db, lead, user, payload=None):
    """The party this lead belongs to: the linked one, the matching one, or a new one.

    Preference runs from most to least certain — an explicit `party_id` beats a
    name match, and a name match beats minting a second row for a company that
    is already in the book.
    """
    payload = payload or {}

    if lead.party_id:
        linked = db.query(Party).filter(Party.id == lead.party_id).first()
        if linked:
            return linked, False
    if lead.converted_party_id:
        linked = db.query(Party).filter(Party.id == lead.converted_party_id).first()
        if linked:
            return linked, False

    name = (payload.get("display_name") or lead.company_name or lead.title or "").strip()
    if not name:
        return None, False

    match = db.query(Party).filter(
        Party.organisation_id == lead.organisation_id,
        Party.display_name == name,
    ).first()
    if match:
        return match, False

    # A company we have not won is a prospect, not a customer. Creating every
    # party as a customer made "lost" unrepresentable: the outcome branch below
    # only ever demotes a prospect, so a lost lead's company stayed Active and
    # looked exactly like one still being worked.
    default_kind = "customer" if (lead.status or "").lower() == "won" else "prospect"
    party = Party(
        organisation_id=lead.organisation_id or user.organisation_id,
        kind=payload.get("kind") or default_kind,
        display_name=name,
        phone=lead.phone,
        email=lead.email,
        owner_id=lead.owner_id or user.id,
        status="Active",
        summary=lead.notes,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(party)
    db.flush()

    if lead.contact_name:
        from backend.crm_models import PartyContact

        db.add(PartyContact(
            organisation_id=party.organisation_id, party_id=party.id, name=lead.contact_name,
            phone=lead.phone, email=lead.email, is_primary=True,
            created_by_id=user.id, updated_by_id=user.id,
        ))
    return party, True


def _project_for_lead(db, lead, party, user, payload=None):
    """The project a won lead opens, created once.

    The lead already carries everything a project needs to start — who it is for,
    which service, what it is worth, who owns it and what the next move is — so
    re-typing it is both work and a chance to disagree with the funnel.
    """
    payload = payload or {}
    if lead.converted_project_id:
        existing = db.query(Project).filter(Project.id == lead.converted_project_id).first()
        if existing:
            return existing, False
    if payload.get("create_project") is False:
        return None, False

    project = Project(
        organisation_id=lead.organisation_id or user.organisation_id,
        name=(payload.get("project_name") or lead.title or "").strip() or lead.title,
        description=lead.notes,
        party_id=party.id if party else None,
        item_id=lead.item_id,
        manager_id=lead.owner_id or user.id,
        stage="Not started",
        status="active",
        one_time_amount=lead.estimated_value,
        monthly_amount=lead.monthly_value,
        currency=lead.currency or "INR",
        next_action=lead.next_action,
        next_action_date=lead.next_action_date,
        next_action_owner_id=lead.next_action_owner_id,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(project)
    db.flush()
    return project, True


def _adopt_lead_tasks(db, lead, party, project):
    """Move a won lead's tasks onto the project it opened.

    Work booked against a lead is the same work once the lead is a project —
    "draft the SOW" does not stop existing because the deal closed. Without this
    the tasks stay behind on a won lead and the new project opens empty, which is
    how a delivery board ends up disagreeing with the funnel that fed it.

    `lead_id` is deliberately left in place: it is the record of where the work
    came from, and clearing it would lose the funnel history the lead exists for.
    A task already pointed at some other project is never moved — an explicit
    assignment outranks an inferred one.
    """
    if project is None:
        return 0
    moved = 0
    for task in db.query(Task).filter(Task.lead_id == lead.id).all():
        if task.project_id is None:
            task.project_id = project.id
            moved += 1
        if task.party_id is None and party is not None:
            task.party_id = party.id
    return moved


def sync_lead_outcome(db, lead, user, payload=None):
    """Make the customer and the project agree with the lead's outcome.

    The three states Meet runs the funnel on:

      ``won``   the company is a customer, and the work it bought is a project
      ``lost``  it stays a prospect, marked Inactive — the record of a company
                we chased and did not land
      ``open``  still in play: a prospect, still Active

    Losing a lead never demotes a company that is already a customer for other
    work, because one lost project is not the end of a relationship.

    Returns a dict describing what it changed, for the caller to audit.
    """
    payload = payload or {}
    result = {"party": None, "project": None, "party_created": False,
              "project_created": False, "tasks_moved": 0}
    status = (lead.status or "open").lower()

    party, party_created = _party_for_lead(db, lead, user, payload)
    if party is None:
        return result

    # A lead always knows who it is for once we can name them, whatever the
    # outcome — that link is what stops one company appearing twice.
    if lead.party_id != party.id:
        lead.party_id = party.id
    result["party"] = party
    result["party_created"] = party_created

    if status == "won":
        if (party.kind or "").lower() in ("prospect", ""):
            party.kind = "customer"
        party.status = "Active"
        lead.converted_party_id = party.id
        lead.converted_at = lead.converted_at or datetime.utcnow()

        project, project_created = _project_for_lead(db, lead, party, user, payload)
        if project is not None:
            lead.converted_project_id = project.id
            result["project"] = project
            result["project_created"] = project_created
            result["tasks_moved"] = _adopt_lead_tasks(db, lead, party, project)

    elif status == "lost":
        # Only a company we never landed goes Inactive. A real customer who lost
        # one bid is still a customer.
        if (party.kind or "").lower() == "prospect" and not party.projects:
            party.status = "Inactive"

    else:  # open — still being worked
        if (party.kind or "").lower() == "prospect":
            party.status = "Active"

    return result


@router.post("/api/tasks/{task_id}/claim")
def claim_task(
    task_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Take ownership of an unclaimed task, or fail.

    This exists because ``PATCH /api/tasks/{id}`` cannot be used safely for
    this. That path reads the row, changes it in Python and writes it back, so
    two agents polling for work both read ``owner_id IS NULL``, both write
    themselves in, and the second silently wins. Nothing errors. You find out
    when the same work has been done twice.

    So the claim is ONE conditional UPDATE and the winner is decided by the
    number of rows the database says it changed — never by a SELECT beforehand,
    which is the same race in a different shape. The loser is told who holds it.
    """
    permissions.require(current_user, "tasks", "update")

    # `owner_id IS NULL OR owner_id = me`, not `IS NULL` alone. Assigning work
    # in the UI produces owner_id set + status 'open', which is the ordinary way
    # a human hands an agent a job. With `IS NULL` alone that state was a dead
    # end: claim refused it because it was owned, release refused it because it
    # had not started, and the agent sat idle on work addressed to it by name.
    #
    # Still one conditional UPDATE, and still race-free: two agents can only
    # both match through the NULL branch, and exactly one of them wins that.
    prior = db.query(Task.status, Task.owner_id).filter(Task.id == task_id).first()
    now = datetime.utcnow()
    result = db.execute(
        sa_update(Task)
        .where(Task.id == task_id, Task.status == "open",
               or_(Task.owner_id.is_(None), Task.owner_id == current_user.id))
        .values(owner_id=current_user.id, status="in_progress",
                updated_by_id=current_user.id, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()

    if result.rowcount == 1:
        task = db.query(Task).filter(Task.id == task_id).first()
        audit.record(
            db, action="claim", entity_type="tasks", entity_id=task_id,
            entity_label=task.title, actor=current_user, request=request,
            # The real prior values, read before the write. Recording a assumed
            # "from" is how an audit trail starts lying about what happened.
            changes={"owner_id": {"from": prior.owner_id if prior else None, "to": current_user.id},
                     "status": {"from": prior.status if prior else None, "to": "in_progress"}},
            organisation_id=task.organisation_id, commit=True,
        )
        return {"claimed": True, "task": serialize(task, _get_entity("tasks"))}

    # Lost, or never eligible. Read the row only NOW — to explain, not to decide.
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task %s not found" % task_id)
    if task.owner_id and task.owner_id != current_user.id:
        holder = db.query(User).filter(User.id == task.owner_id).first()
        raise HTTPException(status_code=409, detail=(
            "Task %s is already held by %s. Nothing was changed."
            % (task_id, (holder.name if holder else "user %s" % task.owner_id))))
    raise HTTPException(status_code=409, detail=(
        "Task %s is '%s', and only an open task can be claimed." % (task_id, task.status)))


@router.post("/api/tasks/{task_id}/release")
def release_task(
    task_id: int,
    request: Request,
    payload: dict = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Give a claimed task back, so a crashed agent does not hold it forever.

    Without this, claiming is a one-way door: an agent that dies mid-task keeps
    the row locked to itself and the work silently stops being picked up. The
    same conditional-update discipline applies, so releasing a task somebody
    else has since taken changes nothing rather than stealing it back.
    """
    permissions.require(current_user, "tasks", "update")

    # 'open' is in the list so an assignment can be declined, not just an
    # in-flight task abandoned — the mirror of claim accepting owner+open.
    prior = db.query(Task.status, Task.owner_id).filter(Task.id == task_id).first()
    now = datetime.utcnow()
    result = db.execute(
        sa_update(Task)
        .where(Task.id == task_id, Task.owner_id == current_user.id,
               Task.status.in_(["open", "in_progress", "blocked"]))
        .values(owner_id=None, status="open", updated_by_id=current_user.id, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()

    if result.rowcount == 1:
        task = db.query(Task).filter(Task.id == task_id).first()
        reason = ((payload or {}).get("reason") or "").strip()
        audit.record(
            db, action="release", entity_type="tasks", entity_id=task_id,
            entity_label=task.title, actor=current_user, request=request,
            # `prior.status`, not a hardcoded "in_progress" — releasing from
            # 'blocked' used to record a transition that never happened.
            changes={"owner_id": {"from": current_user.id, "to": None},
                     "status": {"from": prior.status if prior else None, "to": "open"},
                     **({"reason": {"from": None, "to": reason}} if reason else {})},
            organisation_id=task.organisation_id, commit=True,
        )
        return {"released": True, "task": serialize(task, _get_entity("tasks"))}

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task %s not found" % task_id)
    if task.owner_id != current_user.id:
        raise HTTPException(status_code=409, detail=(
            "Task %s is not yours to release." % task_id))
    raise HTTPException(status_code=409, detail=(
        "Task %s is '%s' — a finished task cannot be released." % (task_id, task.status)))


@router.post("/api/leads/{lead_id}/convert")
def convert_lead(
    lead_id: int,
    request: Request,
    payload: dict = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Turn a won lead into a customer, and open the project it bought.

    The lead is kept and stamped, never deleted — the funnel history is the
    reason the lead existed. Converting twice returns what already exists rather
    than creating a second copy of it.

    Pass ``create_project: false`` to convert the customer without opening a
    project, or ``project_name`` to name it something other than the lead.
    """
    permissions.require(current_user, "leads", "update")
    permissions.require(current_user, "customers", "create")
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead %s not found" % lead_id)

    payload = payload or {}
    already = bool(lead.converted_party_id)

    was_status = lead.status
    lead.status = "won"
    outcome = sync_lead_outcome(db, lead, current_user, payload)
    party = outcome["party"]
    if party is None:
        raise HTTPException(status_code=400, detail="Lead has no company name — pass display_name")

    lead.updated_by_id = current_user.id
    db.commit()
    db.refresh(party)

    audit.record(
        db, action="convert", entity_type="leads", entity_id=lead.id, entity_label=lead.title,
        actor=current_user, request=request,
        changes={
            "converted_party_id": {"from": None if not already else party.id, "to": party.id},
            "converted_project_id": {"from": None, "to": lead.converted_project_id},
            "status": {"from": was_status, "to": "won"},
        },
        organisation_id=lead.organisation_id,
    )
    if outcome["party_created"]:
        audit.record(
            db, action="create", entity_type="parties", entity_id=party.id, entity_label=party.display_name,
            actor=current_user, request=request,
            changes={"converted_from_lead": {"from": None, "to": lead.id}},
            organisation_id=party.organisation_id,
        )
    if outcome["project_created"] and outcome["project"] is not None:
        audit.record(
            db, action="create", entity_type="projects", entity_id=outcome["project"].id,
            entity_label=outcome["project"].name, actor=current_user, request=request,
            changes={"opened_from_lead": {"from": None, "to": lead.id}},
            organisation_id=party.organisation_id,
        )
    db.commit()

    ent = registry.BY_KEY["customers"]
    body = {
        "detail": "Lead already converted" if already else "Lead converted",
        "already_converted": already,
        "lead_id": lead.id,
        "customer": serialize(party, ent, _resolve_refs(db, ent, [party])),
    }
    if outcome["project"] is not None:
        pent = registry.BY_KEY["projects"]
        body["project"] = serialize(outcome["project"], pent, _resolve_refs(db, pent, [outcome["project"]]))
    return body


# ── self-documentation ──────────────────────────────────────────────────────

def catalog_entries(base="__BASE__"):
    """Generate /api/catalog entries for every registry entity.

    Hand-maintaining this list meant it drifted the moment an entity was added —
    it documented 39 endpoints while 58 existed, which is worse than documenting
    none: an agent that trusts the catalogue concludes a route does not exist.
    Generating it from the same registry the routes come from makes drift
    impossible.
    """
    out = []
    for ent in registry.ENTITIES:
        key, label, plural = ent["key"], ent["label"], ent["plural"]
        path = "/api/" + key
        views = ", ".join(v["name"] for v in ent.get("saved_views", [])) or "none"
        required = [f["label"] for f in ent.get("fields", []) if f.get("required")]

        out.append({
            "method": "GET", "path": path, "auth": "Bearer / Cookie",
            "summary": "List %s. Filter by any column, ?q= to search, ?view= for a saved view (%s), "
                       "?limit/?offset to page." % (plural.lower(), views),
            "usage": "curl \"%s%s?view=%s&limit=25\" \\\n  -H \"Authorization: Bearer $TOKEN\""
                     % (base, path, (ent.get("saved_views") or [{"name": "All"}])[0]["name"]),
            "response": "{\n  \"entity\": \"%s\", \"total\": 17, \"count\": 17,\n"
                        "  \"rows\": [ { \"id\": 1, \"_label\": \"...\", \"_refs\": { ... } } ]\n}" % key,
        })
        if not ent.get("read_only"):
            out.append({
                "method": "POST", "path": path, "auth": "Bearer / Cookie",
                "summary": "Create a %s.%s" % (
                    label.lower(),
                    (" Required: %s." % ", ".join(required)) if required else ""),
                "usage": "curl -X POST %s%s \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                         "  -H 'Content-Type: application/json' \\\n  -d '{...}'" % (base, path),
                "response": "{ \"id\": 18, \"_entity\": \"%s\" }" % key,
            })
        out.append({
            "method": "GET", "path": path + "/{id}", "auth": "Bearer / Cookie",
            "summary": "One %s, with its related lists, remark history and audit trail."
                       % label.lower(),
            "usage": "curl %s%s/1 \\\n  -H \"Authorization: Bearer $TOKEN\"" % (base, path),
            "response": "{\n  \"id\": 1, \"_related\": { ... },\n"
                        "  \"_remarks\": [ ... ], \"_audit\": [ ... ]\n}",
        })
        if not ent.get("read_only"):
            out.append({
                "method": "PATCH", "path": path + "/{id}", "auth": "Bearer / Cookie",
                "summary": "Update a %s. Only declared fields are writable." % label.lower(),
                "usage": "curl -X PATCH %s%s/1 \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                         "  -H 'Content-Type: application/json' \\\n  -d '{...}'" % (base, path),
                "response": "{ \"id\": 1 }",
            })
            out.append({
                "method": "DELETE", "path": path + "/{id}", "auth": "Bearer / Cookie",
                "summary": "Delete a %s. Its remarks and attachments go with it; the audit "
                           "entry keeps the row's final state." % label.lower(),
                "usage": "curl -X DELETE %s%s/1 \\\n  -H \"Authorization: Bearer $TOKEN\"" % (base, path),
                "response": "{ \"detail\": \"%s deleted\", \"id\": 1 }" % label,
            })
        else:
            out.append({
                "method": "POST / PATCH / DELETE", "path": path, "auth": "Refused",
                "summary": "%s is a read-only mirror of Zoho Books. Writes return 405 — raise or "
                           "edit the document in Zoho Books." % plural,
                "usage": "# not available by design",
                "response": "{ \"detail\": \"%s is a read-only mirror of Zoho Books...\" }" % plural,
            })

        out.append({
            "method": "GET", "path": path + "/{id}/remarks", "auth": "Bearer / Cookie",
            "summary": "Append-only remark history for one %s." % label.lower(),
            "usage": "curl %s%s/1/remarks \\\n  -H \"Authorization: Bearer $TOKEN\"" % (base, path),
            "response": "{ \"remarks\": [ { \"body\": \"...\", \"author\": \"...\" } ] }",
        })
        out.append({
            "method": "POST", "path": path + "/{id}/remarks", "auth": "Bearer / Cookie",
            "summary": "Append a remark. Never edited or deleted — a correction is a new remark. "
                       "Pass external_ref to make a replay idempotent.",
            "usage": "curl -X POST %s%s/1/remarks \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                     "  -H 'Content-Type: application/json' \\\n"
                     "  -d '{\"body\":\"Spoke to them today.\"}'" % (base, path),
            "response": "{ \"id\": 7, \"author\": \"Meet Deshani\", \"duplicate\": false }",
        })
        out.append({
            "method": "GET", "path": path + "/{id}/attachments", "auth": "Bearer / Cookie",
            "summary": "Files linked to one %s. `kind` is derived from the URL shape — Google Doc, "
                       "Google Sheet, Google Slides, Drive file, Drive folder — with no "
                       "credentials involved." % label.lower(),
            "usage": "curl %s%s/1/attachments \\\n  -H \"Authorization: Bearer $TOKEN\"" % (base, path),
            "response": "{ \"attachments\": [ { \"filename\": \"Scope\", \"url\": \"https://docs.google...\","
                        " \"kind\": \"Google Doc\" } ] }",
        })
        out.append({
            "method": "POST", "path": path + "/{id}/attachments", "auth": "Bearer / Cookie",
            "summary": "Attach a link to this %s. Stores the URL, never the bytes — HQ's container "
                       "has no disk that survives a deploy. Needs `%s:update`. With no filename, "
                       "the link's own kind is used so an attachment is never nameless."
                       % (label.lower(), key),
            "usage": "curl -X POST %s%s/1/attachments \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                     "  -H 'Content-Type: application/json' \\\n"
                     "  -d '{\"url\":\"https://docs.google.com/document/d/abc/edit\",\"filename\":\"Scope\"}'"
                     % (base, path),
            "response": "{ \"id\": 3, \"filename\": \"Scope\", \"kind\": \"Google Doc\" }",
        })
        out.append({
            "method": "POST", "path": path + "/{id}/attachments/upload", "auth": "Bearer / Cookie",
            "summary": "Upload a file to Google Drive and attach the link to this %s. multipart/"
                       "form-data, field `file`. The bytes go straight to Drive and are never "
                       "written to HQ's filesystem, which does not survive a deploy. 400 with the "
                       "setup instructions when Drive is not configured — an upload button that "
                       "accepts a file and loses it is worse than one that says it cannot take it. "
                       "Needs `%s:update`." % (label.lower(), key),
            "usage": "curl -X POST %s%s/1/attachments/upload \\\n  -H \"Authorization: Bearer $TOKEN\" \\\n"
                     "  -F 'file=@scope.pdf'" % (base, path),
            "response": "{ \"id\": 4, \"filename\": \"scope.pdf\", \"kind\": \"Drive file\","
                        " \"url\": \"https://drive.google.com/file/d/.../view\" }",
        })
        out.append({
            "method": "DELETE", "path": path + "/{id}/attachments/{attachment_id}", "auth": "Bearer / Cookie",
            "summary": "Unlink a file from this %s. Removes HQ's reference only — whatever the link "
                       "points at is untouched, because HQ never held it." % label.lower(),
            "usage": "curl -X DELETE %s%s/1/attachments/3 \\\n  -H \"Authorization: Bearer $TOKEN\"" % (base, path),
            "response": "{ \"detail\": \"Attachment removed\", \"id\": 3 }",
        })

        for action in ent.get("actions", []):
            out.append({
                "method": action["method"], "path": action["path"], "auth": "Bearer / Cookie",
                "summary": action.get("description") or action["label"],
                "usage": "curl -X %s %s%s \\\n  -H \"Authorization: Bearer $TOKEN\""
                         % (action["method"], base, action["path"].replace("{id}", "1")),
                "response": "{ ... }",
            })
    return out
