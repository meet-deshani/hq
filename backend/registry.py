"""The entity registry — one declarative description of every CRM entity.

This is the contract the whole platform renders from:

* ``backend/crud.py``      generates REST CRUD for every entry
* ``GET /api/meta/entities`` publishes it, so agents can discover the surface
* ``frontend/static/PortalPage.dc.html`` builds lists, forms and detail pages
* ``cli/hq-cli.py``        builds its commands

Adding an entity means adding one entry below. No router, no CLI command and no
frontend code. That is the property that keeps the API, the UI and the CLI from
drifting apart, and it is what makes the platform usable by an agent that has
only ever read ``/api/meta/entities``.

Field types understood by every consumer:
    text · textarea · email · phone · url · number · money · percent
    date · datetime · select · boolean · ref

``ref`` fields carry ``ref`` (the registry key they point at) so a consumer can
resolve the label without knowing the schema.
"""

from backend import crm_models as m
from backend.models import User

# ── shared option sets ──────────────────────────────────────────────────────

PARTY_KINDS = ["customer", "prospect", "vendor", "both"]
GST_TREATMENTS = ["regular", "composition", "unregistered", "consumer", "overseas", "sez"]
TASK_STATUSES = ["open", "in_progress", "blocked", "done", "cancelled"]
PRIORITIES = ["low", "medium", "high", "urgent"]

# The delivery ladder actually in use on the live board — not a generic
# project status. Changing this list changes the Projects board columns.
PROJECT_STAGES = [
    "Not started",
    "In progress",
    "Testing",
    "Training Completed",
    "Onboarding Completed",
    "Project Completed",
    "On hold",
]

ENTITIES = []
# Maintained incrementally by entity() rather than built once part-way down the
# file: entities declared AFTER the lookup was constructed were invisible to it,
# which made every ref and relation pointing at them fail validation.
BY_KEY = {}
BY_ENTITY_TYPE = {}


def entity(**kw):
    ENTITIES.append(kw)
    BY_KEY[kw["key"]] = kw
    BY_ENTITY_TYPE.setdefault(kw["entity_type"], kw)
    return kw


# ────────────────────────────────────────────────────────────────────────────
# CRM · Customers and people
# ────────────────────────────────────────────────────────────────────────────

entity(
    key="customers",
    entity_type="parties",
    model=m.Party,
    label="Customer",
    plural="Customers",
    workspace="CRM",
    module="Customers",
    icon="users",
    accent="#A2D2FF",
    order_by="display_name",
    search=["display_name", "legal_name", "gstin", "email", "phone", "city"],
    title_field="display_name",
    # Archetype 1B — a dense ledger. Widths are grid-template fractions.
    columns=[
        {"k": "display_name", "label": "Name", "type": "text", "width": "2.2fr", "primary": True},
        {"k": "kind", "label": "Kind", "type": "badge", "width": "0.8fr"},
        {"k": "gstin", "label": "GSTIN", "type": "mono", "width": "1.4fr"},
        {"k": "gst_treatment", "label": "Treatment", "type": "text", "width": "1fr"},
        {"k": "owner_id", "label": "Z9S POC", "type": "ref", "ref": "users", "width": "1.2fr"},
        {"k": "party_group_id", "label": "Group", "type": "ref", "ref": "party-groups", "width": "1.1fr"},
        {"k": "outstanding_amount", "label": "Outstanding", "type": "money", "width": "1.2fr", "align": "right"},
        {"k": "status", "label": "Status", "type": "badge", "width": "0.9fr"},
    ],
    fields=[
        {"k": "display_name", "label": "Display name", "type": "text", "required": True, "group": "Identity"},
        {"k": "legal_name", "label": "Legal name", "type": "text", "group": "Identity"},
        {"k": "kind", "label": "Kind", "type": "select", "options": PARTY_KINDS, "default": "customer", "group": "Identity"},
        {"k": "party_group_id", "label": "Group", "type": "ref", "ref": "party-groups", "group": "Identity"},
        {"k": "owner_id", "label": "Z9S POC", "type": "ref", "ref": "users", "group": "Identity",
         "help": "Who at Z9S owns this account."},
        {"k": "industry", "label": "Industry", "type": "text", "group": "Identity"},

        {"k": "gstin", "label": "GSTIN", "type": "text", "group": "Tax"},
        {"k": "gst_treatment", "label": "GST treatment", "type": "select", "options": GST_TREATMENTS,
         "default": "regular", "group": "Tax"},
        {"k": "pan", "label": "PAN", "type": "text", "group": "Tax"},

        {"k": "phone", "label": "Phone", "type": "phone", "group": "Contact"},
        {"k": "email", "label": "Email", "type": "email", "group": "Contact"},
        {"k": "website", "label": "Website", "type": "url", "group": "Contact"},

        {"k": "billing_address", "label": "Billing address", "type": "textarea", "group": "Address"},
        {"k": "city", "label": "City", "type": "text", "group": "Address"},
        {"k": "state_code", "label": "State code", "type": "text", "group": "Address"},
        {"k": "pincode", "label": "PIN code", "type": "text", "group": "Address"},

        {"k": "credit_limit", "label": "Credit limit", "type": "money", "group": "Commercials"},
        {"k": "credit_days", "label": "Credit days", "type": "number", "group": "Commercials"},

        {"k": "zoho_contact_id", "label": "Zoho Books contact id", "type": "text", "group": "Zoho Books",
         "help": "Links this customer to its Zoho Books contact. Names differ between "
                 "the two systems, so the id is the only safe join."},
        {"k": "zoho_contact_name", "label": "Name in Zoho Books", "type": "text", "group": "Zoho Books"},
        {"k": "outstanding_amount", "label": "Outstanding", "type": "money", "group": "Zoho Books",
         "help": "Mirrored from Zoho Books, which owns the invoices. Editable here only "
                 "until the sync is connected."},

        {"k": "summary", "label": "Summary", "type": "textarea", "group": "Notes",
         "help": "The living one-paragraph answer to 'who are they'. Updated over time."},
        {"k": "notes", "label": "Notes", "type": "textarea", "group": "Notes"},
        {"k": "status", "label": "Status", "type": "select", "options": ["Active", "Dormant", "Archived"],
         "default": "Active", "group": "Notes"},
    ],
    # Archetype 1E — key facts pin to the right rail, sections stack left.
    key_facts=["owner_id", "outstanding_amount", "party_group_id", "credit_limit", "credit_days", "industry"],
    relations=[
        {"key": "contacts", "label": "Contacts", "entity": "contacts", "fk": "party_id"},
        {"key": "leads", "label": "Leads", "entity": "leads", "fk": "party_id"},
        {"key": "projects", "label": "Projects", "entity": "projects", "fk": "party_id"},
        {"key": "tasks", "label": "Tasks", "entity": "tasks", "fk": "party_id"},
        {"key": "work_streams", "label": "Work streams", "entity": "work-streams", "fk": "party_id"},
    ],
    saved_views=[
        {"name": "All", "filters": {}},
        {"name": "Customers", "filters": {"kind": "customer"}},
        {"name": "Prospects", "filters": {"kind": "prospect"}},
        {"name": "Vendors", "filters": {"kind": "vendor"}},
        {"name": "Active", "filters": {"status": "Active"}},
    ],
)

