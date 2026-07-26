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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import audit, permissions, registry
from backend.auth import get_current_user
from backend.crm_models import Activity, Attachment, AuditLog, Comment, Lead, Party
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


def _commit(db, ent, what="save"):
    """Commit, turning a constraint violation into a 409 instead of a 500.

    Most violations here are a duplicate natural key — a second customer with
    the same name, a second lead source called the same thing. That is a
    conflict the caller can act on, not a server fault.
    """
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        detail = "That %s conflicts with an existing record." % ent["label"].lower()
        raw = str(getattr(exc, "orig", exc))
        if "UNIQUE" in raw.upper():
            detail = ("A %s with those details already exists. "
                      "Names must be unique within the organisation." % ent["label"].lower())
        raise HTTPException(status_code=409, detail=detail)


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
    obj = _get_row(db, ent, row_id)
    allowed = _writable(ent)
    before = audit.snapshot(obj)

    for name, value in (payload or {}).items():
        if name in allowed and name not in (ent.get("scope") or {}):
            setattr(obj, name, _coerce(ent, name, value))

    if _column(ent, "updated_by_id") is not None:
        obj.updated_by_id = current_user.id

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

@router.post("/api/leads/{lead_id}/convert")
def convert_lead(
    lead_id: int,
    request: Request,
    payload: dict = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Turn a won lead into a customer.

    The lead is kept and stamped, never deleted — the funnel history is the
    reason the lead existed. Converting twice returns the existing customer
    rather than creating a second one.
    """
    permissions.require(current_user, "leads", "update")
    permissions.require(current_user, "customers", "create")
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead %s not found" % lead_id)

    if lead.converted_party_id:
        existing = db.query(Party).filter(Party.id == lead.converted_party_id).first()
        if existing:
            ent = registry.BY_KEY["customers"]
            return {
                "detail": "Lead already converted",
                "already_converted": True,
                "customer": serialize(existing, ent, _resolve_refs(db, ent, [existing])),
            }

    payload = payload or {}
    name = (payload.get("display_name") or lead.company_name or lead.title or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Lead has no company name — pass display_name")

    clash = db.query(Party).filter(
        Party.display_name == name, Party.organisation_id == lead.organisation_id
    ).first()
    if clash:
        raise HTTPException(
            status_code=409,
            detail="A customer named '%s' already exists (id %s). Link it manually or rename." % (name, clash.id),
        )

    party = Party(
        organisation_id=lead.organisation_id or current_user.organisation_id,
        kind=payload.get("kind") or "customer",
        display_name=name,
        phone=lead.phone,
        email=lead.email,
        owner_id=lead.owner_id or current_user.id,
        status="Active",
        summary=lead.notes,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    db.add(party)
    db.flush()

    if lead.contact_name:
        from backend.crm_models import PartyContact

        db.add(PartyContact(
            organisation_id=party.organisation_id, party_id=party.id, name=lead.contact_name,
            phone=lead.phone, email=lead.email, is_primary=True,
            created_by_id=current_user.id, updated_by_id=current_user.id,
        ))

    lead.converted_party_id = party.id
    lead.converted_at = datetime.utcnow()
    lead.status = "won"
    lead.updated_by_id = current_user.id
    db.commit()
    db.refresh(party)

    audit.record(
        db, action="convert", entity_type="leads", entity_id=lead.id, entity_label=lead.title,
        actor=current_user, request=request,
        changes={"converted_party_id": {"from": None, "to": party.id}, "status": {"from": "open", "to": "won"}},
        organisation_id=lead.organisation_id,
    )
    audit.record(
        db, action="create", entity_type="parties", entity_id=party.id, entity_label=party.display_name,
        actor=current_user, request=request,
        changes={"converted_from_lead": {"from": None, "to": lead.id}},
        organisation_id=party.organisation_id, commit=True,
    )

    ent = registry.BY_KEY["customers"]
    return {
        "detail": "Lead converted",
        "already_converted": False,
        "lead_id": lead.id,
        "customer": serialize(party, ent, _resolve_refs(db, ent, [party])),
    }
