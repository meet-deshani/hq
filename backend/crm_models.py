"""CRM / delivery / task tables for HQ.

Table and column names follow the Super-App module registry (parties, items,
projects, milestones, tasks, leads, ...) so nothing here is an invented entity.

Two deliberate deviations from the registry, both documented rather than silent:

1. The registry scopes rows with ``org_id``. This codebase already scopes with
   ``organisation_id`` (products, workspaces, roles, users). One schema with two
   spellings of the same foreign key is worse than one consistent spelling, so
   everything below uses ``organisation_id``.
2. ``work_streams`` / ``work_stream_members`` have no registry equivalent. They
   model the 00-Brain "Work" join — a standing stream of work keyed by a set of
   people — which the registry has no table for. Flagged as a registry
   amendment, not smuggled in as a helpdesk or project table.

Every business table carries the same provenance columns — ``created_at``,
``updated_at``, ``created_by_id``, ``updated_by_id`` — so no row is anonymous or
undated. ``audit_logs`` keeps the full change history; those four columns keep
the latest answer on the row so a list view never needs a join to show
attribution. That is what makes one platform auditable for Meet, Nishant and
Hemish at the same time.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.database import Base


def _org_fk():
    return Column(
        Integer,
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )


def _actor_fk():
    return Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)


# ────────────────────────────────────────────────────────────────────────────
# B1 · parties — THE master record for any external party.
# Customers, prospects and vendors are one table with a `kind`, never three.
# ────────────────────────────────────────────────────────────────────────────

class PartyGroup(Base):
    """Segmentation bucket — 'Water Treatment', 'Transformers', tiers."""

    __tablename__ = "party_groups"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_party_groups_org_name"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    name = Column(String(150), nullable=False)
    description = Column(String(255))
    color = Column(String(20), default="#C8B6FF")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    parties = relationship("Party", back_populates="group")


class Party(Base):
    """A customer, prospect or vendor. The single system of record.

    Tickets, projects, invoices and conversations all point here; none of them
    keeps its own copy of a customer.
    """

    __tablename__ = "parties"
    __table_args__ = (UniqueConstraint("organisation_id", "display_name", name="uq_parties_org_name"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()

    kind = Column(String(20), default="customer", nullable=False, index=True)  # customer | vendor | both | prospect
    display_name = Column(String(200), nullable=False, index=True)
    legal_name = Column(String(200))
    initials = Column(String(8))
    party_group_id = Column(Integer, ForeignKey("party_groups.id", ondelete="SET NULL"), nullable=True, index=True)

    # The Z9S-side account owner ("Z9S POC") — a user of THIS platform, not a
    # contact at the customer. PRD §5.8 item 6.
    owner_id = _actor_fk()

    # India tax identity
    gstin = Column(String(20))
    gst_treatment = Column(String(30), default="regular")  # regular|composition|unregistered|consumer|overseas|sez
    pan = Column(String(15))

    phone = Column(String(40))
    email = Column(String(150))
    website = Column(String(200))

    billing_address = Column(String(400))
    city = Column(String(100))
    state_code = Column(String(10))
    pincode = Column(String(12))

    credit_limit = Column(Numeric(14, 2))
    credit_days = Column(Integer)

    industry = Column(String(150))

    # Zoho Books is the system of record for money. HQ links to the contact and
    # mirrors its receivable for display; it never writes an invoice.
    # The names differ between the systems ("Michael Bhai" here is
    # "GOA TRADING & TECHNICAL SERVICES" there), so the id is the only safe join.
    zoho_contact_id = Column(String(60), index=True)
    zoho_contact_name = Column(String(200))
    outstanding_amount = Column(Numeric(14, 2))   # mirrored from Zoho, read-only
    outstanding_synced_at = Column(DateTime)

    # Living summary — the 00-Brain "Summary callout" that gets updated over time.
    summary = Column(Text)
    notes = Column(Text)
    status = Column(String(30), default="Active", nullable=False, index=True)
    custom_fields = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    group = relationship("PartyGroup", back_populates="parties")
    owner = relationship("User", foreign_keys=[owner_id])
    contacts = relationship("PartyContact", back_populates="party", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="party")


class PartyContact(Base):
    """A person. Usually a contact at a customer; `party_id` is nullable so the
    00-Brain People pages that belong to no company (advisors, intermediaries)
    still have a home instead of forcing a fake company row.
    """

    __tablename__ = "party_contacts"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="CASCADE"), nullable=True, index=True)

    name = Column(String(150), nullable=False, index=True)
    designation = Column(String(150))  # their title AT the customer
    phone = Column(String(40))
    whatsapp = Column(String(40))
    email = Column(String(150))
    is_primary = Column(Boolean, default=False, nullable=False)

    # 00-Brain People fields: why this person matters and how to reach them.
    relevance = Column(Text)
    comms_preference = Column(String(200))
    summary = Column(Text)
    notes = Column(Text)
    status = Column(String(30), default="Active", nullable=False)
    custom_fields = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    party = relationship("Party", back_populates="contacts")


# ────────────────────────────────────────────────────────────────────────────
# C1 · crm (slim) — leads and the sales pipeline.
# The PRD leaves C1 off; Meet asked for leads explicitly, so it is on, minus
# deals/deal_items (a two-partner company does not need a second funnel object).
# ────────────────────────────────────────────────────────────────────────────

class LeadSource(Base):
    __tablename__ = "lead_sources"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_lead_sources_org_name"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    name = Column(String(120), nullable=False)
    description = Column(String(255))
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()


class LostReason(Base):
    __tablename__ = "lost_reasons"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_lost_reasons_org_name"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    name = Column(String(150), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()


class Pipeline(Base):
    __tablename__ = "pipelines"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_pipelines_org_name"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    name = Column(String(120), nullable=False)
    description = Column(String(255))
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    stages = relationship(
        "PipelineStage", back_populates="pipeline",
        cascade="all, delete-orphan", order_by="PipelineStage.sort_order",
    )


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    pipeline_id = Column(Integer, ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    probability = Column(Integer, default=0)  # 0-100
    is_won = Column(Boolean, default=False, nullable=False)
    is_lost = Column(Boolean, default=False, nullable=False)
    color = Column(String(20), default="#C8B6FF")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    pipeline = relationship("Pipeline", back_populates="stages")


class Lead(Base):
    """A piece of business being won — not necessarily a company we don't know yet.

    The original model assumed a lead is a stranger, so conversion always wrote a
    *new* `parties` row. That is only half of how the funnel actually runs. An
    existing customer asking for a second project is a lead too: same company,
    new work. Forcing that to mint a second customer is how one company ends up
    in the book twice.

    So a lead points at a party (`party_id`) whenever we already know who it is,
    and conversion links rather than duplicates. `converted_party_id` remains the
    record of *which* party this lead produced or landed on.

    Won leads also produce delivery, so `converted_project_id` records the
    project the lead became, and `item_id` is the service it is for — declared
    while the lead is still open, then carried into that project.

    The lead is never deleted on conversion — the funnel history is the point.
    """

    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()

    title = Column(String(200), nullable=False, index=True)
    company_name = Column(String(200))
    contact_name = Column(String(150))
    phone = Column(String(40))
    email = Column(String(150))

    # Who this lead is for, when we already know them. Set on a lead raised
    # against an existing customer or prospect; left null for a genuine stranger
    # until conversion resolves one.
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)

    # The service this lead is for, so a won lead knows what kind of project to
    # open. Mirrors `Project.item_id`.
    item_id = Column(Integer, ForeignKey("items.id", ondelete="SET NULL"), nullable=True, index=True)

    source_id = Column(Integer, ForeignKey("lead_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id", ondelete="SET NULL"), nullable=True, index=True)
    stage_id = Column(Integer, ForeignKey("pipeline_stages.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_id = _actor_fk()

    estimated_value = Column(Numeric(14, 2))
    monthly_value = Column(Numeric(14, 2))
    currency = Column(String(8), default="INR")
    expected_close_date = Column(Date)

    # status is the funnel outcome; stage_id is where it sits inside the funnel.
    status = Column(String(20), default="open", nullable=False, index=True)  # open | won | lost
    lost_reason_id = Column(Integer, ForeignKey("lost_reasons.id", ondelete="SET NULL"), nullable=True)
    converted_party_id = Column(Integer, ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)
    converted_project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    converted_at = Column(DateTime)

    # The Notion board's operating pattern: every row carries its next move.
    next_action = Column(String(400))
    next_action_date = Column(Date, index=True)
    next_action_owner_id = _actor_fk()

    notes = Column(Text)
    custom_fields = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    source = relationship("LeadSource")
    pipeline = relationship("Pipeline")
    stage = relationship("PipelineStage")
    owner = relationship("User", foreign_keys=[owner_id])
    party = relationship("Party", foreign_keys=[party_id])
    converted_party = relationship("Party", foreign_keys=[converted_party_id])
    converted_project = relationship("Project", foreign_keys=[converted_project_id])


# ────────────────────────────────────────────────────────────────────────────
# E1 · inventory — the catalog. Services and Products are ONE table with a
# `item_type`, split in the nav by category root, never by a second table.
# ────────────────────────────────────────────────────────────────────────────

class ItemCategory(Base):
    __tablename__ = "item_categories"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    parent_id = Column(Integer, ForeignKey("item_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(150), nullable=False)
    kind = Column(String(20), default="service", nullable=False)  # service | product
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    items = relationship("Item", back_populates="category")


class Item(Base):
    """A sellable service or product. `item_type` splits the two."""

    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("organisation_id", "code", name="uq_items_org_code"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()

    item_type = Column(String(20), default="service", nullable=False, index=True)  # service | goods
    name = Column(String(200), nullable=False, index=True)
    code = Column(String(80))
    category_id = Column(Integer, ForeignKey("item_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    description = Column(Text)

    hsn_sac_code = Column(String(20))
    gst_rate = Column(Numeric(5, 2))
    selling_price = Column(Numeric(14, 2))
    monthly_price = Column(Numeric(14, 2))
    currency = Column(String(8), default="INR")

    is_active = Column(Boolean, default=True, nullable=False)
    custom_fields = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    category = relationship("ItemCategory", back_populates="items")


# ────────────────────────────────────────────────────────────────────────────
# E4 · projects — delivery. Mirrors the live Notion board: a project is
# "<customer> — <service>", carries a delivery stage, a next action, and money.
# ────────────────────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()

    doc_no = Column(String(40), index=True)
    name = Column(String(250), nullable=False, index=True)
    description = Column(Text)
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="SET NULL"), nullable=True, index=True)
    manager_id = _actor_fk()

    # The delivery ladder actually in use, not a generic project status.
    stage = Column(String(40), default="Not started", nullable=False, index=True)
    status = Column(String(30), default="active", nullable=False, index=True)  # active|on_hold|completed|cancelled

    billing_type = Column(String(30), default="fixed")  # fixed | milestone | monthly | time_material
    one_time_amount = Column(Numeric(14, 2))
    monthly_amount = Column(Numeric(14, 2))
    currency = Column(String(8), default="INR")
    duration_months = Column(Integer)

    start_date = Column(Date)
    end_date = Column(Date)
    go_live_date = Column(Date)
    completed_on = Column(Date)
    completion_pct = Column(Integer, default=0)

    # Next action travels with the project — the Notion board's core mechanic.
    next_action = Column(String(400))
    next_action_date = Column(Date, index=True)
    next_action_owner_id = _actor_fk()

    document_url = Column(String(400))
    prod_url = Column(String(400))
    gdrive_url = Column(String(400))

    notes = Column(Text)
    custom_fields = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    party = relationship("Party", back_populates="projects")
    item = relationship("Item")
    manager = relationship("User", foreign_keys=[manager_id])
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    milestones = relationship(
        "Milestone", back_populates="project",
        cascade="all, delete-orphan", order_by="Milestone.sort_order",
    )
    tasks = relationship("Task", back_populates="project")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(30), default="member", nullable=False)  # manager | member | viewer
    allocation_pct = Column(Integer)
    joined_on = Column(Date)
    left_on = Column(Date)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    project = relationship("Project", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])


class Milestone(Base):
    __tablename__ = "milestones"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    sort_order = Column(Integer, default=0, nullable=False)
    due_date = Column(Date)
    completed_on = Column(Date)
    amount = Column(Numeric(14, 2))
    status = Column(String(30), default="pending", nullable=False)  # pending|in_progress|completed|invoiced
    # Stamped when this milestone is billed. Points at Zoho Books, which owns
    # the invoice — HQ records only that it happened.
    zoho_invoice_id = Column(String(60), index=True)
    zoho_invoice_number = Column(String(60))

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    project = relationship("Project", back_populates="milestones")


# ────────────────────────────────────────────────────────────────────────────
# NEW · work_streams — the 00-Brain "Work" join.
# A standing stream of work keyed by a set of people ("Meet x Nishant"), as
# opposed to a dated task or a delivery project. No registry equivalent.
# ────────────────────────────────────────────────────────────────────────────

class WorkStream(Base):
    __tablename__ = "work_streams"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_work_streams_org_name"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text)
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(30), default="active", nullable=False, index=True)  # active | paused | closed
    waiting_on_id = _actor_fk()
    notes = Column(Text)
    custom_fields = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    members = relationship("WorkStreamMember", back_populates="work_stream", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="work_stream")


class WorkStreamMember(Base):
    """Either a platform user or an external contact — a work stream spans both."""

    __tablename__ = "work_stream_members"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    work_stream_id = Column(Integer, ForeignKey("work_streams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    party_contact_id = Column(
        Integer, ForeignKey("party_contacts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    role = Column(String(60))

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    work_stream = relationship("WorkStream", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
    party_contact = relationship("PartyContact")


# ────────────────────────────────────────────────────────────────────────────
# E4 · tasks — the Google Tasks replacement.
# `project_id` is nullable on purpose: most of Meet's daily tasks belong to a
# person or a work stream, not a delivery project. A task that required a
# project would push half the real workload back out to Google Tasks.
# ────────────────────────────────────────────────────────────────────────────

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()

    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    milestone_id = Column(Integer, ForeignKey("milestones.id", ondelete="SET NULL"), nullable=True, index=True)
    work_stream_id = Column(Integer, ForeignKey("work_streams.id", ondelete="SET NULL"), nullable=True, index=True)
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)

    title = Column(String(400), nullable=False, index=True)
    description = Column(Text)

    owner_id = _actor_fk()
    status = Column(String(30), default="open", nullable=False, index=True)  # open|in_progress|blocked|done|cancelled
    priority = Column(String(20), default="medium", nullable=False)  # low|medium|high|urgent

    task_date = Column(Date, index=True)  # the 00-Brain date page this sits on
    start_date = Column(Date)
    due_date = Column(Date, index=True)
    completed_at = Column(DateTime)

    estimated_hours = Column(Numeric(8, 2))
    is_billable = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0)

    # Where this task came from, so an agent-written task is distinguishable
    # from one Meet typed, and so a wiki/Google row can be reconciled back.
    source = Column(String(20), default="ui", nullable=False, index=True)  # ui|api|cli|agent|import
    external_ref = Column(String(200), index=True)

    custom_fields = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    project = relationship("Project", back_populates="tasks")
    milestone = relationship("Milestone")
    work_stream = relationship("WorkStream", back_populates="tasks")
    party = relationship("Party")
    owner = relationship("User", foreign_keys=[owner_id])
    participants = relationship("TaskParticipant", back_populates="task", cascade="all, delete-orphan")


class TaskParticipant(Base):
    """The 00-Brain "For" column — who a task is *for*, distinct from its owner."""

    __tablename__ = "task_participants"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    party_contact_id = Column(
        Integer, ForeignKey("party_contacts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="CASCADE"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()

    task = relationship("Task", back_populates="participants")
    user = relationship("User", foreign_keys=[user_id])
    party_contact = relationship("PartyContact")
    party = relationship("Party")


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependencies_pair"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    depends_on_task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()


# ────────────────────────────────────────────────────────────────────────────
# A4 · shared services — polymorphic, one table each, never re-implemented
# per module. `entity_type` + `entity_id` is the POLY pair used throughout.
# ────────────────────────────────────────────────────────────────────────────

class Comment(Base):
    """Append-only discussion / Owner Remark history on any record.

    There is deliberately no update or delete endpoint for comments. The
    00-Brain rule is that history is never overwritten — a correction is a NEW
    comment, so the trail of what was believed when stays intact.
    """

    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    entity_type = Column(String(60), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    parent_comment_id = Column(Integer, ForeignKey("comments.id", ondelete="SET NULL"), nullable=True)

    author_id = _actor_fk()
    body = Column(Text, nullable=False)
    kind = Column(String(20), default="remark", nullable=False)  # remark | note | reply | correction
    source = Column(String(20), default="ui", nullable=False)  # ui|api|cli|agent|import
    external_ref = Column(String(200), index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    author = relationship("User", foreign_keys=[author_id])


class Activity(Base):
    """Calls, meetings, emails, WhatsApp, todos logged against any record."""

    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    entity_type = Column(String(60), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)

    activity_type = Column(String(30), default="note", nullable=False, index=True)
    subject = Column(String(300), nullable=False)
    body = Column(Text)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    duration_minutes = Column(Integer)
    owner_id = _actor_fk()
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)
    outcome = Column(String(60))

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_by_id = _actor_fk()

    owner = relationship("User", foreign_keys=[owner_id])
    party = relationship("Party")


class AuditLog(Base):
    """Every mutation on every entity, by anyone, forever.

    This is the table that makes the platform observable: Meet, Nishant and
    Hemish each see who changed what and when, and an agent's writes are
    distinguishable from a human's via `actor_kind`.
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()

    actor_user_id = _actor_fk()
    actor_email = Column(String(150), index=True)  # denormalised: survives user deletion
    actor_kind = Column(String(20), default="user", nullable=False, index=True)  # user|agent|cli|system

    entity_type = Column(String(60), nullable=False, index=True)
    entity_id = Column(Integer, index=True)
    entity_label = Column(String(300))  # human-readable at the time of the change
    action = Column(String(30), nullable=False, index=True)  # create|update|delete|login|logout|convert

    changes = Column(JSON)  # {field: {"from": ..., "to": ...}} — update only
    request_path = Column(String(300))
    ip = Column(String(64))
    user_agent = Column(String(300))

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    actor = relationship("User", foreign_keys=[actor_user_id])


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    entity_type = Column(String(60), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)

    filename = Column(String(300), nullable=False)
    storage_url = Column(String(600), nullable=False)
    mime = Column(String(120))
    size = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_by_id = _actor_fk()