entity(
    key="contacts",
    entity_type="party_contacts",
    model=m.PartyContact,
    label="Person",
    plural="People",
    workspace="CRM",
    module="Customers",
    icon="users",
    accent="#A2D2FF",
    order_by="name",
    search=["name", "email", "phone", "whatsapp", "designation"],
    title_field="name",
    columns=[
        {"k": "name", "label": "Name", "type": "text", "width": "1.8fr", "primary": True},
        {"k": "party_id", "label": "Company", "type": "ref", "ref": "customers", "width": "1.8fr"},
        {"k": "designation", "label": "Designation", "type": "text", "width": "1.3fr"},
        {"k": "phone", "label": "Phone", "type": "mono", "width": "1.2fr"},
        {"k": "email", "label": "Email", "type": "text", "width": "1.6fr"},
        {"k": "is_primary", "label": "Primary", "type": "boolean", "width": "0.7fr"},
    ],
    fields=[
        {"k": "name", "label": "Name", "type": "text", "required": True, "group": "Identity"},
        {"k": "party_id", "label": "Company", "type": "ref", "ref": "customers", "group": "Identity",
         "help": "Leave empty for a person who belongs to no company."},
        {"k": "designation", "label": "Designation", "type": "text", "group": "Identity"},
        {"k": "is_primary", "label": "Primary contact", "type": "boolean", "group": "Identity"},
        {"k": "phone", "label": "Phone", "type": "phone", "group": "Contact"},
        {"k": "whatsapp", "label": "WhatsApp", "type": "phone", "group": "Contact"},
        {"k": "email", "label": "Email", "type": "email", "group": "Contact"},
        {"k": "comms_preference", "label": "Comms preference", "type": "text", "group": "Contact"},
        {"k": "summary", "label": "Summary", "type": "textarea", "group": "Notes"},
        {"k": "relevance", "label": "Relevance", "type": "textarea", "group": "Notes",
         "help": "Why this person matters to us."},
        {"k": "notes", "label": "Notes", "type": "textarea", "group": "Notes"},
        {"k": "status", "label": "Status", "type": "select", "options": ["Active", "Archived"],
         "default": "Active", "group": "Notes"},
    ],
    key_facts=["party_id", "designation", "phone", "whatsapp", "email"],
    relations=[
        {"key": "tasks", "label": "Tasks", "entity": "tasks", "fk": "party_contact_id", "via": "task_participants"},
    ],
    saved_views=[
        {"name": "All", "filters": {}},
        {"name": "Primary contacts", "filters": {"is_primary": True}},
        {"name": "Unattached", "filters": {"party_id": None}},
    ],
)

entity(
    key="party-groups",
    entity_type="party_groups",
    model=m.PartyGroup,
    label="Customer group",
    plural="Customer groups",
    workspace="Config",
    module="CRM setup",
    icon="sliders",
    accent="#A2D2FF",
    order_by="name",
    search=["name"],
    title_field="name",
    columns=[
        {"k": "name", "label": "Name", "type": "text", "width": "2fr", "primary": True},
        {"k": "description", "label": "Description", "type": "text", "width": "3fr"},
        {"k": "color", "label": "Colour", "type": "color", "width": "1fr"},
    ],
    fields=[
        {"k": "name", "label": "Name", "type": "text", "required": True},
        {"k": "description", "label": "Description", "type": "text"},
        {"k": "color", "label": "Colour", "type": "text", "default": "#C8B6FF"},
    ],
)


# ────────────────────────────────────────────────────────────────────────────
# CRM · Leads and the pipeline
# ────────────────────────────────────────────────────────────────────────────

entity(
    key="leads",
    entity_type="leads",
    model=m.Lead,
    label="Lead",
    plural="Leads",
    workspace="CRM",
    module="Leads",
    icon="trend",
    accent="#FFCDB2",
    order_by="-created_at",
    search=["title", "company_name", "contact_name", "email", "phone"],
    title_field="title",
    columns=[
        {"k": "title", "label": "Lead", "type": "text", "width": "2.2fr", "primary": True},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "width": "1.6fr"},
        {"k": "stage_id", "label": "Stage", "type": "ref", "ref": "pipeline-stages", "width": "1.2fr"},
        {"k": "estimated_value", "label": "One-time", "type": "money", "width": "1.1fr", "align": "right"},
        {"k": "monthly_value", "label": "Monthly", "type": "money", "width": "1fr", "align": "right"},
        {"k": "owner_id", "label": "Owner", "type": "ref", "ref": "users", "width": "1.1fr"},
        {"k": "next_action_date", "label": "Next action", "type": "date", "width": "1.1fr"},
        {"k": "status", "label": "Status", "type": "badge", "width": "0.9fr"},
    ],
    fields=[
        {"k": "title", "label": "Lead title", "type": "text", "required": True, "group": "Lead"},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "group": "Lead",
         "hint": "Set this when the lead is for a company already in the book — a "
                 "second project for an existing customer is still a lead. Leave "
                 "empty for a company we do not know yet; winning it creates one."},
        {"k": "company_name", "label": "Company", "type": "text", "group": "Lead",
         "hint": "Only used when no customer is linked above."},
        {"k": "item_id", "label": "Service", "type": "ref", "ref": "catalog-products", "group": "Lead",
         "hint": "What this lead is for. Carried into the project when it is won."},
        {"k": "source_id", "label": "Source", "type": "ref", "ref": "lead-sources", "group": "Lead"},
        {"k": "pipeline_id", "label": "Pipeline", "type": "ref", "ref": "pipelines", "group": "Lead"},
        {"k": "stage_id", "label": "Stage", "type": "ref", "ref": "pipeline-stages", "group": "Lead"},
        {"k": "owner_id", "label": "Owner", "type": "ref", "ref": "users", "group": "Lead"},

        {"k": "contact_name", "label": "Contact name", "type": "text", "group": "Contact"},
        {"k": "phone", "label": "Phone", "type": "phone", "group": "Contact"},
        {"k": "email", "label": "Email", "type": "email", "group": "Contact"},

        {"k": "estimated_value", "label": "One-time value", "type": "money", "group": "Commercials"},
        {"k": "monthly_value", "label": "Monthly value", "type": "money", "group": "Commercials"},
        {"k": "expected_close_date", "label": "Expected close", "type": "date", "group": "Commercials"},

        {"k": "next_action", "label": "Next action", "type": "text", "group": "Next move"},
        {"k": "next_action_date", "label": "Next action date", "type": "date", "group": "Next move"},
        {"k": "next_action_owner_id", "label": "Next action owner", "type": "ref", "ref": "users", "group": "Next move"},

        {"k": "status", "label": "Status", "type": "select", "options": ["open", "won", "lost"],
         "default": "open", "group": "Outcome",
         "hint": "Setting this to won converts the customer, opens the project and "
                 "moves this lead's tasks onto it."},
        {"k": "lost_reason_id", "label": "Lost reason", "type": "ref", "ref": "lost-reasons", "group": "Outcome"},
        # Left editable on purpose: pointing a lead at a project that already
        # exists is exactly how an existing customer's second piece of work gets
        # attached to the delivery it belongs to.
        {"k": "converted_project_id", "label": "Project", "type": "ref", "ref": "projects",
         "group": "Outcome",
         "hint": "Opened automatically when this lead is won. Point it at an "
                 "existing project to attach the lead to work already running."},
        {"k": "notes", "label": "Notes", "type": "textarea", "group": "Outcome"},
    ],
    key_facts=["party_id", "stage_id", "owner_id", "estimated_value", "monthly_value",
               "expected_close_date", "source_id"],
    relations=[
        {"key": "tasks", "label": "Tasks", "entity": "tasks", "fk": "lead_id"},
    ],
    saved_views=[
        {"name": "Open", "filters": {"status": "open"}},
        {"name": "All", "filters": {}},
        {"name": "Won", "filters": {"status": "won"}},
        {"name": "Lost", "filters": {"status": "lost"}},
    ],
    actions=[
        {"key": "convert", "label": "Convert to customer", "method": "POST",
         "path": "/api/leads/{lead_id}/convert",
         "description": "Creates a parties row from the lead, stamps converted_party_id, "
                        "marks the lead won. The lead is kept — the funnel history is the point."},
    ],
)

