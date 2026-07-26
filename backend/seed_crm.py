"""Idempotent CRM seeding — config, team, and the real book of work.

Everything here is keyed on a natural unique value (name, code, email) and
re-checked before insert, so a restart never duplicates a row. Nothing is
invented: customers, services and projects come from the live delivery board,
and any field that board does not carry is left NULL rather than guessed.
"""

import logging
import os
import secrets
from datetime import date, datetime

from backend.crm_models import (
    CommChannel, Item, ItemCategory, LeadSource, LostReason, Party, PartyGroup,
    Pipeline, PipelineStage, Project, SlaPolicy, TicketCategory, WorkStream,
    WorkStreamMember,
)
from backend.models import Organisation, Product, Role, User, Workspace

logger = logging.getLogger("seed_crm")

# Passwords generated on first seed are printed once to the server log and
# never stored in the repo. Set these env vars to choose them explicitly.
TEAM = [
    {
        "email": "nishant@neonir.com", "name": "Nishant Kapadia", "role": "Partner",
        "env": "SEED_NISHANT_PASSWORD", "initials": "NK",
    },
    {
        "email": "hemish@neonir.com", "name": "Hemish Kapadia", "role": "Advisor",
        "env": "SEED_HEMISH_PASSWORD", "initials": "HK",
    },
]

PARTY_GROUPS = [
    ("Water Treatment", "#A2D2FF"),
    ("Electric Assembly", "#FFCDB2"),
    ("Transformers", "#C8B6FF"),
    ("Speciality Oils", "#B8E0D2"),
    ("Professional Services", "#FFB5C2"),
]

LEAD_SOURCES = ["Referral", "Inbound", "Outbound", "Partner", "Existing customer", "Event"]

LOST_REASONS = ["Budget", "Timing", "Went with competitor", "No decision", "Out of scope"]

# One pipeline; the stage list is the real pre-sale ladder, distinct from the
# delivery ladder that lives on a project.
PIPELINE_STAGES = [
    ("New", 10, False, False, "#A2D2FF"),
    ("Qualified", 25, False, False, "#B8E0D2"),
    ("Demo done", 45, False, False, "#FFCDB2"),
    ("Proposal sent", 65, False, False, "#C8B6FF"),
    ("Negotiation", 80, False, False, "#FFB5C2"),
    ("Won", 100, True, False, "#B8E0D2"),
    ("Lost", 0, False, True, "#FF9F9F"),
]

ITEM_CATEGORIES = [
    ("Platform products", "service"),
    ("Custom software", "service"),
    ("AI & automation", "service"),
    ("Websites", "service"),
]

# The services ZeroOne actually sells, derived from the delivery board.
SERVICES = [
    ("AquaServe", "aquaserve", "Platform products", "Water-treatment operations platform."),
    ("TravelDesk", "traveldesk", "Platform products", "Business-travel request and visit tracker."),
    ("SupportDesk", "supportdesk", "Platform products", "Client request and ticket tracker."),
    ("RepairDesk", "repairdesk", "Platform products", "Transformer-repair workshop tracker."),
    ("Community Software", "community-software", "Custom software", "Community and club management software."),
    ("Electrical Software", "electrical-software", "Custom software", "Electrical assembly and panel software."),
    ("AI Leads Bot", "ai-leads-bot", "AI & automation", "Lead generation, profiling and outreach engine."),
    ("Website", "website", "Websites", "Brand website design and build."),
]

# Customers, with the group they belong to. Sourced from the delivery board and
# the client list; a customer with no known GSTIN is left blank, not filled in.
CUSTOMERS = [
    ("NeoNir Engineering", "Water Treatment", "NE"),
    ("Pioneer Engineering", "Water Treatment", "PE"),
    ("Aditya Electric", "Electric Assembly", "AE"),
    ("Krishna Global Transenergy", "Transformers", "KG"),
    ("Active Co", "Professional Services", "AC"),
    ("Arihant Bhai", "Electric Assembly", "AB"),
    ("Vishwa Bhai Supreme Aqua", "Water Treatment", "VS"),
    ("Michael Bhai", "Water Treatment", "MB"),
    ("Pushpendra Bhai", "Water Treatment", "PB"),
    ("FeedAqua", "Water Treatment", "FA"),
    ("Water Whizz", "Water Treatment", "WW"),
    ("Om Enterprises", "Water Treatment", "OE"),
    ("Sustro Oils", "Speciality Oils", "SO"),
    ("Micro Chem", "Water Treatment", "MC"),
    ("Parag Kaka", "Professional Services", "PK"),
]

