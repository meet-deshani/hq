#!/usr/bin/env python3
"""What HQ does with Zoho's answer.

The client is tested offline elsewhere; this tests the decisions — what gets
mirrored, what gets linked, and above all what gets LEFT ALONE. This code will
one day run against Meet's real books, so the rules that protect his data are
asserted here rather than trusted.

    python3 tests/zoho_sync_test.py
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("SECRET_KEY", "test-only")
_DB = os.path.join(tempfile.mkdtemp(), "zoho_sync_test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + _DB

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import zoho, zoho_sync  # noqa: E402
from backend.crm_models import Party, ZohoInvoice  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.models import Organisation  # noqa: E402

# Real shapes from the live org, so the test fails if a field name drifts.
CONTACTS = [
    {"contact_id": "z-neonir", "contact_name": "NEO NIR ENGINEERING LLP",
     "company_name": "NEO NIR ENGINEERING LLP", "email": "hemish@neonir.com",
     "phone": "+91-9825115308", "outstanding_receivable_amount": 354000},
    {"contact_id": "z-goa", "contact_name": "GOA TRADING & TECHNICAL SERVICES",
     "company_name": "GOA TRADING & TECHNICAL SERVICES",
     "email": "michael.martins@gtandts.com", "phone": "",
     "outstanding_receivable_amount": 0},
    {"contact_id": "z-feedaqua", "contact_name": "Feed Aqua Engineering Private Limited",
     "company_name": "Feed Aqua Engineering Private Limited",
     "email": "ajaysingh@feedaqua.com", "phone": "",
     "outstanding_receivable_amount": 47200},
]

INVOICES = [
    {"invoice_id": "inv-1", "invoice_number": "Z0/2026-27/010", "customer_id": "z-neonir",
     "customer_name": "NEO NIR ENGINEERING LLP", "date": "2026-07-21",
     "due_date": "2026-07-28", "status": "sent", "total": 354000,
     "balance": 354000, "currency_code": "INR"},
    {"invoice_id": "inv-2", "invoice_number": "Z0/26-27/004", "customer_id": "z-feedaqua",
     "customer_name": "Feed Aqua Engineering Private Limited", "date": "2026-07-07",
     "due_date": "2026-07-14", "status": "overdue", "total": 47200,
     "balance": 47200, "currency_code": "INR"},
]


class SyncTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()
        self.org = Organisation(name="Z9S-AI", slug="z9s-ai")
        self.db.add(self.org)
        self.db.commit()

        # Stub the client. No network, ever.
        self._real = (zoho.list_contacts, zoho.list_invoices)
        zoho.list_contacts = lambda: list(CONTACTS)
        zoho.list_invoices = lambda: list(INVOICES)

    def tearDown(self):
        zoho.list_contacts, zoho.list_invoices = self._real
        self.db.close()

    def _party(self, name, **kw):
        p = Party(organisation_id=self.org.id, display_name=name, **kw)
        self.db.add(p)
        self.db.commit()
        return p

    # ── mirroring ───────────────────────────────────────────────────────────

    def test_invoices_are_mirrored(self):
        self._party("NeoNir Engineering", zoho_contact_id="z-neonir")
        report = zoho_sync.sync(self.db, self.org.id)

        self.assertEqual(report["invoices_written"], 2)
        rows = self.db.query(ZohoInvoice).all()
        self.assertEqual({r.invoice_number for r in rows},
                         {"Z0/2026-27/010", "Z0/26-27/004"})
        neonir = next(r for r in rows if r.zoho_contact_id == "z-neonir")
        self.assertEqual(float(neonir.balance_due), 354000.0)
        self.assertEqual(neonir.status, "overdue" if False else "sent")
        self.assertIsNotNone(neonir.party_id, "a linked invoice should attach to its customer")

    def test_syncing_twice_updates_rather_than_duplicates(self):
        self._party("NeoNir Engineering", zoho_contact_id="z-neonir")
        zoho_sync.sync(self.db, self.org.id)
        first = self.db.query(ZohoInvoice).count()
        zoho_sync.sync(self.db, self.org.id)
        self.assertEqual(self.db.query(ZohoInvoice).count(), first)

    def test_receivables_land_on_linked_customers_only(self):
        linked = self._party("NeoNir Engineering", zoho_contact_id="z-neonir")
        unlinked = self._party("Michael Bhai")
        zoho_sync.sync(self.db, self.org.id)
        self.db.refresh(linked)
        self.db.refresh(unlinked)

        self.assertEqual(float(linked.outstanding_amount), 354000.0)
        self.assertIsNone(unlinked.outstanding_amount,
                          "an unlinked customer must not receive a figure")

    # ── the protections ─────────────────────────────────────────────────────

    def test_a_hand_edited_figure_is_reported_not_overwritten(self):
        """Silently replacing a typed number is how people stop trusting it."""
        p = self._party("NeoNir Engineering", zoho_contact_id="z-neonir")
        zoho_sync.sync(self.db, self.org.id)
        self.db.refresh(p)

        # Someone corrects it by hand afterwards.
        p.outstanding_amount = 999
        p.updated_at = datetime.utcnow() + timedelta(minutes=5)
        self.db.commit()

        report = zoho_sync.sync(self.db, self.org.id)
        self.db.refresh(p)
        self.assertEqual(float(p.outstanding_amount), 999.0, "the hand edit was clobbered")
        self.assertTrue(report["receivables_skipped_edited"], "and it was not even reported")
        skipped = report["receivables_skipped_edited"][0]
        self.assertEqual(skipped["in_hq"], 999.0)
        self.assertEqual(skipped["in_zoho"], 354000.0)

    def test_name_matches_are_never_auto_applied(self):
        """The rule the whole design turns on.

        Zoho's "GOA TRADING & TECHNICAL SERVICES" IS HQ's "Michael Bhai", and
        nothing in the data says so. Auto-linking on a name would eventually put
        the wrong money on the wrong customer.
        """
        michael = self._party("Michael Bhai")
        feedaqua = self._party("FeedAqua")
        report = zoho_sync.sync(self.db, self.org.id, apply_links=True)
        self.db.refresh(michael)
        self.db.refresh(feedaqua)

        self.assertIsNone(michael.zoho_contact_id,
                          "Michael Bhai must never be auto-linked to GOA TRADING")
        self.assertIsNone(feedaqua.zoho_contact_id,
                          "a name-only match must not be applied automatically")
        linked_names = {l["hq_customer"] for l in report["links_applied"]}
        self.assertNotIn("Michael Bhai", linked_names)
        self.assertNotIn("FeedAqua", linked_names)

    def test_an_email_match_may_be_applied(self):
        """Zoho's own data supports this one, so a human need not confirm it."""
        p = self._party("NeoNir Engineering", email="hemish@neonir.com")
        report = zoho_sync.sync(self.db, self.org.id, apply_links=True)
        self.db.refresh(p)
        self.assertEqual(p.zoho_contact_id, "z-neonir")
        self.assertIn("NeoNir Engineering", {l["hq_customer"] for l in report["links_applied"]})

    def test_links_are_not_applied_unless_asked(self):
        p = self._party("NeoNir Engineering", email="hemish@neonir.com")
        report = zoho_sync.sync(self.db, self.org.id)  # apply_links defaults False
        self.db.refresh(p)
        self.assertIsNone(p.zoho_contact_id)
        self.assertEqual(report["links_applied"], [])

    def test_a_matchable_customer_is_proposed_and_an_unmatchable_one_is_not(self):
        """The two halves of the contract, in one test.

        A customer whose name Zoho plausibly shares comes back as a proposal a
        human can accept. "Michael Bhai" comes back as nothing at all, because
        the only thing linking it to GOA TRADING & TECHNICAL SERVICES is
        knowledge that lives in Meet's head. Proposing it anyway would be
        inventing confidence.
        """
        self._party("Michael Bhai")
        self._party("FeedAqua")
        report = zoho_sync.sync(self.db, self.org.id)

        proposed_hq = {p["hq_name"] for p in report["proposals"]}
        self.assertIn("FeedAqua", proposed_hq,
                      "a plausible name match should be offered for a human to accept")
        self.assertNotIn("Michael Bhai", proposed_hq,
                         "Michael Bhai is unmatchable by name — proposing it invents confidence")

    def test_preview_changes_nothing(self):
        p = self._party("NeoNir Engineering", email="hemish@neonir.com")
        before = self.db.query(ZohoInvoice).count()
        out = zoho_sync.preview(self.db, self.org.id)
        self.db.refresh(p)
        self.assertEqual(self.db.query(ZohoInvoice).count(), before)
        self.assertIsNone(p.zoho_contact_id, "preview must not link anything")
        self.assertEqual(out["zoho_contacts"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
