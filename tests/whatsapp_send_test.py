#!/usr/bin/env python3
"""Offline tests for outbound WhatsApp delivery.

    python3 tests/whatsapp_send_test.py

Stdlib only, and not one packet leaves the machine. ``backend.whatsapp`` puts
every request through a single ``requests.Session`` held at module level, so each
test swaps in a scripted stand-in and asserts on what HQ *would* have sent.

Two properties are worth more than the rest, and most of this file exists to
defend them:

**HQ never reports a delivery it did not get.** Every failure shape the bot can
produce — refused, disconnected, bad token, unreachable, HTML error page — has to
come back as a WhatsAppError, because the caller turns anything else into a
thread that says "sent".

**HQ never dials a number it invented.** Conversations store ten digits; a
country code has to come from somewhere real or the send is declined. Getting
this wrong delivers a client's message to a stranger, which no later fix undoes.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402  (path shim must come first)

from backend import comms, whatsapp  # noqa: E402


# ── stand-ins ───────────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class FakeSession:
    """Scripted responses that also record what was sent."""

    def __init__(self, posts=None, gets=None):
        self.post_responses = list(posts or [])
        self.get_responses = list(gets or [])
        self.posts = []
        self.gets = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append({"url": url, "headers": headers or {},
                           "json": json or {}, "timeout": timeout})
        if not self.post_responses:
            raise AssertionError("unexpected extra POST: %s" % url)
        nxt = self.post_responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def get(self, url, headers=None, timeout=None):
        self.gets.append({"url": url, "headers": headers or {}, "timeout": timeout})
        if not self.get_responses:
            raise AssertionError("unexpected extra GET: %s" % url)
        nxt = self.get_responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class FakeContact:
    def __init__(self, phone=None, whatsapp_number=None):
        self.phone = phone
        self.whatsapp = whatsapp_number


class FakeParty:
    def __init__(self, phone=None):
        self.phone = phone


class FakeConversation:
    def __init__(self, identifier, party=None, party_contact_id=None):
        self.contact_identifier = identifier
        self.party = party
        self.party_contact_id = party_contact_id


class FakeDb:
    """Answers the one query dial_address makes, and nothing else."""

    def __init__(self, contact=None):
        self.contact = contact

    def query(self, _model):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return self.contact


class WhatsAppTestCase(unittest.TestCase):
    """Restores the module's real session and environment after every test."""

    ENV = ("WHATSAPP_BOT_API_TOKEN", "WHATSAPP_BOT_URL", "WHATSAPP_COUNTRY_CODE")

    def setUp(self):
        self._session = whatsapp._SESSION
        self._env = {k: os.environ.get(k) for k in self.ENV}
        os.environ["WHATSAPP_BOT_API_TOKEN"] = "test-token"
        os.environ["WHATSAPP_BOT_URL"] = "https://wa.example.test"
        os.environ.pop("WHATSAPP_COUNTRY_CODE", None)

    def tearDown(self):
        whatsapp._SESSION = self._session
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def install(self, **kwargs):
        session = FakeSession(**kwargs)
        whatsapp._SESSION = session
        return session


# ── addressing ──────────────────────────────────────────────────────────────

class DialAddressTests(WhatsAppTestCase):

    def test_prefers_the_contacts_whatsapp_number(self):
        db = FakeDb(FakeContact(phone="+91 79 2222 3333", whatsapp_number="+91-98251 15308"))
        convo = FakeConversation("9825115308", party=FakeParty("911111111111"),
                                 party_contact_id=7)
        self.assertEqual(whatsapp.dial_address(db, convo), "919825115308")

    def test_falls_back_to_the_contacts_phone_then_the_partys(self):
        db = FakeDb(FakeContact(phone="+91 98765 43210"))
        convo = FakeConversation("9876543210", party=FakeParty("912222222222"),
                                 party_contact_id=7)
        self.assertEqual(whatsapp.dial_address(db, convo), "919876543210")

        db = FakeDb(None)
        convo = FakeConversation("2222222222", party=FakeParty("+91 22222 22222"),
                                 party_contact_id=None)
        self.assertEqual(whatsapp.dial_address(db, convo), "912222222222")

    def test_recovers_the_country_code_the_thread_threw_away(self):
        """The identifier is what comms stored; the contact still has the real number."""
        stored = comms._normalise("+91-98251 15308", "whatsapp")
        self.assertEqual(stored, "9825115308")  # ten digits, not dialable

        db = FakeDb(FakeContact(whatsapp_number="+91-98251 15308"))
        convo = FakeConversation(stored, party_contact_id=7)
        self.assertEqual(whatsapp.dial_address(db, convo), "919825115308")

    def test_uses_the_threads_own_identifier_when_it_is_already_international(self):
        convo = FakeConversation("919825115308")
        self.assertEqual(whatsapp.dial_address(FakeDb(), convo), "919825115308")

    def test_prefixes_the_configured_country_code_for_a_bare_subscriber_number(self):
        os.environ["WHATSAPP_COUNTRY_CODE"] = "91"
        convo = FakeConversation("9825115308")
        self.assertEqual(whatsapp.dial_address(FakeDb(), convo), "919825115308")

    def test_declines_rather_than_guess_when_no_country_code_is_configured(self):
        os.environ["WHATSAPP_COUNTRY_CODE"] = ""
        convo = FakeConversation("9825115308")
        self.assertIsNone(whatsapp.dial_address(FakeDb(), convo))

    def test_declines_on_junk_and_on_numbers_that_are_not_numbers(self):
        os.environ["WHATSAPP_COUNTRY_CODE"] = "91"
        for identifier in ("", "not a phone", "12345", "9" * 20):
            convo = FakeConversation(identifier)
            self.assertIsNone(whatsapp.dial_address(FakeDb(), convo),
                              "should not dial %r" % identifier)

    def test_ignores_a_contact_number_that_is_itself_only_ten_digits(self):
        """A contact with no country code is no better than the thread identifier."""
        os.environ["WHATSAPP_COUNTRY_CODE"] = "91"
        db = FakeDb(FakeContact(phone="9825115308"))
        convo = FakeConversation("9825115308", party_contact_id=7)
        self.assertEqual(whatsapp.dial_address(db, convo), "919825115308")


