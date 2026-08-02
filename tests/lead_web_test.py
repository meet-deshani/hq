#!/usr/bin/env python3
"""Leads, customers, projects and tasks are one web — prove they stay in step.

Offline: an in-memory SQLite database and the real conversion code, no server.

The behaviours worth protecting, each of which was broken or absent before:

  * winning a lead for a company already in the book LINKS to it, instead of
    minting a second customer with the same name (the two Dorf-Ketals)
  * winning a lead opens the project it was for, and moves the lead's tasks onto
    that project so the delivery board agrees with the funnel
  * a task attached only to a lead needs no placeholder "Unknown" project
  * losing a lead marks the prospect Inactive, but never demotes a real customer
  * running conversion twice converges — it does not create a second
    customer, a second project, or move tasks a second time

The last one carries the safety of the whole design: `_run_hook` swallows what
the hook raises, so conversion must be idempotent rather than merely careful.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "lead-web-test-only")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.crm_models import Lead, Party, Project, Task  # noqa: E402
from backend.database import Base  # noqa: E402
from backend.models import Organisation, User  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (label, got, want))
        failures.append(label)


def fresh():
    """A database with one org and one user, and nothing else."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    org = Organisation(name="Z9S-AI", slug="z9s-ai")
    db.add(org)
    db.flush()
    user = User(
        email="agent@dotsai.in", name="Agent", password_hash="x",
        organisation_id=org.id, status="Active",
    )
    db.add(user)
    db.flush()
    return db, org, user


def new_lead(db, org, user, **kw):
    lead = Lead(organisation_id=org.id, owner_id=user.id,
                created_by_id=user.id, updated_by_id=user.id, **kw)
    db.add(lead)
    db.flush()
    return lead


# ── 1 · a won lead for a NEW company creates the customer and the project ────

def test_new_company():
    from backend.crud import sync_lead_outcome

    db, org, user = fresh()
    lead = new_lead(db, org, user, title="Ranger System AI use cases",
                    company_name="Acme Chemicals", contact_name="R Sharma",
                    phone="+91-9825115308", email="r@acme.com",
                    estimated_value=250000, status="won")
    out = sync_lead_outcome(db, lead, user)
    db.flush()

    check("new company -> a customer exists", db.query(Party).count(), 1)
    check("customer is kind=customer", out["party"].kind, "customer")
    check("customer is Active", out["party"].status, "Active")
    check("lead links to it", lead.party_id, out["party"].id)
    check("converted_party_id stamped", lead.converted_party_id, out["party"].id)
    check("a project was opened", db.query(Project).count(), 1)
    check("project is for that customer", out["project"].party_id, out["party"].id)
    check("project carries the lead's value", int(out["project"].one_time_amount), 250000)
    check("converted_project_id stamped", lead.converted_project_id, out["project"].id)


# ── 2 · the Dorf-Ketal case: a won lead for a company ALREADY in the book ────

def test_existing_customer_is_linked_not_duplicated():
    from backend.crud import sync_lead_outcome

    db, org, user = fresh()
    existing = Party(organisation_id=org.id, kind="prospect", status="Active",
                     display_name="Dorf-Ketal Chemicals", owner_id=user.id)
    db.add(existing)
    db.flush()

    lead = new_lead(db, org, user, title="Dorf-Ketal - Ranger System AI use cases",
                    company_name="Dorf-Ketal Chemicals", status="won")
    out = sync_lead_outcome(db, lead, user)
    db.flush()

    check("no second customer was created", db.query(Party).count(), 1)
    check("it linked to the existing one", out["party"].id, existing.id)
    check("prospect was promoted to customer", existing.kind, "customer")
    check("lead.party_id points at it", lead.party_id, existing.id)


def test_lead_raised_against_an_existing_customer():
    """An existing customer's second project starts life as a lead too."""
    from backend.crud import sync_lead_outcome

    db, org, user = fresh()
    customer = Party(organisation_id=org.id, kind="customer", status="Active",
                     display_name="NeoNir Engineering", owner_id=user.id)
    db.add(customer)
    db.flush()

    lead = new_lead(db, org, user, title="NeoNir - phase 2 portal",
                    party_id=customer.id, status="won")
    out = sync_lead_outcome(db, lead, user)
    db.flush()

    check("still one customer", db.query(Party).count(), 1)
    check("second project opened for them", db.query(Project).count(), 1)
    check("project belongs to the customer", out["project"].party_id, customer.id)
    check("customer stayed a customer", customer.kind, "customer")


# ── 3 · tasks follow the lead into the project, with no dummy project ────────

def test_tasks_follow_the_lead():
    from backend.crud import sync_lead_outcome

    db, org, user = fresh()
    lead = new_lead(db, org, user, title="Sustro lead engine",
                    company_name="Sustro Speciality Oils", status="open")

    # A task raised while the project is still unknown attaches to the lead
    # alone — no placeholder project row is needed for it to be valid.
    task = Task(organisation_id=org.id, title="Draft the SOW", lead_id=lead.id,
                created_by_id=user.id, updated_by_id=user.id)
    db.add(task)
    db.flush()
    check("task is valid with no project", task.project_id, None)

    lead.status = "won"
    out = sync_lead_outcome(db, lead, user)
    db.flush()

    check("task moved onto the new project", task.project_id, out["project"].id)
    check("task also learned the customer", task.party_id, out["party"].id)
    check("task keeps its funnel history", task.lead_id, lead.id)
    check("move was counted", out["tasks_moved"], 1)


