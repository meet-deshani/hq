"""Pull Zoho Books into HQ's read-only mirror.

`backend/zoho.py` talks to Zoho; this decides what HQ does with the answer. Kept
separate so the client stays a pure, offline-testable HTTP layer with no
database in it.

Three rules shape everything here:

1. **Nothing is written back to Zoho.** The mirror is one-directional.
2. **A link is never invented.** Receivables are only ever applied to a customer
   that carries a `zoho_contact_id`. Everything else comes back as a *proposal*
   for a human, because Zoho's "GOA TRADING & TECHNICAL SERVICES" is HQ's
   "Michael Bhai" and no algorithm can know that.
3. **A hand-edited figure is not clobbered silently.** A sync that overwrites
   what someone typed, without saying so, is how people stop trusting a number.
"""

import logging
from datetime import date, datetime
from decimal import Decimal

from backend import zoho
from backend.crm_models import Party, ZohoInvoice

logger = logging.getLogger("zoho_sync")


def _as_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_amount(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError):
        return None


def preview(db, organisation_id):
    """What a sync would do, without doing it.

    Worth having its own entry point: the first question anyone asks about an
    integration they have just connected is "what is it about to change?".
    """
    contacts = list(zoho.list_contacts())
    linked = {
        p.zoho_contact_id: p
        for p in db.query(Party).filter(
            Party.organisation_id == organisation_id,
            Party.zoho_contact_id.isnot(None),
        ).all()
    }
    unlinked = [
        {"id": p.id, "display_name": p.display_name, "email": p.email}
        for p in db.query(Party).filter(
            Party.organisation_id == organisation_id,
            Party.zoho_contact_id.is_(None),
        ).all()
    ]
    unmatched_zoho = [c for c in contacts if c.get("contact_id") not in linked]

    return {
        "zoho_contacts": len(contacts),
        "already_linked": len(linked),
        "proposals": zoho.match_contacts(unmatched_zoho, unlinked),
    }


def sync(db, organisation_id, actor=None, apply_links=False):
    """Pull contacts and invoices into the mirror. Returns a report of what changed.

    `apply_links` only ever applies matches Zoho's own data supports — an email
    match. Name-based proposals are returned for a human to accept, never
    applied here, however confident they look.
    """
    started = datetime.utcnow()
    report = {
        "started_at": started.isoformat() + "Z",
        "contacts_seen": 0,
        "invoices_seen": 0,
        "invoices_written": 0,
        "receivables_updated": 0,
        "receivables_skipped_edited": [],
        "links_applied": [],
        "proposals": [],
        "errors": [],
    }

    # ── contacts → receivables ──────────────────────────────────────────────
    contacts = list(zoho.list_contacts())
    report["contacts_seen"] = len(contacts)

    parties = db.query(Party).filter(Party.organisation_id == organisation_id).all()
    by_zoho_id = {p.zoho_contact_id: p for p in parties if p.zoho_contact_id}

    if apply_links:
        unlinked = [{"id": p.id, "display_name": p.display_name, "email": p.email}
                    for p in parties if not p.zoho_contact_id]
        by_id = {p.id: p for p in parties}
        for proposal in zoho.match_contacts(
            [c for c in contacts if c.get("contact_id") not in by_zoho_id], unlinked
        ):
            # Only an email match is safe to apply without a human. A name match,
            # however identical, can be two unrelated firms.
            if proposal.get("confidence") != "exact":
                continue
            party = by_id.get(proposal.get("hq_customer_id"))
            if party is None or party.zoho_contact_id:
                continue
            party.zoho_contact_id = proposal["zoho_contact_id"]
            party.zoho_contact_name = proposal.get("zoho_name")
            by_zoho_id[party.zoho_contact_id] = party
            report["links_applied"].append({
                "hq_customer": party.display_name,
                "zoho_name": proposal.get("zoho_name"),
                "reason": proposal.get("reason"),
            })

    for contact in contacts:
        party = by_zoho_id.get(contact.get("contact_id"))
        if party is None:
            continue
        incoming = _as_amount(contact.get("outstanding_receivable_amount"))
        if incoming is None:
            continue

        # If someone edited the figure by hand since the last sync, say so
        # rather than quietly replacing it.
        edited_by_hand = (
            party.outstanding_synced_at is not None
            and party.updated_at is not None
            and party.updated_at > party.outstanding_synced_at
            and party.outstanding_amount is not None
            and _as_amount(party.outstanding_amount) != incoming
        )
        if edited_by_hand:
            report["receivables_skipped_edited"].append({
                "customer": party.display_name,
                "in_hq": float(party.outstanding_amount),
                "in_zoho": float(incoming),
            })
            continue

        if _as_amount(party.outstanding_amount) != incoming:
            party.outstanding_amount = incoming
            report["receivables_updated"] += 1
        party.outstanding_synced_at = started
        if not party.zoho_contact_name:
            party.zoho_contact_name = contact.get("contact_name")

    # Whatever is still unlinked is a question for a human, every time.
    still_unlinked = [{"id": p.id, "display_name": p.display_name, "email": p.email}
                      for p in parties if not p.zoho_contact_id]
    report["proposals"] = zoho.match_contacts(
        [c for c in contacts if c.get("contact_id") not in by_zoho_id], still_unlinked
    )

    # ── invoices → mirror ───────────────────────────────────────────────────
    invoices = list(zoho.list_invoices())
    report["invoices_seen"] = len(invoices)

    existing = {
        row.zoho_invoice_id: row
        for row in db.query(ZohoInvoice).filter(
            ZohoInvoice.organisation_id == organisation_id
        ).all()
    }

    for inv in invoices:
        zid = inv.get("invoice_id")
        if not zid:
            continue
        party = by_zoho_id.get(inv.get("customer_id"))
        row = existing.get(zid)
        if row is None:
            row = ZohoInvoice(organisation_id=organisation_id, zoho_invoice_id=zid)
            db.add(row)
            existing[zid] = row

        row.invoice_number = inv.get("invoice_number")
        row.zoho_contact_id = inv.get("customer_id")
        row.customer_name = inv.get("customer_name")
        row.party_id = party.id if party else None
        row.invoice_date = _as_date(inv.get("date"))
        row.due_date = _as_date(inv.get("due_date"))
        row.status = inv.get("status")
        row.total = _as_amount(inv.get("total"))
        row.balance_due = _as_amount(inv.get("balance"))
        row.currency = inv.get("currency_code") or "INR"
        row.synced_at = started
        report["invoices_written"] += 1

    db.commit()
    report["finished_at"] = datetime.utcnow().isoformat() + "Z"
    logger.info(
        "Zoho sync: %d contacts, %d invoices, %d receivables updated, %d proposals pending",
        report["contacts_seen"], report["invoices_written"],
        report["receivables_updated"], len(report["proposals"]),
    )
    return report


def last_sync(db, organisation_id):
    newest = (
        db.query(ZohoInvoice.synced_at)
        .filter(ZohoInvoice.organisation_id == organisation_id)
        .order_by(ZohoInvoice.synced_at.desc())
        .first()
    )
    return newest[0].isoformat() + "Z" if newest and newest[0] else None
