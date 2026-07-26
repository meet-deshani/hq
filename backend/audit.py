"""Audit trail — every mutation, by anyone, forever.

Three people share this platform and agents write to it too, so "who changed
this and when" has to be answerable without trusting anyone's memory. Every
create, update and delete goes through :func:`record`, which writes one
``audit_logs`` row carrying the actor, the action, and — for updates — a
field-level before/after diff.

The actor's email is denormalised onto the row on purpose: the trail has to
survive the user being deleted, and a dangling `actor_user_id` would turn
history into anonymous noise.
"""

import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.crm_models import AuditLog

logger = logging.getLogger("audit")

# Columns that describe *when/who* a row changed rather than what it means.
# Diffing them adds noise to every single update, so they are excluded.
_NOISE_FIELDS = {"updated_at", "created_at", "updated_by_id", "created_by_id"}


def _plain(value):
    """Make a column value JSON-serialisable without losing meaning."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (str, int, float, bool, type(None), list, dict)):
        return value
    return str(value)


def snapshot(obj):
    """Field values of a mapped row, as a plain dict."""
    if obj is None:
        return {}
    return {
        c.key: _plain(getattr(obj, c.key, None))
        for c in obj.__table__.columns
        if c.key not in _NOISE_FIELDS
    }


def diff(before, after):
    """Field-level {field: {from, to}} for the values that actually changed."""
    out = {}
    for key in set(before) | set(after):
        old, new = before.get(key), after.get(key)
        if old != new:
            out[key] = {"from": old, "to": new}
    return out


def actor_kind(request):
    """Tell a human, a CLI and an agent apart from the request itself.

    The CLI and agents identify themselves with an X-HQ-Client header; anything
    else arriving with a browser user-agent is treated as a person.
    """
    if request is None:
        return "system"
    declared = (request.headers.get("X-HQ-Client") or "").strip().lower()
    if declared in ("cli", "agent", "system"):
        return declared
    return "user"


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id=None,
    entity_label=None,
    actor=None,
    request=None,
    changes=None,
    organisation_id=None,
    commit: bool = False,
):
    """Write one audit row. Never raises into the caller's request.

    An audit write failing must not roll back or 500 the business write that
    succeeded — it is recorded as an error and the mutation stands.
    """
    try:
        entry = AuditLog(
            organisation_id=organisation_id or getattr(actor, "organisation_id", None),
            actor_user_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", None),
            actor_kind=actor_kind(request),
            entity_type=entity_type,
            entity_id=entity_id,
            entity_label=(str(entity_label)[:300] if entity_label is not None else None),
            action=action,
            changes=changes or None,
            request_path=(str(request.url.path)[:300] if request is not None else None),
            ip=(request.client.host if request is not None and request.client else None),
            user_agent=((request.headers.get("user-agent") or "")[:300] if request is not None else None),
        )
        db.add(entry)
        if commit:
            db.commit()
        return entry
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to write audit log for %s %s: %s", action, entity_type, exc)
        return None
