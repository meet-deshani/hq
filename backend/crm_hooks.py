"""Per-entity write hooks.

The generic CRUD router deliberately knows nothing about any particular entity.
A few entities still need behaviour on write — a ticket's SLA clock has to start
when the ticket is raised, not when someone remembers to type a date. Rather
than special-casing the router, an entity declares a hook and the router calls
it. Registered here so the registry stays declarative data.
"""

import logging
from datetime import timedelta

logging.getLogger(__name__)


def _sla_targets(db, ticket):
    """The response/resolution promise that applies to this ticket."""
    from backend.crm_models import SlaPolicy

    policy = None
    if ticket.sla_policy_id:
        policy = db.query(SlaPolicy).filter(SlaPolicy.id == ticket.sla_policy_id).first()
    if policy is None:
        policy = db.query(SlaPolicy).filter(
            SlaPolicy.organisation_id == ticket.organisation_id,
            SlaPolicy.is_default == True,  # noqa: E712
        ).first()
    if policy is None:
        return None, None
    targets = (policy.targets or {}).get(ticket.priority or "medium") or {}
    return policy, targets


def stamp_ticket_sla(db, obj, ent, action, user):
    """Start (or re-base) a ticket's SLA clock.

    Without this the two due-at columns were only ever set by hand, so the
    Tickets dashboard's "Breaching SLA" tile could never be anything but zero —
    a number that looks like a control and is actually decorative.

    Re-based on a priority change, because promoting a ticket to urgent should
    pull its deadline in rather than leave the old one standing. Never moves a
    deadline that a human has already met: `first_responded_at` and
    `resolved_at` are facts about the past.
    """
    from datetime import datetime

    policy, targets = _sla_targets(db, obj)
    if policy is None or not targets:
        return

    if obj.sla_policy_id is None:
        obj.sla_policy_id = policy.id

    started = obj.created_at or datetime.utcnow()
    response_hours = targets.get("response_hours")
    resolution_hours = targets.get("resolution_hours")

    if response_hours and obj.first_responded_at is None:
        obj.first_response_due_at = started + timedelta(hours=float(response_hours))
    if resolution_hours and obj.resolved_at is None:
        obj.resolution_due_at = started + timedelta(hours=float(resolution_hours))

    # Breach flags are derived, never typed. Computed here so the list and the
    # dashboard agree without either running its own query.
    now = datetime.utcnow()
    obj.response_sla_breached = bool(
        obj.first_response_due_at
        and (obj.first_responded_at or now) > obj.first_response_due_at
    )
    obj.resolution_sla_breached = bool(
        obj.resolution_due_at
        and (obj.resolved_at or now) > obj.resolution_due_at
    )


def stamp_ticket_lifecycle(db, obj, ent, action, user):
    """Record when a ticket actually changed state, so the SLA has facts to use."""
    from datetime import datetime

    now = datetime.utcnow()
    if obj.status in ("resolved", "closed") and obj.resolved_at is None:
        obj.resolved_at = now
    if obj.status == "closed" and obj.closed_at is None:
        obj.closed_at = now
    # Reopening clears the resolution so the clock is honest about it.
    if obj.status in ("new", "open", "waiting_on_customer", "on_hold") and obj.resolved_at:
        obj.resolved_at = None
        obj.closed_at = None
        obj.reopened_count = (obj.reopened_count or 0) + 1


def on_ticket_write(db, obj, ent, action, user):
    stamp_ticket_lifecycle(db, obj, ent, action, user)
    stamp_ticket_sla(db, obj, ent, action, user)


def on_lead_write(db, obj, ent, action, user):
    """Keep the customer, the project and the tasks in step with the lead.

    Marking a lead won is the whole decision — it should not also require
    remembering to press Convert, then to open a project, then to move the tasks
    across. Any write that leaves the lead won does all four, and a lead saved
    against an existing customer links to them instead of minting a second copy
    of a company already in the book.

    Delegates to `crud.sync_lead_outcome`, which is written to be total and
    idempotent, because `_run_hook` swallows what this raises: a conversion that
    could half-fail would leave a lead marked won with no customer and say
    nothing about it. Imported here rather than at module scope — crud imports
    this module, and the cycle is real.
    """
    from backend.crud import sync_lead_outcome

    sync_lead_outcome(db, obj, user)


HOOKS = {
    "tickets": on_ticket_write,
    "leads": on_lead_write,
}