entity(
    key="lead-sources", entity_type="lead_sources", model=m.LeadSource,
    label="Lead source", plural="Lead sources", workspace="Config", module="CRM setup",
    icon="sliders", accent="#FFCDB2", order_by="name", search=["name"], title_field="name",
    columns=[
        {"k": "name", "label": "Name", "type": "text", "width": "2fr", "primary": True},
        {"k": "description", "label": "Description", "type": "text", "width": "3fr"},
        {"k": "is_active", "label": "Active", "type": "boolean", "width": "0.8fr"},
    ],
    fields=[
        {"k": "name", "label": "Name", "type": "text", "required": True},
        {"k": "description", "label": "Description", "type": "text"},
        {"k": "is_active", "label": "Active", "type": "boolean", "default": True},
    ],
)

entity(
    key="pipelines", entity_type="pipelines", model=m.Pipeline,
    label="Pipeline", plural="Pipelines", workspace="Config", module="CRM setup",
    icon="sliders", accent="#FFCDB2", order_by="name", search=["name"], title_field="name",
    columns=[
        {"k": "name", "label": "Name", "type": "text", "width": "2fr", "primary": True},
        {"k": "description", "label": "Description", "type": "text", "width": "3fr"},
        {"k": "is_default", "label": "Default", "type": "boolean", "width": "0.8fr"},
    ],
    fields=[
        {"k": "name", "label": "Name", "type": "text", "required": True},
        {"k": "description", "label": "Description", "type": "text"},
        {"k": "is_default", "label": "Default pipeline", "type": "boolean", "default": False},
    ],
    relations=[{"key": "stages", "label": "Stages", "entity": "pipeline-stages", "fk": "pipeline_id"}],
)

entity(
    key="pipeline-stages", entity_type="pipeline_stages", model=m.PipelineStage,
    label="Pipeline stage", plural="Pipeline stages", workspace="Config", module="CRM setup",
    icon="sliders", accent="#FFCDB2", order_by="sort_order", search=["name"], title_field="name",
    columns=[
        {"k": "sort_order", "label": "#", "type": "number", "width": "0.4fr"},
        {"k": "name", "label": "Stage", "type": "text", "width": "2fr", "primary": True},
        {"k": "pipeline_id", "label": "Pipeline", "type": "ref", "ref": "pipelines", "width": "1.5fr"},
        {"k": "probability", "label": "Probability", "type": "percent", "width": "1fr", "align": "right"},
        {"k": "is_won", "label": "Won", "type": "boolean", "width": "0.6fr"},
        {"k": "is_lost", "label": "Lost", "type": "boolean", "width": "0.6fr"},
    ],
    fields=[
        {"k": "name", "label": "Name", "type": "text", "required": True},
        {"k": "pipeline_id", "label": "Pipeline", "type": "ref", "ref": "pipelines", "required": True},
        {"k": "sort_order", "label": "Order", "type": "number", "default": 0},
        {"k": "probability", "label": "Probability %", "type": "number"},
        {"k": "is_won", "label": "Counts as won", "type": "boolean", "default": False},
        {"k": "is_lost", "label": "Counts as lost", "type": "boolean", "default": False},
        {"k": "color", "label": "Colour", "type": "text", "default": "#C8B6FF"},
    ],
)

entity(
    key="lost-reasons", entity_type="lost_reasons", model=m.LostReason,
    label="Lost reason", plural="Lost reasons", workspace="Config", module="CRM setup",
    icon="sliders", accent="#FFCDB2", order_by="name", search=["name"], title_field="name",
    columns=[{"k": "name", "label": "Reason", "type": "text", "width": "1fr", "primary": True}],
    fields=[{"k": "name", "label": "Reason", "type": "text", "required": True}],
)


# ────────────────────────────────────────────────────────────────────────────
# CRM · Catalog — Services and Products are one table split by item_type
# ────────────────────────────────────────────────────────────────────────────

_ITEM_COLUMNS = [
    {"k": "name", "label": "Name", "type": "text", "width": "2.2fr", "primary": True},
    {"k": "code", "label": "Code", "type": "mono", "width": "1fr"},
    {"k": "category_id", "label": "Category", "type": "ref", "ref": "item-categories", "width": "1.3fr"},
    {"k": "selling_price", "label": "One-time", "type": "money", "width": "1.1fr", "align": "right"},
    {"k": "monthly_price", "label": "Monthly", "type": "money", "width": "1.1fr", "align": "right"},
    {"k": "gst_rate", "label": "GST %", "type": "percent", "width": "0.8fr", "align": "right"},
    {"k": "is_active", "label": "Active", "type": "boolean", "width": "0.7fr"},
]

_ITEM_FIELDS = [
    {"k": "name", "label": "Name", "type": "text", "required": True, "group": "Item"},
    {"k": "code", "label": "Code", "type": "text", "group": "Item"},
    {"k": "category_id", "label": "Category", "type": "ref", "ref": "item-categories", "group": "Item"},
    {"k": "description", "label": "Description", "type": "textarea", "group": "Item"},
    {"k": "selling_price", "label": "One-time price", "type": "money", "group": "Pricing"},
    {"k": "monthly_price", "label": "Monthly price", "type": "money", "group": "Pricing"},
    {"k": "hsn_sac_code", "label": "HSN / SAC", "type": "text", "group": "Tax"},
    {"k": "gst_rate", "label": "GST rate %", "type": "number", "group": "Tax"},
    {"k": "is_active", "label": "Active", "type": "boolean", "default": True, "group": "Tax"},
]

