#!/usr/bin/env python3
"""Inbound message policy: who is allowed into the inbox at all.

    python3 tests/comms_ingest_test.py

HQ's carrier is a WhatsApp bot running on a number that is also a personal
phone, and the inbox it feeds is read by the whole team. So there are two
opposite correct behaviours, and which one is right depends entirely on the
deployment:

  default                     keep everything; an unattached thread is visible
                              and fixable, a dropped message is neither
  COMMS_KNOWN_SENDERS_ONLY    keep only senders already on record, so family
                              and delivery notifications never reach the team

The tests that matter are the ones at the seam: an existing thread must keep
working after its customer link is gone, and the flag must never quietly discard
a message from someone HQ *does* know.
"""

import os
import sys
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-only")
_DB = os.path.join(tempfile.mkdtemp(), "comms_test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + _DB

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import comms  # noqa: E402
from backend.crm_models import CommChannel, Party, PartyContact  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.models import Organisation  # noqa: E402

ORG_SLUG = "test-org"


class IngestPolicyTests(unittest.TestCase):

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()
        org = Organisation(name="Test", slug=ORG_SLUG)
        self.db.add(org)
        self.db.flush()
        self.org_id = org.id

        self.db.add(CommChannel(organisation_id=self.org_id, name="WhatsApp",
                                channel_type="whatsapp", identifier="918320065658"))
        customer = Party(organisation_id=self.org_id, display_name="Known Customer",
                         phone="+91 98251 15308")
        self.db.add(customer)
        self.db.flush()
        self.customer_id = customer.id
        self.db.add(PartyContact(organisation_id=self.org_id, party_id=customer.id,
                                 name="Hemish", whatsapp="+91-98765 43210"))
        self.db.commit()
        os.environ.pop("COMMS_KNOWN_SENDERS_ONLY", None)

    def tearDown(self):
        self.db.close()
        os.environ.pop("COMMS_KNOWN_SENDERS_ONLY", None)

    def land(self, number, body="hello", external_id=None):
        return comms.ingest(self.db, self.org_id, {
            "channel_type": "whatsapp", "from": number, "body": body,
            "external_id": external_id,
        })

    # ── the flag itself ─────────────────────────────────────────────────────

    def test_the_flag_is_off_unless_explicitly_turned_on(self):
        self.assertFalse(comms.known_senders_only())
        for value in ("true", "TRUE", "1", "yes", "on"):
            os.environ["COMMS_KNOWN_SENDERS_ONLY"] = value
            self.assertTrue(comms.known_senders_only(), value)
        for value in ("false", "0", "no", "", "maybe"):
            os.environ["COMMS_KNOWN_SENDERS_ONLY"] = value
            self.assertFalse(comms.known_senders_only(), value)

    # ── default: keep everything ────────────────────────────────────────────

    def test_by_default_a_stranger_gets_an_unattached_thread(self):
        message, convo, created = self.land("919000000123")
        self.assertTrue(created)
        self.assertIsNone(convo.party_id)
        self.assertIsNotNone(message.id)

    # ── known senders only ──────────────────────────────────────────────────

    def test_a_stranger_is_dropped_when_the_flag_is_on(self):
        os.environ["COMMS_KNOWN_SENDERS_ONLY"] = "true"
        with self.assertRaises(comms.Ignored):
            self.land("919000000123")
        self.db.rollback()
        self.assertEqual(self.db.query(comms.Conversation).count(), 0,
                         "a dropped message must not leave a thread behind")

    def test_a_known_customer_still_gets_through(self):
        os.environ["COMMS_KNOWN_SENDERS_ONLY"] = "true"
        _, convo, created = self.land("919825115308")
        self.assertTrue(created)
        self.assertEqual(convo.party_id, self.customer_id)

    def test_a_known_contact_still_gets_through_however_the_number_is_written(self):
        """The contact is stored as '+91-98765 43210'; WhatsApp sends digits."""
        os.environ["COMMS_KNOWN_SENDERS_ONLY"] = "true"
        _, convo, created = self.land("919876543210")
        self.assertTrue(created)
        self.assertEqual(convo.party_id, self.customer_id)

    def test_an_existing_thread_keeps_working_after_its_customer_link_is_lost(self):
        """Turning the flag on must not strand conversations already here."""
        _, convo, _ = self.land("919000000123")          # created while off
        self.db.commit()
        os.environ["COMMS_KNOWN_SENDERS_ONLY"] = "true"
        _, again, created = self.land("919000000123", body="second", external_id="x2")
        self.assertTrue(created)
        self.assertEqual(again.id, convo.id)

    def test_a_replay_is_still_deduped_and_never_raises(self):
        os.environ["COMMS_KNOWN_SENDERS_ONLY"] = "true"
        first, _, created = self.land("919825115308", external_id="dup-1")
        self.db.commit()
        self.assertTrue(created)
        replay, _, created_again = self.land("919825115308", external_id="dup-1")
        self.assertFalse(created_again)
        self.assertEqual(replay.id, first.id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