# The live delivery board, transcribed exactly.
# (ref, name, customer, service, stage, next_action, next_action_date, owner_email, prod_url)
# Money is deliberately absent: the board's per-row One-Time / Monthly values
# were not readable, and a fabricated figure in an accounting-adjacent system is
# worse than a blank one. Fill them in-app.
PROJECTS = [
    ("HQ-P22", "Active Co — Community Software", "Active Co", "Community Software",
     "In progress", "HB to send invoice", date(2026, 7, 25), "hemish@neonir.com", None),
    ("HQ-P21", "Arihant Bhai — Electrical Software", "Arihant Bhai", "Electrical Software",
     "Not started", "NK to send followup on contract", date(2026, 7, 27), "nishant@neonir.com", None),
    ("HQ-P18", "Vishwa Bhai Supreme Aqua — AquaServe", "Vishwa Bhai Supreme Aqua", "AquaServe",
     "Not started", "MD to setup environment", date(2026, 7, 27), "meet@dotsai.in", None),
    ("HQ-P15", "Michael Bhai — AquaServe", "Michael Bhai", "AquaServe",
     "Training Completed", "MD to check onboarding status", date(2026, 7, 27), "meet@dotsai.in", None),
    ("HQ-P14", "Pushpendra Bhai — AquaServe", "Pushpendra Bhai", "AquaServe",
     "Training Completed", "Check email reply", date(2026, 7, 27), "nishant@neonir.com", None),
    ("HQ-P12", "FeedAqua — Website", "FeedAqua", "Website",
     "In progress", "MD to finalise website", date(2026, 8, 8), "meet@dotsai.in", None),
    ("HQ-P11", "RepairDesk", None, "RepairDesk",
     "In progress", "MD to meet in-person", date(2026, 7, 27), "meet@dotsai.in", None),
    ("HQ-P10", "Pioneer Engineering — TravelDesk", "Pioneer Engineering", "TravelDesk",
     "Onboarding Completed", "NK to check usage status", date(2026, 8, 15), "nishant@neonir.com",
     "https://traveldesk.dotsai.cloud/login"),
    ("HQ-P09", "Water Whizz — AquaServe", "Water Whizz", "AquaServe",
     "Onboarding Completed", "MD to make 1 change (deploy this feature to NeoSERV and other platforms also)",
     date(2026, 7, 27), "meet@dotsai.in", "https://waterwhizz.aquaserve.dotsai.in/login"),
    ("HQ-P08", "Om Enterprises — AquaServe", "Om Enterprises", "AquaServe",
     "Onboarding Completed", "MD to assist till full adoption", date(2026, 8, 8), "meet@dotsai.in", None),
    ("HQ-P07", "Sustro Oils — AI Leads Bot", "Sustro Oils", "AI Leads Bot",
     "In progress", "NK to explore Vanira Platform", date(2026, 7, 27), "meet@dotsai.in", None),
    ("HQ-P06", "Pioneer Engineering — AquaServe", "Pioneer Engineering", "AquaServe",
     "In progress", "Send follow-up on whatsapp for Dubai dealer", date(2026, 8, 8), "nishant@neonir.com", None),
    ("HQ-P05", "Micro Chem — AquaServe", "Micro Chem", "AquaServe",
     "Onboarding Completed", "MD to assist till full adoption", date(2026, 8, 8), "meet@dotsai.in", None),
    ("HQ-P04", "FeedAqua — AquaServe", "FeedAqua", "AquaServe",
     "Project Completed", "MD to assist till full adoption", date(2026, 8, 8), "meet@dotsai.in", None),
    ("HQ-P03", "Parag Kaka — SupportDesk", "Parag Kaka", "SupportDesk",
     "Testing", "NK to test", date(2026, 7, 27), "meet@dotsai.in",
     "https://supportdesk.dotsai.cloud/login"),
]