entity(
    key="services", entity_type="items", model=m.Item,
    label="Service", plural="Services", workspace="CRM", module="Catalog",
    icon="package", accent="#FFCDB2", order_by="name",
    search=["name", "code", "description"], title_field="name",
    # Two tabs, one table: the scope filter is what makes them different.
    scope={"item_type": "service"},
    columns=_ITEM_COLUMNS, fields=_ITEM_FIELDS,
    key_facts=["category_id", "selling_price", "monthly_price", "gst_rate", "hsn_sac_code"],
    relations=[{"key": "projects", "label": "Projects", "entity": "projects", "fk": "item_id"}],
)

entity(
    # NOT `products`: /api/products is already the platform's own product-config
    # route, and a registry key that collides with a hand-written route is
    # silently unreachable. `check_route_collisions` in main.py enforces this.
    key="catalog-products", entity_type="items", model=m.Item,
    label="Product", plural="Products", workspace="CRM", module="Catalog",
    icon="package", accent="#FFCDB2", order_by="name",
    search=["name", "code", "description"], title_field="name",
    scope={"item_type": "goods"},
    columns=_ITEM_COLUMNS, fields=_ITEM_FIELDS,
    key_facts=["category_id", "selling_price", "monthly_price", "gst_rate", "hsn_sac_code"],
    relations=[{"key": "projects", "label": "Projects", "entity": "projects", "fk": "item_id"}],
)

entity(
    key="item-categories", entity_type="item_categories", model=m.ItemCategory,
    label="Category", plural="Categories", workspace="Config", module="CRM setup",
    icon="sliders", accent="#FFCDB2", order_by="name", search=["name"], title_field="name",
    columns=[
        {"k": "name", "label": "Name", "type": "text", "width": "2fr", "primary": True},
        {"k": "kind", "label": "Kind", "type": "badge", "width": "1fr"},
        {"k": "parent_id", "label": "Parent", "type": "ref", "ref": "item-categories", "width": "1.5fr"},
    ],
    fields=[
        {"k": "name", "label": "Name", "type": "text", "required": True},
        {"k": "kind", "label": "Kind", "type": "select", "options": ["service", "product"], "default": "service"},
        {"k": "parent_id", "label": "Parent category", "type": "ref", "ref": "item-categories"},
        {"k": "sort_order", "label": "Order", "type": "number", "default": 0},
    ],
)


# ────────────────────────────────────────────────────────────────────────────
# CRM · Projects — delivery
# ────────────────────────────────────────────────────────────────────────────

entity(
    key="projects",
    entity_type="projects",
    model=m.Project,
    label="Project",
    plural="Projects",
    workspace="CRM",
    module="Projects",
    icon="clipboard",
    accent="#B8E0D2",
    order_by="-created_at",
    search=["name", "doc_no", "description", "next_action"],
    title_field="name",
    columns=[
        {"k": "name", "label": "Project", "type": "text", "width": "2.2fr", "primary": True},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "width": "1.4fr"},
        # Wide enough for the longest stage label ("Onboarding Completed") —
        # a truncated status badge is worse than useless, it misreads.
        {"k": "stage", "label": "Stage", "type": "badge", "width": "1.75fr"},
        {"k": "next_action", "label": "Next action", "type": "text", "width": "2fr"},
        {"k": "next_action_date", "label": "By", "type": "date", "width": "1fr"},
        {"k": "next_action_owner_id", "label": "Owner", "type": "ref", "ref": "users", "width": "1.1fr"},
        {"k": "one_time_amount", "label": "One-time", "type": "money", "width": "1.1fr", "align": "right"},
        {"k": "monthly_amount", "label": "Monthly", "type": "money", "width": "1fr", "align": "right"},
    ],
    fields=[
        {"k": "name", "label": "Project name", "type": "text", "required": True, "group": "Project",
         "help": "The working convention is '<Customer> — <Service>'."},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "group": "Project"},
        {"k": "item_id", "label": "Service / product", "type": "ref", "ref": "services", "group": "Project"},
        {"k": "manager_id", "label": "Manager", "type": "ref", "ref": "users", "group": "Project"},
        {"k": "stage", "label": "Stage", "type": "select", "options": PROJECT_STAGES,
         "default": "Not started", "group": "Project"},
        {"k": "status", "label": "Status", "type": "select",
         "options": ["active", "on_hold", "completed", "cancelled"], "default": "active", "group": "Project"},
        {"k": "description", "label": "Description", "type": "textarea", "group": "Project"},

        {"k": "next_action", "label": "Next action", "type": "text", "group": "Next move"},
        {"k": "next_action_date", "label": "Next action date", "type": "date", "group": "Next move"},
        {"k": "next_action_owner_id", "label": "Next action owner", "type": "ref", "ref": "users", "group": "Next move"},

        {"k": "billing_type", "label": "Billing type", "type": "select",
         "options": ["fixed", "milestone", "monthly", "time_material"], "default": "fixed", "group": "Commercials"},
        {"k": "one_time_amount", "label": "One-time amount", "type": "money", "group": "Commercials"},
        {"k": "monthly_amount", "label": "Monthly amount", "type": "money", "group": "Commercials"},
        {"k": "duration_months", "label": "Duration (months)", "type": "number", "group": "Commercials"},

        {"k": "start_date", "label": "Start date", "type": "date", "group": "Dates"},
        {"k": "go_live_date", "label": "Go-live date", "type": "date", "group": "Dates"},
        {"k": "end_date", "label": "End date", "type": "date", "group": "Dates"},
        {"k": "completion_pct", "label": "Completion %", "type": "number", "group": "Dates"},

        {"k": "prod_url", "label": "Production URL", "type": "url", "group": "Links"},
        {"k": "document_url", "label": "Document URL", "type": "url", "group": "Links"},
        {"k": "gdrive_url", "label": "Drive URL", "type": "url", "group": "Links"},
        {"k": "notes", "label": "Notes", "type": "textarea", "group": "Links"},
    ],
    key_facts=["party_id", "manager_id", "stage", "one_time_amount", "monthly_amount", "start_date", "prod_url"],
    relations=[
        {"key": "milestones", "label": "Milestones", "entity": "milestones", "fk": "project_id"},
        {"key": "tasks", "label": "Tasks", "entity": "tasks", "fk": "project_id"},
        {"key": "members", "label": "Team", "entity": "project-members", "fk": "project_id"},
        {"key": "leads", "label": "Won from", "entity": "leads", "fk": "converted_project_id"},
    ],
    saved_views=[
        {"name": "Ongoing", "filters": {"status": "active"}},
        {"name": "All", "filters": {}},
        {"name": "Not started", "filters": {"stage": "Not started"}},
        {"name": "In progress", "filters": {"stage": "In progress"}},
        {"name": "Completed", "filters": {"stage": "Project Completed"}},
    ],
)