# ────────────────────────────────────────────────────────────────────────────
# A3 · customization — saved views and terminology.
# Status filters ("Pending", "Raised", "Unpaid") are saved views over one list,
# never separate routes. PRD §6.6.
# ────────────────────────────────────────────────────────────────────────────

class SavedView(Base):
    __tablename__ = "saved_views"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    entity_type = Column(String(60), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    filters = Column(JSON, default=dict)
    columns = Column(JSON, default=list)
    sort = Column(JSON, default=dict)
    is_pinned = Column(Boolean, default=False, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()


class TerminologyOverride(Base):
    """Render-time label map. The data model never renames."""

    __tablename__ = "terminology_overrides"
    __table_args__ = (
        UniqueConstraint("organisation_id", "term_key", name="uq_terminology_org_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    term_key = Column(String(120), nullable=False, index=True)
    label = Column(String(120), nullable=False)
    plural = Column(String(120))

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()


# ────────────────────────────────────────────────────────────────────────────
# F2 · helpdesk — Tickets.
# Internal agent notes reuse the polymorphic `comments` table rather than a
# separate ticket_messages store: one discussion mechanism, not two.
# ────────────────────────────────────────────────────────────────────────────

class TicketCategory(Base):
    """Org-defined tree of request types. Labelled "Job Types" in the UI."""

    __tablename__ = "ticket_categories"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_ticket_categories_org_name"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    parent_id = Column(Integer, ForeignKey("ticket_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(150), nullable=False)
    description = Column(String(400))
    default_priority = Column(String(20), default="medium")
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()


class SlaPolicy(Base):
    """A named response/resolution promise, with per-priority targets in hours."""

    __tablename__ = "sla_policies"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_sla_policies_org_name"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    name = Column(String(150), nullable=False)
    description = Column(String(400))
    # {priority: {"response_hours": n, "resolution_hours": n}}
    targets = Column(JSON, default=dict)
    use_business_hours = Column(Boolean, default=False, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()


class Ticket(Base):
    """A client complaint or request, with its SLA timestamp trail.

    `status` and `assigned_to` are orthogonal on purpose: a ticket can be
    assigned and still new, or unassigned and already resolved.
    """

    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()

    doc_no = Column(String(40), index=True)
    subject = Column(String(400), nullable=False, index=True)
    description = Column(Text)

    party_id = Column(Integer, ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)
    category_id = Column(Integer, ForeignKey("ticket_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_to = _actor_fk()

    contact_name = Column(String(150))
    contact_phone = Column(String(40))
    contact_email = Column(String(150))

    channel = Column(String(20), default="whatsapp")   # phone|whatsapp|email|web|walk_in|internal
    priority = Column(String(20), default="medium", nullable=False, index=True)
    status = Column(String(30), default="new", nullable=False, index=True)
    # new | open | waiting_on_customer | on_hold | resolved | closed

    sla_policy_id = Column(Integer, ForeignKey("sla_policies.id", ondelete="SET NULL"), nullable=True)
    first_response_due_at = Column(DateTime)
    resolution_due_at = Column(DateTime, index=True)
    first_responded_at = Column(DateTime)
    resolved_at = Column(DateTime)
    closed_at = Column(DateTime)
    response_sla_breached = Column(Boolean, default=False, nullable=False)
    resolution_sla_breached = Column(Boolean, default=False, nullable=False)
    escalation_level = Column(Integer, default=0)
    reopened_count = Column(Integer, default=0)
    resolution = Column(Text)

    custom_fields = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    party = relationship("Party")
    category = relationship("TicketCategory")
    assignee = relationship("User", foreign_keys=[assigned_to])


# ────────────────────────────────────────────────────────────────────────────
# F4 · communication — the omnichannel inbox.
# conversation_messages is the ONLY external message store; tickets reference
# it rather than copying replies into their own table.
# ────────────────────────────────────────────────────────────────────────────

class CommChannel(Base):
    """A connected endpoint — a WhatsApp number, a mailbox, an SMS sender."""

    __tablename__ = "comm_channels"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_comm_channels_org_name"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    name = Column(String(150), nullable=False)
    channel_type = Column(String(30), default="whatsapp", nullable=False, index=True)
    provider = Column(String(80))
    # The address counterparties reach us on — a phone number or a mailbox.
    identifier = Column(String(200))
    status = Column(String(30), default="active", nullable=False)
    # Credentials are NOT stored here; this holds only non-secret settings.
    config = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()


class Conversation(Base):
    """One thread per counterparty per channel. The inbox row."""

    __tablename__ = "conversations"
    __table_args__ = (
        # The dedupe key: the same person on the same channel is one thread.
        UniqueConstraint("organisation_id", "channel_id", "contact_identifier",
                         name="uq_conversations_channel_contact"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    channel_id = Column(Integer, ForeignKey("comm_channels.id", ondelete="CASCADE"), nullable=False, index=True)

    contact_identifier = Column(String(200), nullable=False, index=True)
    contact_name = Column(String(200))
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)
    party_contact_id = Column(
        Integer, ForeignKey("party_contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )

    subject = Column(String(400))
    status = Column(String(20), default="open", nullable=False, index=True)  # open|pending|snoozed|closed
    assigned_to = _actor_fk()
    unread_count = Column(Integer, default=0, nullable=False)
    last_message_at = Column(DateTime, index=True)
    last_inbound_at = Column(DateTime)
    snoozed_until = Column(DateTime)
    closed_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    channel = relationship("CommChannel")
    party = relationship("Party")
    messages = relationship(
        "ConversationMessage", back_populates="conversation",
        cascade="all, delete-orphan", order_by="ConversationMessage.sent_at",
    )


class ConversationMessage(Base):
    """Append-only in/out stream. The only store of what a client actually said."""

    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    conversation_id = Column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # A message may be the origin of a ticket without the thread belonging to it —
    # a standing thread outlives any one ticket, so the link lives on the message.
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True, index=True)

    direction = Column(String(10), default="inbound", nullable=False, index=True)  # inbound | outbound
    message_type = Column(String(20), default="text")  # text|image|document|audio|template
    body = Column(Text)
    media_url = Column(String(600))

    # The provider's own id, so re-ingesting the same message is a no-op.
    external_id = Column(String(200), index=True)
    delivery_status = Column(String(30))
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    author_id = _actor_fk()

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")


# ────────────────────────────────────────────────────────────────────────────
# D5 · contracts — NEW, no registry equivalent (PRD §3.5 amendment).
# The signed-agreement vault and its billing schedule. The INVOICE itself lives
# in Zoho Books; a schedule row records only that it was billed and where.
# ────────────────────────────────────────────────────────────────────────────

class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("organisation_id", "doc_no", name="uq_contracts_org_doc"),)

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()

    doc_no = Column(String(40), index=True)
    title = Column(String(300), nullable=False, index=True)
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    contract_type = Column(String(30), default="sow")  # msa|sow|retainer|amc|nda

    value = Column(Numeric(14, 2))
    monthly_value = Column(Numeric(14, 2))
    currency = Column(String(8), default="INR")

    start_date = Column(Date)
    end_date = Column(Date)
    auto_renew = Column(Boolean, default=False, nullable=False)
    renewal_date = Column(Date, index=True)
    notice_days = Column(Integer)
    signed_on = Column(Date)
    signatory_name = Column(String(200))

    status = Column(String(30), default="draft", nullable=False, index=True)
    # draft|sent|signed|active|expired|terminated|renewed
    document_url = Column(String(600))
    notes = Column(Text)
    custom_fields = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    party = relationship("Party")
    project = relationship("Project")
    schedule = relationship(
        "ContractBillingSchedule", back_populates="contract",
        cascade="all, delete-orphan", order_by="ContractBillingSchedule.seq",
    )


class ContractBillingSchedule(Base):
    """When a contract becomes an invoice. HQ plans it; Zoho Books raises it."""

    __tablename__ = "contract_billing_schedule"
    __table_args__ = (
        UniqueConstraint("organisation_id", "contract_id", "seq", name="uq_billing_schedule_contract_seq"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()
    contract_id = Column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    milestone_id = Column(Integer, ForeignKey("milestones.id", ondelete="SET NULL"), nullable=True, index=True)

    seq = Column(Integer, default=1, nullable=False)
    name = Column(String(200), nullable=False)
    trigger_type = Column(String(20), default="date")  # date|milestone|manual
    due_date = Column(Date, index=True)
    amount = Column(Numeric(14, 2))
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending|invoiced|cancelled

    # Stamped once the invoice exists in Zoho Books.
    zoho_invoice_id = Column(String(60), index=True)
    zoho_invoice_number = Column(String(60))
    invoiced_on = Column(Date)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    contract = relationship("Contract", back_populates="schedule")


class ZohoInvoice(Base):
    """A read-only mirror of a Zoho Books invoice.

    HQ never creates, edits or deletes one of these through its own UI — the row
    exists so a customer page can show what is owed without a round trip, and so
    "billable but unbilled" is answerable. Zoho Books remains the only place an
    invoice is actually raised or changed.
    """

    __tablename__ = "zoho_invoices"
    __table_args__ = (
        UniqueConstraint("organisation_id", "zoho_invoice_id", name="uq_zoho_invoices_org_invoice"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()

    zoho_invoice_id = Column(String(60), nullable=False, index=True)
    invoice_number = Column(String(60), index=True)
    zoho_contact_id = Column(String(60), index=True)
    customer_name = Column(String(200))
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)

    invoice_date = Column(Date, index=True)
    due_date = Column(Date, index=True)
    status = Column(String(30), index=True)   # draft|sent|paid|overdue|partially_paid|void
    total = Column(Numeric(14, 2))
    balance_due = Column(Numeric(14, 2))
    currency = Column(String(8), default="INR")

    synced_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    party = relationship("Party")