# ── Zoho Books linkage ──────────────────────────────────────────────────────
# Zoho Books (org 60078183686) is the system of record for money. These are the
# real contacts and receivables read from it on 2026-07-26. HQ mirrors the
# figure for display; it never writes an invoice.
#
# Only names that match unambiguously are linked. Two Zoho contacts look like
# HQ customers under a different name — GOA TRADING & TECHNICAL SERVICES
# (michael.martins@) vs "Michael Bhai", and KAJAL PARAG TELI (parag_teli@) vs
# "Parag Kaka" — but that is an inference from a first name, and attaching the
# wrong receivable to the wrong customer is a money error. They stay unlinked
# until Meet confirms. See ZOHO_LIKELY_MATCHES below.
# (hq_display_name, zoho_contact_name, email, phone, place_of_supply, receivable)
ZOHO_LINKS = [
    ("NeoNir Engineering", "NEO NIR ENGINEERING LLP", "hemish@neonir.com", "+91-9825115308", "Gujarat", 354000),
    ("Pioneer Engineering", "PIONEER ENGINEERING", "subodh.gurjar@dorfketal.com", None, "Maharashtra", 0),
    ("FeedAqua", "Feed Aqua Engineering Private Limited", "ajaysingh@feedaqua.com", None, "Uttar Pradesh", 47200),
    ("Micro Chem", "Microchem Enterprises", None, None, "Tamil Nadu", 0),
    ("Om Enterprises", "OM Enterprises", "ajay.kasture@omenterprises.co.in", None, "Maharashtra", 41300),
    ("Water Whizz", "Water Whizz", None, None, "Gujarat", 0),
]

# Zoho contacts with no HQ customer at all — created so the books and the CRM
# agree on who exists.
ZOHO_ONLY_CUSTOMERS = [
    ("S P Chemicals", "Professional Services", "SP", "sales@spchemicals.net", "+91-9850000966", "Maharashtra", 41300),
    ("Bellway Consulting", "Professional Services", "BC", "sales@bellwayconsulting.com", None, "Uttar Pradesh", 47200),
]

# Recorded, not applied. Surfaced to Meet to confirm or reject.
ZOHO_LIKELY_MATCHES = [
    ("Michael Bhai", "GOA TRADING & TECHNICAL SERVICES", "michael.martins@gtandts.com", "Goa", 0),
    ("Parag Kaka", "KAJAL PARAG TELI", "parag_teli@yahoo.com", "Gujarat", 11800),
]

# Ticket categories — labelled "Job types" in the UI. Drawn from the kinds of
# request the live platforms actually generate.
JOB_TYPES = [
    ("Bug", "Something is broken and needs fixing.", "high"),
    ("Change request", "A behaviour or field change to an existing feature.", "medium"),
    ("New feature", "Something that does not exist yet.", "medium"),
    ("Onboarding", "Setup, data import or environment work for a new account.", "high"),
    ("Training", "Walkthroughs and how-to help for a client's team.", "medium"),
    ("Data fix", "Correcting records on a client's behalf.", "high"),
    ("Deployment", "Release, environment or infrastructure work.", "high"),
    ("Question", "A query that needs an answer, not a change.", "low"),
]

# Response and resolution promises, in hours, per priority.
SLA_POLICIES = [
    ("Standard", "Default promise for client requests.", True, {
        "urgent": {"response_hours": 2, "resolution_hours": 8},
        "high": {"response_hours": 4, "resolution_hours": 24},
        "medium": {"response_hours": 8, "resolution_hours": 72},
        "low": {"response_hours": 24, "resolution_hours": 168},
    }),
]

# The channels ZeroOne actually receives client messages on.
COMM_CHANNELS = [
    ("WhatsApp Business", "whatsapp", "918320065658", "Baileys bot (wa.dotsai.cloud)"),
    ("Email", "email", "meet@dotsai.in", "Google Workspace"),
]

# Standing work streams — the 00-Brain "Work" join, keyed by who is in them.
WORK_STREAMS = [
    ("Meet x Nishant", "Standing partner stream — decisions, delivery and follow-ups.",
     ["meet@dotsai.in", "nishant@neonir.com"]),
    ("Meet x Hemish", "Advisory stream — commercials, invoicing and guidance.",
     ["meet@dotsai.in", "hemish@neonir.com"]),
]

# Stage COMPLETED means delivery is finished; the project stays active for
# support unless it is explicitly closed.
_COMPLETED_STAGES = {"Project Completed"}