entity(
    key="milestones", entity_type="milestones", model=m.Milestone,
    label="Milestone", plural="Milestones", workspace="CRM", module="Projects",
    icon="calendar", accent="#B8E0D2", order_by="sort_order",
    search=["name", "description"], title_field="name",
    columns=[
        {"k": "sort_order", "label": "#", "type": "number", "width": "0.4fr"},
        {"k": "name", "label": "Milestone", "type": "text", "width": "2.2fr", "primary": True},
        {"k": "project_id", "label": "Project", "type": "ref", "ref": "projects", "width": "1.8fr"},
        {"k": "due_date", "label": "Due", "type": "date", "width": "1fr"},
        {"k": "amount", "label": "Amount", "type": "money", "width": "1.1fr", "align": "right"},
        {"k": "status", "label": "Status", "type": "badge", "width": "1fr"},
    ],
    fields=[
        {"k": "name", "label": "Name", "type": "text", "required": True},
        {"k": "project_id", "label": "Project", "type": "ref", "ref": "projects", "required": True},
        {"k": "description", "label": "Description", "type": "textarea"},
        {"k": "sort_order", "label": "Order", "type": "number", "default": 0},
        {"k": "due_date", "label": "Due date", "type": "date"},
        {"k": "completed_on", "label": "Completed on", "type": "date"},
        {"k": "amount", "label": "Amount", "type": "money"},
        {"k": "status", "label": "Status", "type": "select",
         "options": ["pending", "in_progress", "completed", "invoiced"], "default": "pending"},
        {"k": "zoho_invoice_number", "label": "Zoho invoice no.", "type": "text",
         "help": "The Zoho Books invoice this milestone was billed on, e.g. Z0/26-27/011."},
        {"k": "zoho_invoice_id", "label": "Zoho invoice id", "type": "text"},
    ],
)

entity(
    key="project-members", entity_type="project_members", model=m.ProjectMember,
    label="Team member", plural="Team", workspace="CRM", module="Projects",
    icon="users", accent="#B8E0D2", order_by="id", search=[], title_field="role",
    columns=[
        {"k": "user_id", "label": "Member", "type": "ref", "ref": "users", "width": "2fr", "primary": True},
        {"k": "project_id", "label": "Project", "type": "ref", "ref": "projects", "width": "2fr"},
        {"k": "role", "label": "Role", "type": "badge", "width": "1fr"},
        {"k": "allocation_pct", "label": "Allocation", "type": "percent", "width": "1fr", "align": "right"},
        {"k": "is_active", "label": "Active", "type": "boolean", "width": "0.7fr"},
    ],
    fields=[
        {"k": "project_id", "label": "Project", "type": "ref", "ref": "projects", "required": True},
        {"k": "user_id", "label": "Member", "type": "ref", "ref": "users", "required": True},
        {"k": "role", "label": "Role", "type": "select", "options": ["manager", "member", "viewer"],
         "default": "member"},
        {"k": "allocation_pct", "label": "Allocation %", "type": "number"},
        {"k": "joined_on", "label": "Joined on", "type": "date"},
        {"k": "is_active", "label": "Active", "type": "boolean", "default": True},
    ],
)


# ────────────────────────────────────────────────────────────────────────────
# Work · tasks and standing work streams — the Google Tasks replacement
# ────────────────────────────────────────────────────────────────────────────

entity(
    key="tasks",
    entity_type="tasks",
    model=m.Task,
    label="Task",
    plural="Tasks",
    workspace="Work",
    module="Tasks",
    icon="clipboard",
    accent="#B8E0D2",
    order_by="-created_at",
    search=["title", "description", "external_ref"],
    title_field="title",
    columns=[
        {"k": "title", "label": "Task", "type": "text", "width": "3fr", "primary": True},
        {"k": "owner_id", "label": "Owner", "type": "ref", "ref": "users", "width": "1.2fr"},
        {"k": "party_id", "label": "For", "type": "ref", "ref": "customers", "width": "1.4fr"},
        {"k": "project_id", "label": "Project", "type": "ref", "ref": "projects", "width": "1.6fr"},
        {"k": "due_date", "label": "Due", "type": "date", "width": "1fr"},
        {"k": "priority", "label": "Priority", "type": "badge", "width": "0.9fr"},
        {"k": "status", "label": "Status", "type": "badge", "width": "1fr"},
    ],
    fields=[
        {"k": "title", "label": "Task", "type": "text", "required": True, "group": "Task"},
        {"k": "description", "label": "Description", "type": "textarea", "group": "Task"},
        {"k": "owner_id", "label": "Owner", "type": "ref", "ref": "users", "group": "Task"},
        {"k": "status", "label": "Status", "type": "select", "options": TASK_STATUSES,
         "default": "open", "group": "Task"},
        {"k": "priority", "label": "Priority", "type": "select", "options": PRIORITIES,
         "default": "medium", "group": "Task"},

        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "group": "Context"},
        {"k": "project_id", "label": "Project", "type": "ref", "ref": "projects", "group": "Context"},
        {"k": "work_stream_id", "label": "Work stream", "type": "ref", "ref": "work-streams", "group": "Context"},
        {"k": "job_type_id", "label": "Job type", "type": "ref", "ref": "job-types", "group": "Context",
         "hint": "The kind of work this is. Manage the list under Work › Job types."},
        {"k": "lead_id", "label": "Lead", "type": "ref", "ref": "leads", "group": "Context"},
        {"k": "milestone_id", "label": "Milestone", "type": "ref", "ref": "milestones", "group": "Context"},

        {"k": "task_date", "label": "Task date", "type": "date", "group": "Dates",
         "help": "The day this sits on, mirroring a Daily Task date page."},
        {"k": "due_date", "label": "Due date", "type": "date", "group": "Dates"},
        {"k": "start_date", "label": "Start date", "type": "date", "group": "Dates"},
        {"k": "estimated_hours", "label": "Estimated hours", "type": "number", "group": "Dates"},
        {"k": "is_billable", "label": "Billable", "type": "boolean", "default": False, "group": "Dates"},

        {"k": "external_ref", "label": "External ref", "type": "text", "group": "Sync",
         "help": "Back-reference to a wiki row or an external task id."},
    ],
    key_facts=["owner_id", "status", "priority", "due_date", "project_id", "party_id", "source"],
    relations=[],
    saved_views=[
        {"name": "Open", "filters": {"status": ["open", "in_progress", "blocked"]}},
        {"name": "Today", "filters": {"due_date": "today"}},
        {"name": "Overdue", "filters": {"overdue": True}},
        {"name": "Mine", "filters": {"owner_id": "me"}},
        {"name": "Done", "filters": {"status": "done"}},
        {"name": "All", "filters": {}},
    ],
    actions=[
        {"key": "remark", "label": "Add remark", "method": "POST", "path": "/api/tasks/{id}/remarks",
         "description": "Append an Owner Remark. Append-only: remarks are never edited or deleted, "
                        "a correction is a new remark."},
    ],
)