def test_an_explicit_project_is_never_overridden():
    from backend.crud import sync_lead_outcome

    db, org, user = fresh()
    other = Project(organisation_id=org.id, name="Somewhere else", manager_id=user.id)
    db.add(other)
    db.flush()

    lead = new_lead(db, org, user, title="A lead", company_name="Some Co", status="won")
    pinned = Task(organisation_id=org.id, title="Already placed", lead_id=lead.id,
                  project_id=other.id, created_by_id=user.id, updated_by_id=user.id)
    db.add(pinned)
    db.flush()

    sync_lead_outcome(db, lead, user)
    db.flush()
    check("a deliberately placed task is left alone", pinned.project_id, other.id)


# ── 4 · losing ──────────────────────────────────────────────────────────────

def test_lost_lead_marks_the_prospect_inactive():
    from backend.crud import sync_lead_outcome

    db, org, user = fresh()
    lead = new_lead(db, org, user, title="Cold one", company_name="Nope Ltd", status="lost")
    out = sync_lead_outcome(db, lead, user)
    db.flush()

    check("prospect kept, not deleted", db.query(Party).count(), 1)
    check("marked Inactive", out["party"].status, "Inactive")
    check("no project was opened", db.query(Project).count(), 0)


def test_losing_never_demotes_a_real_customer():
    """One lost bid is not the end of a relationship."""
    from backend.crud import sync_lead_outcome

    db, org, user = fresh()
    customer = Party(organisation_id=org.id, kind="customer", status="Active",
                     display_name="BHB Incorporate", owner_id=user.id)
    db.add(customer)
    db.flush()

    lead = new_lead(db, org, user, title="A bid we lost", party_id=customer.id, status="lost")
    sync_lead_outcome(db, lead, user)
    db.flush()

    check("customer stays Active", customer.status, "Active")
    check("customer stays a customer", customer.kind, "customer")


# ── 5 · idempotence — the property the swallowing hook depends on ───────────

def test_converting_twice_converges():
    from backend.crud import sync_lead_outcome

    db, org, user = fresh()
    lead = new_lead(db, org, user, title="Repeat", company_name="Twice Co", status="won")
    task = Task(organisation_id=org.id, title="A task", lead_id=lead.id,
                created_by_id=user.id, updated_by_id=user.id)
    db.add(task)
    db.flush()

    first = sync_lead_outcome(db, lead, user)
    db.flush()
    second = sync_lead_outcome(db, lead, user)
    db.flush()

    check("still one customer", db.query(Party).count(), 1)
    check("still one project", db.query(Project).count(), 1)
    check("same customer both times", second["party"].id, first["party"].id)
    check("same project both times", second["project"].id, first["project"].id)
    check("second run created nothing", second["party_created"], False)
    check("second run opened nothing", second["project_created"], False)
    check("second run moved no tasks", second["tasks_moved"], 0)


def test_reopening_a_lost_lead_reactivates_the_prospect():
    from backend.crud import sync_lead_outcome

    db, org, user = fresh()
    lead = new_lead(db, org, user, title="Back on", company_name="Revive Co", status="lost")
    sync_lead_outcome(db, lead, user)
    db.flush()
    check("starts Inactive", lead.party.status, "Inactive")

    lead.status = "open"
    sync_lead_outcome(db, lead, user)
    db.flush()
    check("reopening makes it Active again", lead.party.status, "Active")


# ── 6 · a lead with nothing to identify it must not invent a customer ───────

def test_nameless_lead_creates_nothing():
    from backend.crud import sync_lead_outcome

    db, org, user = fresh()
    # `title` is NOT NULL, so the only truly nameless lead is one whose title is
    # blank; the point is that a blank name never becomes a blank customer.
    lead = new_lead(db, org, user, title="   ", status="won")
    out = sync_lead_outcome(db, lead, user)
    db.flush()

    check("no customer invented", db.query(Party).count(), 0)
    check("no project invented", db.query(Project).count(), 0)
    check("reported nothing", out["party"], None)


TESTS = [
    ("won lead, new company", test_new_company),
    ("won lead, company already in the book", test_existing_customer_is_linked_not_duplicated),
    ("lead raised against an existing customer", test_lead_raised_against_an_existing_customer),
    ("tasks follow the lead into its project", test_tasks_follow_the_lead),
    ("explicit task placement is respected", test_an_explicit_project_is_never_overridden),
    ("lost lead marks the prospect Inactive", test_lost_lead_marks_the_prospect_inactive),
    ("losing never demotes a real customer", test_losing_never_demotes_a_real_customer),
    ("converting twice converges", test_converting_twice_converges),
    ("reopening a lost lead reactivates it", test_reopening_a_lost_lead_reactivates_the_prospect),
    ("a nameless lead creates nothing", test_nameless_lead_creates_nothing),
]

if __name__ == "__main__":
    print("lead / customer / project / task web")
    for label, fn in TESTS:
        print("\n%s" % label)
        fn()
    print("\n%s" % ("-" * 58))
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("all green")