# ── sending ─────────────────────────────────────────────────────────────────

class SendTextTests(WhatsAppTestCase):

    def test_sends_and_returns_the_providers_message_id(self):
        session = self.install(posts=[FakeResponse(200, {"success": True, "messageId": "ABC123"})])
        self.assertEqual(whatsapp.send_text("919825115308", "hello"), "ABC123")

        sent = session.posts[0]
        self.assertEqual(sent["url"], "https://wa.example.test/api/send/text")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(sent["json"], {"to": "919825115308", "message": "hello"})
        self.assertTrue(sent["timeout"], "a send must not hang forever")

    def test_a_refusal_is_an_error_carrying_the_bots_reason(self):
        self.install(posts=[FakeResponse(400, {"success": False, "error": "Missing: to, message"})])
        with self.assertRaises(whatsapp.WhatsAppError) as caught:
            whatsapp.send_text("919825115308", "hello")
        self.assertIn("Missing: to, message", str(caught.exception))

    def test_a_disconnected_bot_says_so_and_points_at_the_qr(self):
        self.install(posts=[FakeResponse(503, {"success": False, "error": "WhatsApp not connected"})])
        with self.assertRaises(whatsapp.WhatsAppError) as caught:
            whatsapp.send_text("919825115308", "hello")
        self.assertIn("/api/qr", str(caught.exception))

    def test_a_rejected_token_names_the_variable_to_fix(self):
        for status in (401, 403):
            self.install(posts=[FakeResponse(status, {"success": False, "error": "Unauthorized"})])
            with self.assertRaises(whatsapp.WhatsAppError) as caught:
                whatsapp.send_text("919825115308", "hello")
            self.assertIn("WHATSAPP_BOT_API_TOKEN", str(caught.exception))

    def test_an_unreachable_bot_is_an_error_not_a_raw_requests_exception(self):
        self.install(posts=[requests.ConnectionError("connection refused")])
        with self.assertRaises(whatsapp.WhatsAppError) as caught:
            whatsapp.send_text("919825115308", "hello")
        self.assertIn("Could not reach", str(caught.exception))

    def test_a_non_json_body_is_a_failure_not_a_crash(self):
        """A 502 from nginx is an HTML page, and json() raises on it."""
        self.install(posts=[FakeResponse(502, None, text="<html>Bad Gateway</html>")])
        with self.assertRaises(whatsapp.WhatsAppError) as caught:
            whatsapp.send_text("919825115308", "hello")
        self.assertIn("502", str(caught.exception))

    def test_a_200_that_does_not_say_success_is_not_a_delivery(self):
        """Never trust the status line alone — the bot's own flag is the answer."""
        self.install(posts=[FakeResponse(200, {"success": False, "error": "no session"})])
        with self.assertRaises(whatsapp.WhatsAppError):
            whatsapp.send_text("919825115308", "hello")

    def test_refuses_to_send_when_no_token_is_configured(self):
        os.environ.pop("WHATSAPP_BOT_API_TOKEN", None)
        session = self.install()
        self.assertFalse(whatsapp.is_configured())
        with self.assertRaises(whatsapp.WhatsAppError):
            whatsapp.send_text("919825115308", "hello")
        self.assertEqual(session.posts, [], "an unconfigured send must not hit the network")


# ── status ──────────────────────────────────────────────────────────────────

class StatusTests(WhatsAppTestCase):

    def test_connected_when_the_bot_reports_an_open_session(self):
        self.install(gets=[FakeResponse(200, {"success": True, "status": "open"})])
        self.assertEqual(whatsapp.status()["state"], "connected")

    def test_reachable_but_logged_out_is_an_error_not_a_green_light(self):
        self.install(gets=[FakeResponse(200, {"success": True, "status": "close"})])
        out = whatsapp.status()
        self.assertEqual(out["state"], "error")
        self.assertIn("/api/qr", out["detail"])

    def test_an_outage_renders_as_a_red_dot_rather_than_raising(self):
        self.install(gets=[requests.ConnectionError("no route to host")])
        self.assertEqual(whatsapp.status()["state"], "error")

    def test_unconfigured_is_reported_without_touching_the_network(self):
        os.environ.pop("WHATSAPP_BOT_API_TOKEN", None)
        session = self.install()
        out = whatsapp.status()
        self.assertFalse(out["configured"])
        self.assertEqual(out["state"], "not configured")
        self.assertEqual(session.gets, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
