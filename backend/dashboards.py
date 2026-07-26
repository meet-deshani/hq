"""Per-workspace dashboard metrics.

Every workspace used to render the same six numbers — total users, roles,
permissions, organisations, products, workspaces. That is platform plumbing, and
on a CRM dashboard it is worse than empty: it looks like information while
answering nothing anyone opened the page to ask.

Each workspace now answers its own question:

    CRM         who are our customers and what is in flight
    Work        what is on me today, and what has slipped
    Tickets     what is waiting on us, and what is breaching
    Comms       who is waiting for a reply
    Accounting  what is owed, and what is billable but unbilled
    HQ          the platform overview (the original six)

A dashboard aggregates and owns nothing. Every number here is a count or a sum
over a table another workspace writes, so a figure can never diverge from the
list it summarises.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func

from backend import crm_models as c
from backend.models import Organisation, Permission, Product, Role, User, Workspace


def _stat(label, value, note):
    return {"l": label, "v": value, "d": note}


def _money(value):
    """Indian-grouped rupees, shortened so a tile never wraps."""
    n = float(value or 0)
    if n >= 10000000:
        return "₹%.2fCr" % (n / 10000000)
    if n >= 100000:
        return "₹%.2fL" % (n / 100000)
    return "₹%s" % format(int(n), ",d")


def _count(db, model, *filters):
    q = db.query(func.count(model.id))
    for f in filters:
        q = q.filter(f)
    return q.scalar() or 0


def _sum(db, column, *filters):
    q = db.query(func.coalesce(func.sum(column), 0))
    for f in filters:
        q = q.filter(f)
    return q.scalar() or 0


# ── per-workspace builders ──────────────────────────────────────────────────

def _crm(db, user):
    today = date.today()
    customers = _count(db, c.Party, c.Party.kind.in_(["customer", "both"]))
    prospects = _count(db, c.Party, c.Party.kind == "prospect")
    open_leads = _count(db, c.Lead, c.Lead.status == "open")
    pipeline = _sum(db, c.Lead.estimated_value, c.Lead.status == "open")
    active = _count(db, c.Project, c.Project.status == "active")
    completed = _count(db, c.Project, c.Project.stage == "Project Completed")
    slipped = _count(
        db, c.Project,
        c.Project.next_action_date < today,
        c.Project.status == "active",
    )
    monthly = _sum(db, c.Project.monthly_amount, c.Project.status == "active")

    return [
        _stat("Customers", str(customers), "→ %d prospect%s" % (prospects, "" if prospects == 1 else "s")),
        _stat("Open leads", str(open_leads), "→ %s in pipeline" % _money(pipeline)),
        _stat("Active projects", str(active), "→ %d completed" % completed),
        _stat("Next actions overdue", str(slipped),
              "→ all on track" if slipped == 0 else "↘ needs attention"),
        _stat("Monthly recurring", _money(monthly), "→ across active projects"),
        _stat("Outstanding", _money(_sum(db, c.Party.outstanding_amount)), "→ per Zoho Books"),
    ]


def _work(db, user):
    today = date.today()
    week_ago = datetime.utcnow() - timedelta(days=7)
    open_states = ["open", "in_progress", "blocked"]

    mine = _count(db, c.Task, c.Task.owner_id == user.id, c.Task.status.in_(open_states))
    return [
        _stat("Open tasks", str(_count(db, c.Task, c.Task.status.in_(open_states))),
              "→ %d assigned to you" % mine),
        _stat("Due today", str(_count(db, c.Task, c.Task.due_date == today,
                                      c.Task.status.in_(open_states))), "→ today"),
        _stat("Overdue", str(_count(db, c.Task, c.Task.due_date < today,
                                    c.Task.status.in_(open_states))), "↘ past due date"),
        _stat("Blocked", str(_count(db, c.Task, c.Task.status == "blocked")), "→ waiting on someone"),
        _stat("Done this week", str(_count(db, c.Task, c.Task.status == "done",
                                           c.Task.updated_at >= week_ago)), "↗ last 7 days"),
        _stat("Work streams", str(_count(db, c.WorkStream, c.WorkStream.status == "active")),
              "→ standing threads"),
    ]


def _tickets(db, user):
    now = datetime.utcnow()
    month_start = date.today().replace(day=1)
    open_states = ["new", "open", "waiting_on_customer", "on_hold"]

    breaching = _count(
        db, c.Ticket,
        c.Ticket.resolution_due_at < now,
        c.Ticket.status.in_(open_states),
    )
    return [
        _stat("Open tickets", str(_count(db, c.Ticket, c.Ticket.status.in_(open_states))),
              "→ awaiting us"),
        _stat("Unassigned", str(_count(db, c.Ticket, c.Ticket.assigned_to.is_(None),
                                       c.Ticket.status.in_(open_states))), "↘ nobody owns these"),
        _stat("Breaching SLA", str(breaching),
              "→ within promise" if breaching == 0 else "↘ past resolution due"),
        _stat("Urgent", str(_count(db, c.Ticket, c.Ticket.priority.in_(["high", "urgent"]),
                                   c.Ticket.status.in_(open_states))), "→ high or urgent"),
        _stat("Resolved this month", str(_count(db, c.Ticket, c.Ticket.resolved_at >= month_start)),
              "↗ since the 1st"),
        _stat("Job types", str(_count(db, c.TicketCategory, c.TicketCategory.is_active == True)),  # noqa: E712
              "→ configured"),
    ]


def _comms(db, user):
    open_convs = _count(db, c.Conversation, c.Conversation.status == "open")
    return [
        _stat("Open threads", str(open_convs), "→ awaiting a reply"),
        _stat("Unassigned", str(_count(db, c.Conversation, c.Conversation.assigned_to.is_(None),
                                       c.Conversation.status == "open")), "↘ nobody owns these"),
        _stat("Unread", str(_sum(db, c.Conversation.unread_count)), "→ messages"),
        _stat("Not linked", str(_count(db, c.Conversation, c.Conversation.party_id.is_(None))),
              "→ no customer attached"),
        _stat("Channels", str(_count(db, c.CommChannel, c.CommChannel.status == "active")),
              "→ connected"),
        _stat("Messages", str(_count(db, c.ConversationMessage)), "→ on record"),
    ]


def _accounting(db, user):
    today = date.today()
    outstanding = _sum(db, c.Party.outstanding_amount)
    to_raise = _sum(db, c.ContractBillingSchedule.amount,
                    c.ContractBillingSchedule.status == "pending")
    overdue_invoices = _count(db, c.ZohoInvoice, c.ZohoInvoice.balance_due > 0,
                              c.ZohoInvoice.due_date < today)
    active_contracts = _count(db, c.Contract, c.Contract.status.in_(["active", "signed"]))

    return [
        _stat("Outstanding", _money(outstanding), "→ per Zoho Books"),
        _stat("Billable, unbilled", _money(to_raise), "→ schedule lines pending"),
        _stat("Active contracts", str(active_contracts),
              "→ %s total value" % _money(_sum(db, c.Contract.value,
                                               c.Contract.status.in_(["active", "signed"])))),
        _stat("Monthly contracted", _money(_sum(db, c.Contract.monthly_value,
                                                c.Contract.status.in_(["active", "signed"]))),
              "→ recurring"),
        _stat("Overdue invoices", str(overdue_invoices),
              "→ none past due" if overdue_invoices == 0 else "↘ past due date"),
        _stat("Renewals due", str(_count(db, c.Contract,
                                         c.Contract.renewal_date >= today,
                                         c.Contract.renewal_date <= today + timedelta(days=60))),
              "→ next 60 days"),
    ]


def _platform(db, user):
    active_users = _count(db, User, User.status == "Active")
    return [
        _stat("Customers", str(_count(db, c.Party)), "→ on the books"),
        _stat("Projects", str(_count(db, c.Project)), "→ delivered and in flight"),
        _stat("Open tasks", str(_count(db, c.Task, c.Task.status.in_(["open", "in_progress", "blocked"]))),
              "→ across everyone"),
        _stat("Team", str(_count(db, User)), "↗ %d active" % active_users),
        _stat("Roles", str(_count(db, Role)), "→ %d permissions" % _count(db, Permission)),
        _stat("Workspaces", str(_count(db, Workspace)), "→ %d product(s)" % _count(db, Product)),
    ]


BUILDERS = {
    "crm": _crm,
    "work": _work,
    "tickets": _tickets,
    "comms": _comms,
    "communication": _comms,
    "accounting": _accounting,
    "hq": _platform,
}

# Which table's growth the trend line plots, per workspace.
TREND_MODELS = {
    "crm": (c.Party, "Customers"),
    "work": (c.Task, "Tasks"),
    "tickets": (c.Ticket, "Tickets"),
    "comms": (c.Conversation, "Conversations"),
    "communication": (c.Conversation, "Conversations"),
    "accounting": (c.Contract, "Contracts"),
}


def stats_for(db, user, workspace):
    builder = BUILDERS.get((workspace or "hq").strip().lower(), _platform)
    return builder(db, user)


def trend_for(db, workspace):
    """Cumulative growth of the workspace's primary record over six months."""
    key = (workspace or "hq").strip().lower()
    model, label = TREND_MODELS.get(key, (None, "Records"))

    now = datetime.utcnow()
    months = []
    for i in range(5, -1, -1):
        mm, yy = now.month - i, now.year
        while mm <= 0:
            mm += 12
            yy -= 1
        months.append((yy, mm))

    if model is None:
        # The platform view counts everything that has a created_at.
        stamps = []
        for m in (User, Organisation, Product, Workspace, Role, c.Party, c.Project, c.Task):
            stamps += [r[0] for r in db.query(m.created_at).all() if r[0] is not None]
    else:
        stamps = [r[0] for r in db.query(model.created_at).all() if r[0] is not None]

    points = []
    for (yy, mm) in months:
        nm, ny = (mm + 1, yy) if mm < 12 else (1, yy + 1)
        boundary = datetime(ny, nm, 1)
        points.append({"label": datetime(yy, mm, 1).strftime("%b"),
                       "value": sum(1 for s in stamps if s < boundary)})
    return {"points": points, "label": label}
