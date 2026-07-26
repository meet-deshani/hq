"""TabDesk — the column type catalogue, JSON querying, and the SQL views.

Three jobs that all come down to the same problem: TabDesk values live inside a
JSON blob, and SQLite (local dev) and Postgres (production) disagree about how to
reach into one.

1. **``TYPES``** — the catalogue. Each type carries its write-side coercion, the
   SQL kind it flattens to, and the filter operators it accepts. Adding a column
   type means adding one entry here; nothing else in the platform enumerates them.

2. **Querying** — filter and sort expressions over ``tabdesk_rows.data``. These go
   through SQLAlchemy's JSON accessors (``col.data[key].as_string()``), which
   compile to ``json_extract`` on SQLite and ``->>`` on Postgres, so almost none
   of this file is dialect-specific. Array containment (``has``) is the one
   operator with no portable spelling, and it is written per dialect.

3. **Views** — one read-only SQL view per table, flattening JSON into typed
   columns so pgAdmin and Metabase can read a TabDesk table like a normal one.

The safety rules for the view path, all of them learned the expensive way in
other systems:

* Rebuilt from scratch on every schema change, never patched. A view that
  disagrees with its table is worse than no view, because it looks authoritative.
* Every numeric/date cast is guarded. On Postgres ``(data->>'x')::numeric``
  RAISES on an empty string — one bad cell would break the whole view for every
  reader, so casts are wrapped in a pattern test that yields NULL instead.
* No user input reaches DDL. Identifiers are rebuilt from ``[a-z0-9_]`` only.
* A failed rebuild is logged, never raised. The app never reads these views; an
  external convenience must not be able to fail a user's save.
"""

import json
import logging
import re
from datetime import date, datetime

from sqlalchemy import or_, text

logger = logging.getLogger("tabdesk.sql")


class BadValue(ValueError):
    """Raised for a value that does not fit its column type.

    Carries a message written for the person who typed the value, because it is
    surfaced verbatim as the 400 on their save.
    """


# ── the type catalogue ──────────────────────────────────────────────────────

STRINGY = ["eq", "ne", "empty", "contains", "startswith", "in"]
NUMERIC = ["eq", "ne", "empty", "gt", "gte", "lt", "lte"]
CHOICE = ["eq", "ne", "empty", "in"]
ARRAY = ["empty", "has", "in"]


def _s(value):
    """Coerce to a trimmed string, with empty meaning absent."""
    if value is None:
        return None
    out = str(value).strip()
    return out or None