entity(
    key="work-streams",
    entity_type="work_streams",
    model=m.WorkStream,
    label="Work stream",
    plural="Work streams",
    workspace="Work",
    module="Work",
    icon="activity",
    accent="#C8B6FF",
    order_by="name",
    search=["name", "description"],
    title_field="name",
    columns=[
        {"k": "name", "label": "Work stream", "type": "text", "width": "2.4fr", "primary": True},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "width": "1.6fr"},
        {"k": "project_id", "label": "Project", "type": "ref", "ref": "projects", "width": "1.6fr"},
        {"k": "waiting_on_id", "label": "Waiting on", "type": "ref", "ref": "users", "width": "1.2fr"},
        {"k": "status", "label": "Status", "type": "badge", "width": "1fr"},
    ],
    fields=[
        {"k": "name", "label": "Name", "type": "text", "required": True,
         "help": "A standing stream keyed by the people in it, e.g. 'Meet x Nishant'."},
        {"k": "description", "label": "Description", "type": "textarea"},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers"},
        {"k": "project_id", "label": "Project", "type": "ref", "ref": "projects"},
        {"k": "waiting_on_id", "label": "Waiting on", "type": "ref", "ref": "users"},
        {"k": "status", "label": "Status", "type": "select", "options": ["active", "paused", "closed"],
         "default": "active"},
        {"k": "notes", "label": "Notes", "type": "textarea"},
    ],
    key_facts=["party_id", "project_id", "waiting_on_id", "status"],
    relations=[
        {"key": "tasks", "label": "Tasks", "entity": "tasks", "fk": "work_stream_id"},
        {"key": "members", "label": "Members", "entity": "work-stream-members", "fk": "work_stream_id"},
    ],
    saved_views=[
        {"name": "Active", "filters": {"status": "active"}},
        {"name": "All", "filters": {}},
    ],
)

entity(
    key="work-stream-members", entity_type="work_stream_members", model=m.WorkStreamMember,
    label="Member", plural="Members", workspace="Work", module="Work",
    icon="users", accent="#C8B6FF", order_by="id", search=[], title_field="role",
    columns=[
        {"k": "work_stream_id", "label": "Work stream", "type": "ref", "ref": "work-streams", "width": "2fr"},
        {"k": "user_id", "label": "User", "type": "ref", "ref": "users", "width": "1.5fr", "primary": True},
        {"k": "party_contact_id", "label": "Contact", "type": "ref", "ref": "contacts", "width": "1.5fr"},
        {"k": "role", "label": "Role", "type": "text", "width": "1fr"},
    ],
    fields=[
        {"k": "work_stream_id", "label": "Work stream", "type": "ref", "ref": "work-streams", "required": True},
        {"k": "user_id", "label": "Platform user", "type": "ref", "ref": "users"},
        {"k": "party_contact_id", "label": "External contact", "type": "ref", "ref": "contacts"},
        {"k": "role", "label": "Role", "type": "text"},
    ],
)


# ────────────────────────────────────────────────────────────────────────────
# Lookups
# ────────────────────────────────────────────────────────────────────────────

def public(e):
    """The JSON-safe shape published at /api/meta/entities (drops the model class)."""
    out = {k: v for k, v in e.items() if k != "model"}
    out.setdefault("scope", {})
    out.setdefault("relations", [])
    out.setdefault("saved_views", [{"name": "All", "filters": {}}])
    out.setdefault("actions", [])
    out.setdefault("key_facts", [])
    out.setdefault("read_only", False)
    out["path"] = "/api/" + e["key"]
    return out


def label_for(obj, ent):
    """Human-readable label for a row, used by refs and the audit log."""
    if obj is None:
        return None
    return getattr(obj, ent.get("title_field") or "name", None) or "#%s" % getattr(obj, "id", "?")


# `users` is not a registry entity (it predates the CRM model and has its own
# router), but ref fields point at it, so consumers need a way to resolve it.
USER_REF = {
    "key": "users",
    "path": "/api/users",
    "label": "User",
    "plural": "Users",
    "title_field": "name",
    "model": User,
}


# ────────────────────────────────────────────────────────────────────────────
# Tickets · helpdesk
# ────────────────────────────────────────────────────────────────────────────

TICKET_STATUSES = ["new", "open", "waiting_on_customer", "on_hold", "resolved", "closed"]
TICKET_CHANNELS = ["whatsapp", "email", "phone", "web", "walk_in", "internal"]

entity(
    key="tickets",
    entity_type="tickets",
    model=m.Ticket,
    label="Ticket",
    plural="Tickets",
    workspace="Tickets",
    module="Helpdesk",
    icon="bell",
    accent="#FFB5C2",
    order_by="-created_at",
    search=["subject", "description", "doc_no", "contact_name", "resolution"],
    title_field="subject",
    columns=[
        {"k": "doc_no", "label": "Ref", "type": "mono", "width": "0.8fr"},
        {"k": "subject", "label": "Subject", "type": "text", "width": "2.6fr", "primary": True},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "width": "1.5fr"},
        {"k": "category_id", "label": "Job type", "type": "ref", "ref": "job-types", "width": "1.3fr"},
        {"k": "assigned_to", "label": "Assigned", "type": "ref", "ref": "users", "width": "1.2fr"},
        {"k": "resolution_due_at", "label": "Due", "type": "date", "width": "1fr"},
        {"k": "priority", "label": "Priority", "type": "badge", "width": "0.9fr"},
        {"k": "status", "label": "Status", "type": "badge", "width": "1.4fr"},
    ],
    fields=[
        {"k": "subject", "label": "Subject", "type": "text", "required": True, "group": "Ticket"},
        {"k": "description", "label": "Description", "type": "textarea", "group": "Ticket"},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "group": "Ticket"},
        {"k": "category_id", "label": "Job type", "type": "ref", "ref": "job-types", "group": "Ticket"},
        {"k": "project_id", "label": "Project", "type": "ref", "ref": "projects", "group": "Ticket"},
        {"k": "doc_no", "label": "Reference", "type": "text", "group": "Ticket"},

        {"k": "assigned_to", "label": "Assigned to", "type": "ref", "ref": "users", "group": "Handling"},
        {"k": "status", "label": "Status", "type": "select", "options": TICKET_STATUSES,
         "default": "new", "group": "Handling"},
        {"k": "priority", "label": "Priority", "type": "select", "options": PRIORITIES,
         "default": "medium", "group": "Handling"},
        {"k": "channel", "label": "Came in via", "type": "select", "options": TICKET_CHANNELS,
         "default": "whatsapp", "group": "Handling"},
        {"k": "sla_policy_id", "label": "SLA policy", "type": "ref", "ref": "sla-policies", "group": "Handling"},

        {"k": "contact_name", "label": "Contact name", "type": "text", "group": "Reporter"},
        {"k": "contact_phone", "label": "Contact phone", "type": "phone", "group": "Reporter"},
        {"k": "contact_email", "label": "Contact email", "type": "email", "group": "Reporter"},

        {"k": "first_response_due_at", "label": "First response due", "type": "datetime", "group": "SLA"},
        {"k": "resolution_due_at", "label": "Resolution due", "type": "datetime", "group": "SLA"},
        {"k": "first_responded_at", "label": "First responded at", "type": "datetime", "group": "SLA"},
        {"k": "resolved_at", "label": "Resolved at", "type": "datetime", "group": "SLA"},
        {"k": "resolution", "label": "Resolution", "type": "textarea", "group": "SLA"},
    ],
    key_facts=["party_id", "assigned_to", "status", "priority", "category_id", "resolution_due_at", "channel"],
    relations=[],
    saved_views=[
        {"name": "Pending", "filters": {"status": ["new", "open", "waiting_on_customer", "on_hold"]}},
        {"name": "Mine", "filters": {"assigned_to": "me"}},
        {"name": "Unassigned", "filters": {"assigned_to": None}},
        {"name": "Urgent", "filters": {"priority": ["high", "urgent"]}},
        {"name": "Completed", "filters": {"status": ["resolved", "closed"]}},
        {"name": "All", "filters": {}},
    ],
)