def _get_or_create(db, model, defaults=None, **lookup):
    """Fetch by the natural key, else create. Returns (obj, created)."""
    obj = db.query(model).filter_by(**lookup).first()
    if obj:
        return obj, False
    obj = model(**dict(lookup, **(defaults or {})))
    db.add(obj)
    db.flush()
    return obj, True


def seed(db, org: Organisation, admin: User, get_password_hash):
    """Seed CRM config, the team, and the real book of work. Safe to re-run."""
    created_passwords = {}
    org_id = org.id

    # ── workspaces ──────────────────────────────────────────────────────────
    # The sidebar's tab tree is defined in the frontend, but the workspace
    # switcher reads these rows, so the two must agree.
    product = db.query(Product).filter(Product.code == "hq").first()
    for name, slug, icon, description in [
        ("CRM", "crm", "users", "Customers, leads, catalog and delivery projects"),
        ("Work", "work", "work", "Tasks and standing work streams"),
        ("Tickets", "tickets", "bell", "Client requests, job types and SLAs"),
        ("Comms", "comms", "chat", "Client conversations across WhatsApp and email"),
        ("Accounting", "accounting", "billing", "Contracts, billing schedule and the Zoho Books mirror"),
    ]:
        _get_or_create(
            db, Workspace,
            {"slug": slug, "icon": icon, "description": description,
             "product_id": product.id if product else None, "status": "Active"},
            organisation_id=org_id, name=name,
        )
    db.flush()

    # Roles and their grants are owned by backend/permissions.py, which runs
    # before this. We only assign people to them here.

    # ── team ────────────────────────────────────────────────────────────────
    for spec in TEAM:
        existing = db.query(User).filter(User.email == spec["email"]).first()
        if existing:
            continue
        role = db.query(Role).filter(Role.organisation_id == org_id, Role.name == spec["role"]).first()
        password = os.getenv(spec["env"]) or secrets.token_urlsafe(12)
        db.add(User(
            email=spec["email"], name=spec["name"],
            password_hash=get_password_hash(password),
            role_id=role.id if role else None,
            organisation_id=org_id, status="Active",
        ))
        created_passwords[spec["email"]] = password if not os.getenv(spec["env"]) else "(from %s)" % spec["env"]
    db.flush()

    users = {u.email: u for u in db.query(User).filter(User.organisation_id == org_id).all()}

    # ── config ──────────────────────────────────────────────────────────────
    for name, color in PARTY_GROUPS:
        _get_or_create(db, PartyGroup, {"color": color, "created_by_id": admin.id},
                       organisation_id=org_id, name=name)

    for name in LEAD_SOURCES:
        _get_or_create(db, LeadSource, {"created_by_id": admin.id}, organisation_id=org_id, name=name)

    for name in LOST_REASONS:
        _get_or_create(db, LostReason, {"created_by_id": admin.id}, organisation_id=org_id, name=name)

    pipeline, _ = _get_or_create(
        db, Pipeline, {"is_default": True, "description": "Z9S AI sales pipeline", "created_by_id": admin.id},
        organisation_id=org_id, name="Sales",
    )
    for i, (name, prob, won, lost, color) in enumerate(PIPELINE_STAGES):
        _get_or_create(
            db, PipelineStage,
            {"sort_order": i, "probability": prob, "is_won": won, "is_lost": lost,
             "color": color, "created_by_id": admin.id},
            organisation_id=org_id, pipeline_id=pipeline.id, name=name,
        )

    for name, kind in ITEM_CATEGORIES:
        _get_or_create(db, ItemCategory, {"kind": kind, "created_by_id": admin.id},
                       organisation_id=org_id, name=name)
    db.flush()

    categories = {c.name: c for c in db.query(ItemCategory).filter(ItemCategory.organisation_id == org_id).all()}
    groups = {g.name: g for g in db.query(PartyGroup).filter(PartyGroup.organisation_id == org_id).all()}

    # ── catalog ─────────────────────────────────────────────────────────────
    for name, code, category, description in SERVICES:
        cat = categories.get(category)
        _get_or_create(
            db, Item,
            {"name": name, "item_type": "service", "category_id": cat.id if cat else None,
             "description": description, "is_active": True, "created_by_id": admin.id},
            organisation_id=org_id, code=code,
        )
    db.flush()
    items = {i.name: i for i in db.query(Item).filter(Item.organisation_id == org_id).all()}

    # ── customers ───────────────────────────────────────────────────────────
    for name, group, initials in CUSTOMERS:
        grp = groups.get(group)
        _get_or_create(
            db, Party,
            {"kind": "customer", "initials": initials, "party_group_id": grp.id if grp else None,
             "industry": group, "owner_id": admin.id, "status": "Active",
             "created_by_id": admin.id, "updated_by_id": admin.id},
            organisation_id=org_id, display_name=name,
        )
    for name, group, initials, email, phone, state, receivable in ZOHO_ONLY_CUSTOMERS:
        grp = groups.get(group)
        _get_or_create(
            db, Party,
            {"kind": "customer", "initials": initials, "party_group_id": grp.id if grp else None,
             "email": email, "phone": phone, "owner_id": admin.id, "status": "Active",
             "zoho_contact_name": name.upper(), "outstanding_amount": receivable,
             "outstanding_synced_at": datetime.utcnow(),
             "created_by_id": admin.id, "updated_by_id": admin.id},
            organisation_id=org_id, display_name=name,
        )
    db.flush()
    parties = {p.display_name: p for p in db.query(Party).filter(Party.organisation_id == org_id).all()}

    # ── Zoho Books figures ──────────────────────────────────────────────────
    # Only fills blanks — never overwrites a value Meet has edited by hand.
    for hq_name, zoho_name, email, phone, state, receivable in ZOHO_LINKS:
        party = parties.get(hq_name)
        if not party:
            continue
        if not party.zoho_contact_name:
            party.zoho_contact_name = zoho_name
            party.outstanding_amount = receivable
            party.outstanding_synced_at = datetime.utcnow()
        if email and not party.email:
            party.email = email
        if phone and not party.phone:
            party.phone = phone
    db.flush()

    # ── projects ────────────────────────────────────────────────────────────
    for ref, name, customer, service, stage, action, action_date, owner_email, prod_url in PROJECTS:
        owner = users.get(owner_email) or admin
        party = parties.get(customer) if customer else None
        item = items.get(service)
        _get_or_create(
            db, Project,
            {
                "name": name,
                "party_id": party.id if party else None,
                "item_id": item.id if item else None,
                "manager_id": owner.id,
                "stage": stage,
                "status": "completed" if stage in _COMPLETED_STAGES else "active",
                "next_action": action,
                "next_action_date": action_date,
                "next_action_owner_id": owner.id,
                "prod_url": prod_url,
                "created_by_id": admin.id,
                "updated_by_id": admin.id,
            },
            organisation_id=org_id, doc_no=ref,
        )
    db.flush()

    # ── helpdesk config ─────────────────────────────────────────────────────
    for i, (name, description, priority) in enumerate(JOB_TYPES):
        _get_or_create(
            db, TicketCategory,
            {"description": description, "default_priority": priority,
             "sort_order": i, "is_active": True, "created_by_id": admin.id},
            organisation_id=org_id, name=name,
        )

    for name, description, business_hours, targets in SLA_POLICIES:
        _get_or_create(
            db, SlaPolicy,
            {"description": description, "use_business_hours": business_hours,
             "targets": targets, "is_default": True, "created_by_id": admin.id},
            organisation_id=org_id, name=name,
        )

    # ── comms channels ──────────────────────────────────────────────────────
    for name, kind, identifier, provider in COMM_CHANNELS:
        _get_or_create(
            db, CommChannel,
            {"channel_type": kind, "identifier": identifier, "provider": provider,
             "status": "active", "created_by_id": admin.id},
            organisation_id=org_id, name=name,
        )
    db.flush()

    # ── work streams ────────────────────────────────────────────────────────
    for name, description, member_emails in WORK_STREAMS:
        stream, created = _get_or_create(
            db, WorkStream,
            {"description": description, "status": "active", "created_by_id": admin.id,
             "updated_by_id": admin.id},
            organisation_id=org_id, name=name,
        )
        if created:
            for email in member_emails:
                user = users.get(email)
                if user:
                    db.add(WorkStreamMember(
                        organisation_id=org_id, work_stream_id=stream.id,
                        user_id=user.id, created_by_id=admin.id,
                    ))

    db.commit()

    if created_passwords:
        for email, password in created_passwords.items():
            logger.warning("SEEDED USER %s — initial password: %s (change on first login)", email, password)
    return created_passwords