def _num(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise BadValue("expected a number, got a checkbox value")
    try:
        # Tolerate the thousands separators and currency symbols people paste in
        # from a spreadsheet. Rejecting "45,000" would be technically correct and
        # practically useless.
        if isinstance(value, str):
            value = re.sub(r"[,\s₹$€£]", "", value)
        out = float(value)
    except (TypeError, ValueError):
        raise BadValue("%r is not a number" % value)
    if out != out or out in (float("inf"), float("-inf")):
        raise BadValue("%r is not a finite number" % value)
    # Keep integers as ints so JSON does not render 45000.0 in the grid.
    return int(out) if out == int(out) and abs(out) < 2 ** 53 else out


def _date(value):
    got = _s(value)
    if got is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    got = got[:10]
    try:
        return date.fromisoformat(got).isoformat()
    except ValueError:
        raise BadValue("%r is not a date (expected YYYY-MM-DD)" % value)


def _datetime(value):
    got = _s(value)
    if got is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    try:
        # Accept a trailing Z, which fromisoformat rejects before 3.11.
        return datetime.fromisoformat(got.replace("Z", "+00:00")).replace(microsecond=0).isoformat()
    except ValueError:
        raise BadValue("%r is not a date and time (expected ISO 8601)" % value)


def _bool(value):
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _int_id(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise BadValue("%r is not a record id" % value)


def _id_list(value):
    """A relation's value: a list of integer ids, de-duplicated, order kept."""
    if value is None or value == "":
        return []
    if not isinstance(value, (list, tuple)):
        value = [value]
    out = []
    for item in value:
        got = _int_id(item)
        if got is not None and got not in out:
            out.append(got)
    return out


def _attachment(value):
    """``{url, filename}``. A link, not an upload — HQ has no upload endpoint."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        url = _s(value)
        return {"url": url, "filename": url.rsplit("/", 1)[-1]} if url else None
    if isinstance(value, dict):
        url = _s(value.get("url"))
        if not url:
            return None
        return {"url": url, "filename": _s(value.get("filename")) or url.rsplit("/", 1)[-1]}
    raise BadValue("%r is not an attachment" % value)


# sql: how the value flattens in a view and sorts in a query.
#      text | number | date | datetime | bool | json
TYPES = {
    "text":        {"label": "Text",          "coerce": _s,          "sql": "text",     "ops": STRINGY},
    "longtext":    {"label": "Long text",     "coerce": _s,          "sql": "text",     "ops": STRINGY},
    "number":      {"label": "Number",        "coerce": _num,        "sql": "number",   "ops": NUMERIC},
    "money":       {"label": "Money",         "coerce": _num,        "sql": "number",   "ops": NUMERIC},
    "percent":     {"label": "Percent",       "coerce": _num,        "sql": "number",   "ops": NUMERIC},
    "date":        {"label": "Date",          "coerce": _date,       "sql": "date",     "ops": NUMERIC},
    "datetime":    {"label": "Date and time", "coerce": _datetime,   "sql": "datetime", "ops": NUMERIC},
    "select":      {"label": "Single select", "coerce": _s,          "sql": "text",     "ops": CHOICE},
    "multiselect": {"label": "Multi select",  "coerce": None,        "sql": "json",     "ops": ARRAY},
    "checkbox":    {"label": "Checkbox",      "coerce": _bool,       "sql": "bool",     "ops": ["eq", "ne"]},
    "user":        {"label": "User",          "coerce": _int_id,     "sql": "number",   "ops": CHOICE},
    "url":         {"label": "URL",           "coerce": _s,          "sql": "text",     "ops": STRINGY},
    "email":       {"label": "Email",         "coerce": _s,          "sql": "text",     "ops": STRINGY},
    "phone":       {"label": "Phone",         "coerce": _s,          "sql": "text",     "ops": STRINGY},
    "attachment":  {"label": "Attachment",    "coerce": _attachment, "sql": "json",     "ops": ["empty"]},
    "relation":    {"label": "Relation",      "coerce": _id_list,    "sql": "json",     "ops": ARRAY},
}

# Types whose value cannot be edited usefully in a grid cell — the frontend sends
# these to the entry modal instead of offering inline edit.
MODAL_ONLY = {"longtext", "attachment", "relation", "multiselect"}

# Types the search box (?q=) scans. Searching a checkbox or an id is not useful.
SEARCHABLE = {"text", "longtext", "select", "url", "email", "phone"}


def public_types():
    """The catalogue, for the UI's column editor."""
    return [
        {
            "type": key,
            "label": spec["label"],
            "ops": spec["ops"],
            "modal_only": key in MODAL_ONLY,
            "needs_options": key in ("select", "multiselect"),
            "needs_ref": key == "relation",
        }
        for key, spec in TYPES.items()
    ]


def coerce(column, value):
    """Canonicalise one value for storage, or raise BadValue with a real reason.

    Every write goes through here, which is what lets the query and view layers
    assume the JSON is well-formed — a number is a JSON number, a date is an ISO
    string, never an empty string that would blow up a Postgres cast.
    """
    spec = TYPES.get(column.type)
    if spec is None:
        raise BadValue("unknown column type %r" % column.type)

    options = list(column.options or [])

    if column.type == "multiselect":
        if value is None or value == "":
            return []
        if not isinstance(value, (list, tuple)):
            value = [value]
        out = []
        for item in value:
            got = _s(item)
            if got is None or got in out:
                continue
            if options and got not in options:
                raise BadValue("%r is not one of the choices for %s" % (got, column.label))
            out.append(got)
        return out

    out = spec["coerce"](value)

    if column.type == "select" and out is not None and options and out not in options:
        raise BadValue("%r is not one of the choices for %s" % (out, column.label))

    if column.required and (out is None or out == [] or out == ""):
        raise BadValue("%s is required" % column.label)

    return out


# ── querying ────────────────────────────────────────────────────────────────

def _accessor(model, column):
    """A typed SQLAlchemy expression for one JSON value.

    SQLAlchemy's JSON accessors compile per dialect (``json_extract`` on SQLite,
    ``->>`` on Postgres), so this is portable without a dialect branch.
    """
    kind = TYPES[column.type]["sql"]
    element = model.data[column.key]
    if kind == "number":
        return element.as_float()
    if kind == "bool":
        return element.as_boolean()
    # date / datetime stay text on purpose: they are stored as ISO strings, whose
    # lexicographic order IS chronological order. Casting them per dialect would
    # buy nothing and risk a cast error on a malformed cell.
    return element.as_string()


def sort_expression(model, column, descending):
    expr = _accessor(model, column)
    return expr.desc() if descending else expr.asc()


def _empty_clause(model, column):
    """NULL, missing key, empty string, or empty array all count as empty."""
    as_text = model.data[column.key].as_string()
    clauses = [as_text.is_(None), as_text == ""]
    if TYPES[column.type]["sql"] == "json":
        clauses += [as_text == "[]", as_text == "null"]
    return or_(*clauses)


def _has_clause(session, model, column, wanted):
    """Array containment — the one operator with no portable spelling.

    Compares as JSON so that a relation id of 1 does not match 12, which a naive
    text LIKE over "[1,12]" would.
    """
    dialect = session.get_bind().dialect.name
    key, param = column.key, "td_has"

    if dialect == "postgresql":
        # Our column is JSON, not JSONB, so cast before using the containment
        # operator. Passing the needle as a JSON array keeps 1 from matching 12.
        clause = "(%s.data -> :td_key)::jsonb @> (:%s)::jsonb" % (model.__tablename__, param)
        return text(clause).bindparams(td_key=key, **{param: json.dumps([wanted])})

    # SQLite: walk the array and compare each element.
    clause = (
        "EXISTS (SELECT 1 FROM json_each(%s.data, '$.\"%s\"') WHERE json_each.value = :%s)"
        % (model.__tablename__, _ident(key), param)
    )
    return text(clause).bindparams(**{param: wanted})


def filter_clause(session, model, column, op, values, me):
    """One filter, as a SQL clause. Repeated values within a column mean OR.

    Raises BadValue on an operator the type does not accept. An unsupported
    filter must never be silently dropped: a caller asking "does this row exist?"
    with a bad filter would get the whole unfiltered table back and conclude yes.
    """
    spec = TYPES.get(column.type)
    if spec is None:
        raise BadValue("unknown column type %r" % column.type)
    if op not in spec["ops"] and op != "empty":
        raise BadValue(
            "'%s' does not support the '%s' filter. It accepts: %s"
            % (column.label, op, ", ".join(spec["ops"]))
        )

    if op == "empty":
        wanted = _bool(values[0] if values else True)
        clause = _empty_clause(model, column)
        return clause if wanted else ~clause

    def resolve(raw):
        """`me` resolves to the caller, so a saved view can say "mine"."""
        if raw == "me" and column.type == "user":
            return me.id if me else None
        return raw

    if op == "has":
        return or_(*[_has_clause(session, model, column, resolve(v)) for v in values])

    if op == "in":
        if TYPES[column.type]["sql"] == "json":
            return or_(*[_has_clause(session, model, column, resolve(v)) for v in values])
        expr = _accessor(model, column)
        return expr.in_([_cmp_value(column, resolve(v)) for v in values])

    expr = _accessor(model, column)

    def one(raw):
        raw = resolve(raw)
        if op == "eq":
            return _empty_clause(model, column) if raw in (None, "", "null") else expr == _cmp_value(column, raw)
        if op == "ne":
            return expr != _cmp_value(column, raw)
        if op == "contains":
            return expr.ilike("%%%s%%" % str(raw).strip())
        if op == "startswith":
            return expr.ilike("%s%%" % str(raw).strip())
        if op == "gt":
            return expr > _cmp_value(column, raw)
        if op == "gte":
            return expr >= _cmp_value(column, raw)
        if op == "lt":
            return expr < _cmp_value(column, raw)
        if op == "lte":
            return expr <= _cmp_value(column, raw)
        raise BadValue("unknown filter operator %r" % op)

    clauses = [one(v) for v in values]
    return clauses[0] if len(clauses) == 1 else or_(*clauses)


def _cmp_value(column, raw):
    """Coerce a filter's argument the same way a stored value is coerced.

    Comparing the string "45000" against a JSON number would depend on the
    dialect's coercion rules; comparing 45000.0 does not.
    """
    kind = TYPES[column.type]["sql"]
    try:
        if kind == "number":
            return _num(raw)
        if kind == "bool":
            return _bool(raw)
        if kind == "date":
            return _date(raw)
        if kind == "datetime":
            return _datetime(raw)
    except BadValue:
        raise
    return _s(raw)


def search_clause(model, columns, term):
    """?q= over every text-ish column. Nothing to scan means no filter."""
    term = (term or "").strip()
    if not term:
        return None
    like = "%%%s%%" % term
    clauses = [
        model.data[c.key].as_string().ilike(like)
        for c in columns
        if c.type in SEARCHABLE
    ]
    return or_(*clauses) if clauses else None


# ── the SQL views ───────────────────────────────────────────────────────────

def _ident(raw):
    """A SQL identifier rebuilt from scratch. User input never survives this."""
    out = re.sub(r"[^a-z0-9_]", "_", str(raw or "").lower()).strip("_")
    out = re.sub(r"_+", "_", out)
    return out[:48] or "col"


def view_name(table):
    """``tabdesk_v_<id>_<slug>``.

    The id is in the name because ``slug`` is only unique per organisation, and a
    second organisation reusing a slug would otherwise collide with an existing
    view — which, since a failed rebuild is deliberately non-fatal, would fail
    silently and leave BI reading another org's table.
    """
    return "tabdesk_v_%d_%s" % (table.id, _ident(table.slug))


def _pg_expr(key, kind):
    """A NULL-safe Postgres expression for one JSON value.

    The pattern tests are the point. ``(data->>'amount')::numeric`` raises on an
    empty string or stray text, and because a view is one statement, a single bad
    cell would take out every column for every reader. A guarded cast yields NULL
    for that cell and keeps the rest readable.
    """
    raw = "data ->> '%s'" % key
    if kind == "number":
        return ("CASE WHEN %s ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (%s)::numeric END" % (raw, raw))
    if kind == "date":
        return ("CASE WHEN %s ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN (%s)::date END" % (raw, raw))
    if kind == "datetime":
        return ("CASE WHEN %s ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]' THEN (%s)::timestamp END" % (raw, raw))
    if kind == "bool":
        return (
            "CASE WHEN lower(%s) IN ('true','1','t','yes') THEN true "
            "WHEN lower(%s) IN ('false','0','f','no') THEN false END" % (raw, raw)
        )
    if kind == "json":
        return "data -> '%s'" % key
    return raw


def _sqlite_expr(key, kind):
    """SQLite needs no guards: CAST is lenient there and never raises."""
    raw = "json_extract(data, '$.\"%s\"')" % key
    if kind == "number":
        return "CAST(%s AS REAL)" % raw
    return raw


def sync_view(session, table, columns):
    """Drop and recreate this table's view. Idempotent, and never raises.

    Called after every schema change. Rebuilding wholesale rather than patching
    is what keeps the view honest: there is no path where it ends up describing
    a shape the table no longer has.
    """
    name = view_name(table)
    dialect = session.get_bind().dialect.name
    build = _pg_expr if dialect == "postgresql" else _sqlite_expr

    seen, selects = set(), ["id", "created_at", "updated_at", "created_by_id"]
    for column in columns:
        alias = _ident(column.key)
        if alias in seen or alias in ("id", "created_at", "updated_at", "created_by_id"):
            alias = "%s_%d" % (alias, column.id)
        seen.add(alias)
        kind = TYPES.get(column.type, {}).get("sql", "text")
        selects.append('%s AS "%s"' % (build(_ident(column.key), kind), alias))

    sql = 'CREATE VIEW %s AS SELECT %s FROM tabdesk_rows WHERE table_id = %d' % (
        name, ", ".join(selects), table.id,
    )

    try:
        session.execute(text("DROP VIEW IF EXISTS %s" % name))
        session.execute(text(sql))
        session.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — a convenience must not fail a save
        session.rollback()
        logger.warning("TabDesk view %s not rebuilt: %s", name, exc)
        return False


def drop_view(session, table):
    try:
        session.execute(text("DROP VIEW IF EXISTS %s" % view_name(table)))
        session.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning("TabDesk view for table %s not dropped: %s", table.id, exc)
        return False