entity(
    key="job-types", entity_type="ticket_categories", model=m.TicketCategory,
    label="Job type", plural="Job types", workspace="Tickets", module="Config",
    icon="sliders", accent="#FFB5C2", order_by="sort_order",
    search=["name", "description"], title_field="name",
    columns=[
        {"k": "name", "label": "Job type", "type": "text", "width": "2fr", "primary": True},
        {"k": "parent_id", "label": "Parent", "type": "ref", "ref": "job-types", "width": "1.4fr"},
        {"k": "default_priority", "label": "Default priority", "type": "badge", "width": "1.1fr"},
        {"k": "description", "label": "Description", "type": "text", "width": "2.4fr"},
        {"k": "is_active", "label": "Active", "type": "boolean", "width": "0.7fr"},
    ],
    fields=[
        {"k": "name", "label": "Name", "type": "text", "required": True},
        {"k": "parent_id", "label": "Parent job type", "type": "ref", "ref": "job-types"},
        {"k": "description", "label": "Description", "type": "textarea"},
        {"k": "default_priority", "label": "Default priority", "type": "select",
         "options": PRIORITIES, "default": "medium"},
        {"k": "sort_order", "label": "Order", "type": "number", "default": 0},
        {"k": "is_active", "label": "Active", "type": "boolean", "default": True},
    ],
    relations=[
        {"key": "tasks", "label": "Tasks", "entity": "tasks", "fk": "job_type_id"},
        {"key": "tickets", "label": "Tickets", "entity": "tickets", "fk": "category_id"},
    ],
)

entity(
    key="sla-policies", entity_type="sla_policies", model=m.SlaPolicy,
    label="SLA policy", plural="SLA policies", workspace="Tickets", module="Config",
    icon="gauge", accent="#FFB5C2", order_by="name", search=["name"], title_field="name",
    columns=[
        {"k": "name", "label": "Policy", "type": "text", "width": "2fr", "primary": True},
        {"k": "description", "label": "Description", "type": "text", "width": "3fr"},
        {"k": "use_business_hours", "label": "Business hours", "type": "boolean", "width": "1fr"},
        {"k": "is_default", "label": "Default", "type": "boolean", "width": "0.8fr"},
    ],
    fields=[
        {"k": "name", "label": "Name", "type": "text", "required": True},
        {"k": "description", "label": "Description", "type": "textarea"},
        {"k": "use_business_hours", "label": "Count business hours only", "type": "boolean", "default": False},
        {"k": "is_default", "label": "Default policy", "type": "boolean", "default": False},
    ],
)


# ────────────────────────────────────────────────────────────────────────────
# Communication · the omnichannel inbox
# ────────────────────────────────────────────────────────────────────────────

entity(
    key="conversations",
    entity_type="conversations",
    model=m.Conversation,
    label="Conversation",
    plural="Conversations",
    workspace="Comms",
    module="Inbox",
    icon="message",
    accent="#B8E0D2",
    order_by="-last_message_at",
    search=["contact_name", "contact_identifier", "subject"],
    title_field="contact_name",
    columns=[
        {"k": "contact_name", "label": "Contact", "type": "text", "width": "1.8fr", "primary": True},
        {"k": "contact_identifier", "label": "Address", "type": "mono", "width": "1.6fr"},
        {"k": "channel_id", "label": "Channel", "type": "ref", "ref": "channels", "width": "1.2fr"},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "width": "1.6fr"},
        {"k": "assigned_to", "label": "Assigned", "type": "ref", "ref": "users", "width": "1.2fr"},
        {"k": "last_message_at", "label": "Last message", "type": "date", "width": "1.1fr"},
        {"k": "status", "label": "Status", "type": "badge", "width": "0.9fr"},
    ],
    fields=[
        {"k": "contact_name", "label": "Contact name", "type": "text", "group": "Thread"},
        {"k": "contact_identifier", "label": "Address", "type": "text", "required": True, "group": "Thread",
         "help": "The number or mailbox they reach us from. One thread per address per channel."},
        {"k": "channel_id", "label": "Channel", "type": "ref", "ref": "channels", "required": True, "group": "Thread"},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "group": "Thread"},
        {"k": "party_contact_id", "label": "Person", "type": "ref", "ref": "contacts", "group": "Thread"},
        {"k": "subject", "label": "Subject", "type": "text", "group": "Thread"},
        {"k": "assigned_to", "label": "Assigned to", "type": "ref", "ref": "users", "group": "Handling"},
        {"k": "status", "label": "Status", "type": "select",
         "options": ["open", "pending", "snoozed", "closed"], "default": "open", "group": "Handling"},
    ],
    key_facts=["party_id", "channel_id", "assigned_to", "status", "last_message_at", "unread_count"],
    relations=[],
    saved_views=[
        {"name": "Open", "filters": {"status": "open"}},
        {"name": "Mine", "filters": {"assigned_to": "me"}},
        {"name": "Unlinked", "filters": {"party_id": None}},
        {"name": "All", "filters": {}},
    ],
)

entity(
    key="channels", entity_type="comm_channels", model=m.CommChannel,
    label="Channel", plural="Channels", workspace="Comms", module="Config",
    icon="sliders", accent="#B8E0D2", order_by="name", search=["name", "identifier"], title_field="name",
    columns=[
        {"k": "name", "label": "Channel", "type": "text", "width": "1.8fr", "primary": True},
        {"k": "channel_type", "label": "Type", "type": "badge", "width": "1fr"},
        {"k": "identifier", "label": "Address", "type": "mono", "width": "1.8fr"},
        {"k": "provider", "label": "Provider", "type": "text", "width": "1.2fr"},
        {"k": "status", "label": "Status", "type": "badge", "width": "0.9fr"},
    ],
    fields=[
        {"k": "name", "label": "Name", "type": "text", "required": True},
        {"k": "channel_type", "label": "Type", "type": "select",
         "options": ["whatsapp", "email", "sms", "instagram", "webform"], "default": "whatsapp"},
        {"k": "identifier", "label": "Address", "type": "text",
         "help": "The number or mailbox counterparties reach us on."},
        {"k": "provider", "label": "Provider", "type": "text"},
        {"k": "status", "label": "Status", "type": "select", "options": ["active", "paused"], "default": "active"},
    ],
    relations=[{"key": "conversations", "label": "Conversations", "entity": "conversations", "fk": "channel_id"}],
)


# ────────────────────────────────────────────────────────────────────────────
# Accounting · contracts and the Zoho Books mirror.
# Zoho Books raises every invoice; HQ plans the billing and reads the result.
# ────────────────────────────────────────────────────────────────────────────

entity(
    key="contracts",
    entity_type="contracts",
    model=m.Contract,
    label="Contract",
    plural="Contracts",
    workspace="Accounting",
    module="Contracts",
    icon="file",
    accent="#C8B6FF",
    order_by="-created_at",
    search=["title", "doc_no", "signatory_name", "notes"],
    title_field="title",
    columns=[
        {"k": "doc_no", "label": "Ref", "type": "mono", "width": "0.9fr"},
        {"k": "title", "label": "Contract", "type": "text", "width": "2.4fr", "primary": True},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "width": "1.6fr"},
        {"k": "contract_type", "label": "Type", "type": "badge", "width": "0.9fr"},
        {"k": "value", "label": "Value", "type": "money", "width": "1.2fr", "align": "right"},
        {"k": "monthly_value", "label": "Monthly", "type": "money", "width": "1.1fr", "align": "right"},
        {"k": "renewal_date", "label": "Renews", "type": "date", "width": "1.1fr"},
        {"k": "status", "label": "Status", "type": "badge", "width": "1fr"},
    ],
    fields=[
        {"k": "title", "label": "Title", "type": "text", "required": True, "group": "Contract"},
        {"k": "doc_no", "label": "Reference", "type": "text", "group": "Contract"},
        {"k": "party_id", "label": "Customer", "type": "ref", "ref": "customers", "group": "Contract"},
        {"k": "project_id", "label": "Project", "type": "ref", "ref": "projects", "group": "Contract"},
        {"k": "contract_type", "label": "Type", "type": "select",
         "options": ["msa", "sow", "retainer", "amc", "nda"], "default": "sow", "group": "Contract"},
        {"k": "status", "label": "Status", "type": "select",
         "options": ["draft", "sent", "signed", "active", "expired", "terminated", "renewed"],
         "default": "draft", "group": "Contract"},

        {"k": "value", "label": "Contract value", "type": "money", "group": "Commercials"},
        {"k": "monthly_value", "label": "Monthly value", "type": "money", "group": "Commercials"},

        {"k": "start_date", "label": "Start date", "type": "date", "group": "Term"},
        {"k": "end_date", "label": "End date", "type": "date", "group": "Term"},
        {"k": "auto_renew", "label": "Auto-renews", "type": "boolean", "default": False, "group": "Term"},
        {"k": "renewal_date", "label": "Renewal date", "type": "date", "group": "Term"},
        {"k": "notice_days", "label": "Notice period (days)", "type": "number", "group": "Term"},
        {"k": "signed_on", "label": "Signed on", "type": "date", "group": "Term"},
        {"k": "signatory_name", "label": "Signatory", "type": "text", "group": "Term"},

        {"k": "document_url", "label": "Document URL", "type": "url", "group": "Notes"},
        {"k": "notes", "label": "Notes", "type": "textarea", "group": "Notes"},
    ],
    key_facts=["party_id", "contract_type", "value", "monthly_value", "start_date", "renewal_date", "status"],
    relations=[
        {"key": "schedule", "label": "Billing schedule", "entity": "billing-schedule", "fk": "contract_id"},
    ],
    saved_views=[
        {"name": "Active", "filters": {"status": ["active", "signed"]}},
        {"name": "Draft", "filters": {"status": ["draft", "sent"]}},
        {"name": "All", "filters": {}},
    ],
)

entity(
    key="billing-schedule", entity_type="contract_billing_schedule", model=m.ContractBillingSchedule,
    label="Billing line", plural="Billing schedule", workspace="Accounting", module="Contracts",
    icon="list", accent="#C8B6FF", order_by="due_date", search=["name"], title_field="name",
    columns=[
        {"k": "seq", "label": "#", "type": "number", "width": "0.4fr"},
        {"k": "name", "label": "Billing line", "type": "text", "width": "2.2fr", "primary": True},
        {"k": "contract_id", "label": "Contract", "type": "ref", "ref": "contracts", "width": "1.8fr"},
        {"k": "due_date", "label": "Due", "type": "date", "width": "1.1fr"},
        {"k": "amount", "label": "Amount", "type": "money", "width": "1.2fr", "align": "right"},
        {"k": "zoho_invoice_number", "label": "Zoho invoice", "type": "mono", "width": "1.3fr"},
        {"k": "status", "label": "Status", "type": "badge", "width": "1fr"},
    ],
    fields=[
        {"k": "contract_id", "label": "Contract", "type": "ref", "ref": "contracts", "required": True},
        {"k": "name", "label": "Billing line", "type": "text", "required": True},
        {"k": "seq", "label": "Sequence", "type": "number", "default": 1},
        {"k": "trigger_type", "label": "Triggered by", "type": "select",
         "options": ["date", "milestone", "manual"], "default": "date"},
        {"k": "milestone_id", "label": "Milestone", "type": "ref", "ref": "milestones"},
        {"k": "due_date", "label": "Due date", "type": "date"},
        {"k": "amount", "label": "Amount", "type": "money"},
        {"k": "status", "label": "Status", "type": "select",
         "options": ["pending", "invoiced", "cancelled"], "default": "pending"},
        {"k": "zoho_invoice_number", "label": "Zoho invoice no.", "type": "text",
         "help": "Filled in once the invoice is raised in Zoho Books."},
        {"k": "invoiced_on", "label": "Invoiced on", "type": "date"},
    ],
    saved_views=[
        {"name": "To raise", "filters": {"status": "pending"}},
        {"name": "Invoiced", "filters": {"status": "invoiced"}},
        {"name": "All", "filters": {}},
    ],
)

entity(
    key="invoices",
    entity_type="zoho_invoices",
    model=m.ZohoInvoice,
    label="Invoice",
    plural="Invoices",
    workspace="Accounting",
    module="Billing",
    icon="file",
    accent="#C8B6FF",
    order_by="-invoice_date",
    search=["invoice_number", "customer_name"],
    title_field="invoice_number",
    # Read-only mirror: `fields` is empty so the generic CRUD has nothing
    # writable, and the UI renders no create or edit form. Zoho Books is the
    # only place an invoice is raised or changed.
    read_only=True,
    columns=[
        {"k": "invoice_number", "label": "Invoice", "type": "mono", "width": "1.3fr", "primary": True},
        {"k": "customer_name", "label": "Customer", "type": "text", "width": "2fr"},
        {"k": "invoice_date", "label": "Date", "type": "date", "width": "1.1fr"},
        {"k": "due_date", "label": "Due", "type": "date", "width": "1.1fr"},
        {"k": "total", "label": "Amount", "type": "money", "width": "1.2fr", "align": "right"},
        {"k": "balance_due", "label": "Balance", "type": "money", "width": "1.2fr", "align": "right"},
        {"k": "status", "label": "Status", "type": "badge", "width": "1fr"},
    ],
    fields=[],
    key_facts=["customer_name", "total", "balance_due", "status", "invoice_date", "due_date"],
    saved_views=[
        {"name": "Unpaid", "filters": {"status": ["sent", "overdue", "partially_paid"]}},
        {"name": "Overdue", "filters": {"status": "overdue"}},
        {"name": "Paid", "filters": {"status": "paid"}},
        {"name": "All", "filters": {}},
    ],
)
