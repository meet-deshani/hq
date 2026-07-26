#!/usr/bin/env python3
"""Offline tests for the Zoho Books read-only client.

    python3 tests/zoho_client_test.py

Stdlib only, and not one packet leaves the machine. ``backend.zoho`` puts every
request through a single ``requests.Session`` held at module level, so each test
swaps in a scripted stand-in and then asserts on what the client *would* have
sent. That is the point: the behaviour worth testing here is the retry and
pagination bookkeeping, and against a live org you could never reliably provoke
a 429 or watch a token refresh exactly once.

The stand-in also refuses every verb but GET (bar the OAuth POST to
accounts.zoho), which turns "HQ never writes to Zoho Books" from a comment in
the module docstring into something that fails a build.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402  (path shim must come first)

from backend import zoho  # noqa: E402


# ── HTTP stand-ins ──────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class FakeSession:
    """Scripted responses, plus a hard stop on anything that would write."""

    def __init__(self, token=None, gets=None):
        self.token_responses = list(token or [])
        self.get_responses = list(gets or [])
        self.posts = []
        self.gets = []

    def post(self, url, data=None, timeout=None):
        if "zohoapis" in url:
            raise AssertionError("HQ must never POST to the Zoho Books API: %s" % url)
        self.posts.append({"url": url, "data": data, "timeout": timeout})
        if not self.token_responses:
            raise AssertionError("unexpected extra token request")
        nxt = self.token_responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def get(self, url, headers=None, params=None, timeout=None):
        self.gets.append({"url": url, "headers": headers or {},
                          "params": params or {}, "timeout": timeout})
        if not self.get_responses:
            raise AssertionError("unexpected extra GET: %s %s" % (url, params))
        nxt = self.get_responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def _forbidden(self, *args, **kwargs):
        raise AssertionError("HQ must never write to Zoho Books")

    put = patch = delete = _forbidden


def token_ok(value="tok-1", expires_in=3600):
    return FakeResponse(200, {"access_token": value, "expires_in": expires_in,
                              "token_type": "Bearer"})


def contacts_page(rows, has_more):
    return FakeResponse(200, {"code": 0, "message": "success", "contacts": rows,
                              "page_context": {"page": 1, "per_page": 200,
                                               "has_more_page": has_more}})


class ZohoTestCase(unittest.TestCase):
    """Restores the module's global state so tests cannot leak into each other."""

    ENV = ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN",
           "ZOHO_ORG_ID", "ZOHO_DC")

    def setUp(self):
        self._saved_env = {k: os.environ.get(k) for k in self.ENV}
        self._saved_session = zoho._SESSION
        self._saved_backoff = zoho._BACKOFF_SECONDS
        self._saved_max_pages = zoho._MAX_PAGES
        for key in self.ENV:
            os.environ.pop(key, None)
        zoho._forget_token()
        # Retries must be exercised, not waited out.
        zoho._BACKOFF_SECONDS = (0.0, 0.0)

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        zoho._SESSION = self._saved_session
        zoho._BACKOFF_SECONDS = self._saved_backoff
        zoho._MAX_PAGES = self._saved_max_pages
        zoho._forget_token()

    def configure(self, session):
        os.environ["ZOHO_CLIENT_ID"] = "1000.FAKECLIENTID"
        os.environ["ZOHO_CLIENT_SECRET"] = "fake-secret"
        os.environ["ZOHO_REFRESH_TOKEN"] = "1000.fake-refresh-token"
        zoho._SESSION = session
        return session


# ── configuration ───────────────────────────────────────────────────────────

class ConfigTests(ZohoTestCase):

    def test_not_configured_raises_a_helpful_error(self):
        session = self.configure(FakeSession())
        for key in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN"):
            os.environ.pop(key, None)

        self.assertFalse(zoho.is_configured())
        with self.assertRaises(zoho.ZohoError) as caught:
            zoho.list_contacts()
        message = str(caught.exception)

        for expected in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN",
                         "Self Client", "api-console.zoho.in",
                         # The scopes Zoho actually documents. "fullaccess.READ"
                         # is not a real scope — the console rejects it — so the
                         # hint must not send an operator chasing it.
                         "ZohoBooks.contacts.READ", "ZohoBooks.invoices.READ"):
            self.assertIn(expected, message)
        # It must name the read-only requirement, not merely a scope string,
        # and must warn off the write-capable blanket scope.
        self.assertIn("must never be able to write", message)
        self.assertIn("Do NOT use ZohoBooks.fullaccess.all", message)
        # Nothing should have been attempted over the wire.
        self.assertEqual(session.gets, [])
        self.assertEqual(session.posts, [])

    def test_status_reports_not_configured_without_touching_the_network(self):
        session = self.configure(FakeSession())
        os.environ.pop("ZOHO_REFRESH_TOKEN", None)

        state = zoho.status()
        self.assertEqual(state["state"], "not configured")
        self.assertFalse(state["configured"])
        self.assertEqual(state["organisation_id"], "60078183686")
        self.assertEqual(state["data_centre"], "in")
        self.assertIn("ZOHO_REFRESH_TOKEN", state["detail"])
        self.assertEqual(session.posts, [])

    def test_status_reports_connected_and_carries_the_last_sync(self):
        self.configure(FakeSession(token=[token_ok()]))
        state = zoho.status(last_sync="2026-07-26T09:15:00Z")
        self.assertEqual(state["state"], "connected")
        self.assertTrue(state["configured"])
        self.assertEqual(state["last_sync"], "2026-07-26T09:15:00Z")

    def test_status_reports_error_rather_than_raising(self):
        # Zoho answers a dead refresh token with HTTP 200 and an "error" key.
        self.configure(FakeSession(token=[FakeResponse(200, {"error": "invalid_code"})]))
        state = zoho.status()
        self.assertEqual(state["state"], "error")
        self.assertIn("invalid_code", state["detail"])

    def test_data_centre_drives_both_hostnames(self):
        session = self.configure(FakeSession(token=[token_ok()],
                                             gets=[contacts_page([], False)]))
        os.environ["ZOHO_DC"] = ".eu"  # leading dot is the obvious typo
        os.environ["ZOHO_ORG_ID"] = "99999"
        zoho.list_contacts()
        self.assertEqual(session.posts[0]["url"], "https://accounts.zoho.eu/oauth/v2/token")
        self.assertEqual(session.gets[0]["url"], "https://www.zohoapis.eu/books/v3/contacts")
        self.assertEqual(session.gets[0]["params"]["organization_id"], "99999")


# ── OAuth ───────────────────────────────────────────────────────────────────

class TokenTests(ZohoTestCase):

    def test_the_token_is_cached_across_calls(self):
        session = self.configure(FakeSession(
            token=[token_ok()],
            gets=[contacts_page([], False), contacts_page([], False)],
        ))
        zoho.list_contacts()
        zoho.list_contacts()
        self.assertEqual(len(session.posts), 1, "refreshed on every call")
        self.assertEqual(len(session.gets), 2)

    def test_an_expiring_token_is_refreshed(self):
        session = self.configure(FakeSession(
            # expires_in below the safety margin means it is already stale.
            token=[token_ok("tok-1", expires_in=10), token_ok("tok-2", expires_in=3600)],
            gets=[contacts_page([], False), contacts_page([], False)],
        ))
        zoho.list_contacts()
        zoho.list_contacts()
        self.assertEqual(len(session.posts), 2)
        self.assertEqual(session.gets[1]["headers"]["Authorization"], "Zoho-oauthtoken tok-2")

    def test_the_secret_never_travels_in_the_query_string(self):
        session = self.configure(FakeSession(token=[token_ok()],
                                             gets=[contacts_page([], False)]))
        zoho.list_contacts()
        post = session.posts[0]
        self.assertNotIn("?", post["url"])
        self.assertEqual(post["data"]["grant_type"], "refresh_token")
        self.assertEqual(post["data"]["client_secret"], "fake-secret")
        self.assertIsNotNone(post["timeout"])


# ── pagination ──────────────────────────────────────────────────────────────

class PaginationTests(ZohoTestCase):

    def test_pagination_walks_every_page(self):
        session = self.configure(FakeSession(token=[token_ok()], gets=[
            contacts_page([
                {"contact_id": "1", "contact_name": "A", "contact_type": "customer"},
                {"contact_id": "2", "contact_name": "B", "contact_type": "customer"},
            ], True),
            contacts_page([
                {"contact_id": "3", "contact_name": "C", "contact_type": "customer"},
                {"contact_id": "4", "contact_name": "A Supplier", "contact_type": "vendor"},
            ], True),
            contacts_page([
                {"contact_id": "5", "contact_name": "D", "contact_type": "customer"},
            ], False),
        ]))

        rows = zoho.list_contacts()

        self.assertEqual([r["contact_id"] for r in rows], ["1", "2", "3", "5"],
                         "later pages were dropped, or the vendor was kept")
        self.assertEqual(len(session.gets), 3)
        self.assertEqual([g["params"]["page"] for g in session.gets], [1, 2, 3])
        for get in session.gets:
            self.assertEqual(get["params"]["per_page"], 200)
            self.assertEqual(get["params"]["organization_id"], "60078183686")
            self.assertEqual(get["headers"]["Authorization"], "Zoho-oauthtoken tok-1")
            self.assertIsNotNone(get["timeout"])

    def test_pagination_stops_at_the_cap_instead_of_looping(self):
        zoho._MAX_PAGES = 2
        session = self.configure(FakeSession(token=[token_ok()], gets=[
            contacts_page([{"contact_id": "1", "contact_name": "A"}], True),
            contacts_page([{"contact_id": "2", "contact_name": "B"}], True),
        ]))
        rows = zoho.list_contacts()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(session.gets), 2, "ignored the page cap")

    def test_a_missing_has_more_page_flag_ends_the_walk(self):
        session = self.configure(FakeSession(token=[token_ok()], gets=[
            FakeResponse(200, {"contacts": [{"contact_id": "1", "contact_name": "A"}]}),
        ]))
        self.assertEqual(len(zoho.list_contacts()), 1)
        self.assertEqual(len(session.gets), 1)

    def test_invoices_are_shaped_and_amounts_coerced(self):
        self.configure(FakeSession(token=[token_ok()], gets=[
            FakeResponse(200, {"invoices": [{
                "invoice_id": "INV1", "invoice_number": "Z0/26-27/009",
                "customer_id": "C1", "customer_name": "BELLWAY CONSULTING",
                "date": "2026-07-16", "due_date": "2026-07-23",
                "status": "sent", "total": "47200.00", "balance": 47200,
                "currency_code": "INR", "unexpected_new_field": "ignored",
            }, {
                "invoice_id": "INV2",  # every other field absent on purpose
            }], "page_context": {"has_more_page": False}}),
        ]))
        rows = zoho.list_invoices()
        self.assertEqual(rows[0]["invoice_number"], "Z0/26-27/009")
        self.assertEqual(rows[0]["total"], 47200.0)
        self.assertEqual(rows[0]["balance"], 47200.0)
        self.assertNotIn("unexpected_new_field", rows[0])
        # A sparse row must degrade to None, never raise.
        self.assertIsNone(rows[1]["total"])
        self.assertIsNone(rows[1]["customer_name"])


# ── robustness ──────────────────────────────────────────────────────────────

class RetryTests(ZohoTestCase):

    def test_a_401_refreshes_once_and_retries_once_then_gives_up(self):
        session = self.configure(FakeSession(
            token=[token_ok("tok-1"), token_ok("tok-2"), token_ok("tok-3")],
            gets=[FakeResponse(401, {"code": 57, "message": "Invalid oauth token"}),
                  FakeResponse(401, {"code": 57, "message": "Invalid oauth token"}),
                  FakeResponse(401, {"code": 57, "message": "Invalid oauth token"})],
        ))
        with self.assertRaises(zoho.ZohoError) as caught:
            zoho.list_contacts()

        self.assertEqual(len(session.gets), 2, "did not stop after one retry")
        self.assertEqual(len(session.posts), 2, "refreshed more than once")
        self.assertIn("even after refreshing", str(caught.exception))

    def test_a_401_from_an_expired_token_recovers(self):
        session = self.configure(FakeSession(
            token=[token_ok("tok-1"), token_ok("tok-2")],
            gets=[FakeResponse(401, {"code": 57, "message": "Invalid oauth token"}),
                  contacts_page([{"contact_id": "1", "contact_name": "A"}], False)],
        ))
        rows = zoho.list_contacts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(session.gets), 2)
        self.assertEqual(session.gets[1]["headers"]["Authorization"], "Zoho-oauthtoken tok-2")

    def test_a_429_is_retried_at_most_twice(self):
        throttled = FakeResponse(429, {"code": 44, "message": "too many requests"})
        session = self.configure(FakeSession(
            token=[token_ok()],
            gets=[throttled, throttled, throttled],
        ))
        with self.assertRaises(zoho.ZohoError) as caught:
            zoho.list_contacts()

        self.assertEqual(len(session.gets), 3, "expected the first call plus two retries")
        self.assertIn("rate-limiting", str(caught.exception))

    def test_a_429_that_clears_is_not_an_error(self):
        session = self.configure(FakeSession(token=[token_ok()], gets=[
            FakeResponse(429, {"code": 44, "message": "too many requests"}),
            contacts_page([{"contact_id": "1", "contact_name": "A"}], False),
        ]))
        self.assertEqual(len(zoho.list_contacts()), 1)
        self.assertEqual(len(session.gets), 2)

    def test_retry_after_is_honoured_when_present(self):
        with_header = FakeResponse(429, headers={"Retry-After": "7"})
        self.assertEqual(zoho._retry_delay(with_header, 1), 7.0)
        # Capped, so a hostile or silly header cannot park a worker for an hour.
        self.assertEqual(zoho._retry_delay(FakeResponse(429, headers={"Retry-After": "99999"}), 1),
                         zoho._MAX_RETRY_AFTER)
        # Absent or unparseable falls back to the backoff schedule.
        zoho._BACKOFF_SECONDS = (5.0, 15.0)
        self.assertEqual(zoho._retry_delay(FakeResponse(429), 1), 5.0)
        self.assertEqual(zoho._retry_delay(FakeResponse(429), 2), 15.0)
        self.assertEqual(zoho._retry_delay(FakeResponse(429, headers={"Retry-After": "Wed, 21 Oct"}), 1),
                         5.0)

    def test_a_network_failure_never_escapes_as_a_requests_exception(self):
        self.configure(FakeSession(
            token=[token_ok()],
            gets=[requests.ConnectionError("connection reset by peer")],
        ))
        with self.assertRaises(zoho.ZohoError) as caught:
            zoho.list_contacts()
        self.assertIn("Could not reach Zoho Books", str(caught.exception))

    def test_an_unreachable_oauth_service_becomes_a_zoho_error(self):
        self.configure(FakeSession(token=[requests.Timeout("timed out")]))
        with self.assertRaises(zoho.ZohoError) as caught:
            zoho.list_contacts()
        self.assertIn("OAuth", str(caught.exception))

    def test_a_server_error_reports_zohos_own_message(self):
        self.configure(FakeSession(token=[token_ok()], gets=[
            FakeResponse(500, {"code": 1000, "message": "Internal error"}),
        ]))
        with self.assertRaises(zoho.ZohoError) as caught:
            zoho.list_contacts()
        self.assertIn("Internal error", str(caught.exception))

    def test_an_html_error_page_becomes_a_zoho_error(self):
        self.configure(FakeSession(token=[token_ok()], gets=[
            FakeResponse(200, None, text="<html>gateway timeout</html>"),
        ]))
        with self.assertRaises(zoho.ZohoError) as caught:
            zoho.list_contacts()
        self.assertIn("non-JSON", str(caught.exception))


# ── matching, on the real ZeroOne data ──────────────────────────────────────

# Verbatim from the Zoho Books org and from HQ. The pairs that matter are the
# ones no algorithm can get: Zoho's "GOA TRADING & TECHNICAL SERVICES" is HQ's
# "Michael Bhai", and "KAJAL PARAG TELI" is HQ's "Parag Kaka". Both are correct
# in the real world and unknowable from the strings.
ZOHO_CONTACTS = [
    {"contact_id": "z1", "contact_name": "NEO NIR ENGINEERING LLP", "email": "hemish@neonir.com"},
    {"contact_id": "z2", "contact_name": "Feed Aqua Engineering Private Limited",
     "email": "ajaysingh@feedaqua.com"},
    {"contact_id": "z3", "contact_name": "Microchem Enterprises", "email": None},
    {"contact_id": "z4", "contact_name": "OM Enterprises", "email": None},
    {"contact_id": "z5", "contact_name": "PIONEER ENGINEERING", "email": None},
    {"contact_id": "z6", "contact_name": "Water Whizz", "email": None},
    {"contact_id": "z7", "contact_name": "GOA TRADING & TECHNICAL SERVICES",
     "email": "michael.martins@gtandts.com"},
    {"contact_id": "z8", "contact_name": "KAJAL PARAG TELI", "email": "parag_teli@yahoo.com"},
    {"contact_id": "z9", "contact_name": "S P Chemicals", "email": None},
    {"contact_id": "z10", "contact_name": "BELLWAY CONSULTING", "email": None},
]

HQ_CUSTOMERS = [
    {"id": 1, "display_name": "NeoNir Engineering", "email": "hemish@neonir.com"},
    {"id": 2, "display_name": "Pioneer Engineering", "email": None},
    {"id": 3, "display_name": "FeedAqua", "email": None},
    {"id": 4, "display_name": "Micro Chem", "email": None},
    {"id": 5, "display_name": "Om Enterprises", "email": None},
    {"id": 6, "display_name": "Water Whizz", "email": None},
    {"id": 7, "display_name": "Michael Bhai", "email": None},
    {"id": 8, "display_name": "Parag Kaka", "email": None},
    {"id": 9, "display_name": "Aditya Electric", "email": None},
    {"id": 10, "display_name": "Krishna Global Transenergy", "email": None},
]


class MatchTests(unittest.TestCase):

    def setUp(self):
        self.proposals = zoho.match_contacts(ZOHO_CONTACTS, HQ_CUSTOMERS)
        self.by_zoho = {p["zoho_contact_id"]: p for p in self.proposals}

    def confidence_for(self, zoho_id):
        found = self.by_zoho.get(zoho_id)
        return found["confidence"] if found else None

    def test_an_email_match_is_the_only_thing_called_exact(self):
        neonir = self.by_zoho["z1"]
        self.assertEqual(neonir["confidence"], "exact")
        self.assertEqual(neonir["hq_customer_id"], 1)
        self.assertIn("email", neonir["reason"])
        exact = [p for p in self.proposals if p["confidence"] == "exact"]
        self.assertEqual([p["zoho_contact_id"] for p in exact], ["z1"])

    def test_the_obvious_ones_match(self):
        expected = {
            "z1": 1,   # NEO NIR ENGINEERING LLP     -> NeoNir Engineering
            "z2": 3,   # Feed Aqua Engineering P Ltd -> FeedAqua
            "z3": 4,   # Microchem Enterprises       -> Micro Chem
            "z4": 5,   # OM Enterprises              -> Om Enterprises
            "z5": 2,   # PIONEER ENGINEERING         -> Pioneer Engineering
            "z6": 6,   # Water Whizz                 -> Water Whizz
        }
        for zoho_id, hq_id in expected.items():
            proposal = self.by_zoho.get(zoho_id)
            self.assertIsNotNone(proposal, "no proposal for %s" % zoho_id)
            self.assertEqual(proposal["hq_customer_id"], hq_id,
                             "%s matched %r" % (zoho_id, proposal["hq_name"]))
            self.assertIn(proposal["confidence"], ("exact", "likely"),
                          "%s came back only as %s" % (zoho_id, proposal["confidence"]))

    def test_michael_bhai_is_never_claimed(self):
        # "GOA TRADING & TECHNICAL SERVICES" really is Michael Bhai. Nothing in
        # the two strings says so, and inventing the link would be a fabrication.
        for proposal in self.proposals:
            self.assertNotEqual(proposal["hq_name"], "Michael Bhai",
                                "fabricated a %s match for Michael Bhai: %s"
                                % (proposal["confidence"], proposal["reason"]))
        self.assertIsNone(self.confidence_for("z7"))

    def test_parag_kaka_is_at_best_a_weak_suggestion(self):
        # "KAJAL PARAG TELI" shares one word, which is worth showing a human and
        # worth nothing at all as an automatic link.
        for proposal in self.proposals:
            if proposal["hq_name"] == "Parag Kaka":
                self.assertEqual(proposal["confidence"], "weak", proposal["reason"])
        self.assertIn(self.confidence_for("z8"), (None, "weak"))

    def test_unknown_contacts_are_left_alone(self):
        for zoho_id in ("z9", "z10"):  # S P Chemicals, BELLWAY CONSULTING
            self.assertIsNone(self.confidence_for(zoho_id))
        matched_hq = {p["hq_customer_id"] for p in self.proposals}
        self.assertNotIn(9, matched_hq)   # Aditya Electric
        self.assertNotIn(10, matched_hq)  # Krishna Global Transenergy

    def test_nothing_is_proposed_twice(self):
        zoho_ids = [p["zoho_contact_id"] for p in self.proposals]
        hq_ids = [p["hq_customer_id"] for p in self.proposals]
        self.assertEqual(len(zoho_ids), len(set(zoho_ids)))
        self.assertEqual(len(hq_ids), len(set(hq_ids)))

    def test_every_proposal_carries_a_readable_reason(self):
        for proposal in self.proposals:
            self.assertIn(proposal["confidence"], ("exact", "likely", "weak"))
            self.assertTrue(proposal["reason"].strip())
            self.assertEqual(
                set(proposal),
                {"zoho_contact_id", "zoho_name", "hq_customer_id", "hq_name",
                 "confidence", "reason"},
            )

    def test_empty_inputs_are_not_an_error(self):
        self.assertEqual(zoho.match_contacts([], HQ_CUSTOMERS), [])
        self.assertEqual(zoho.match_contacts(ZOHO_CONTACTS, []), [])
        self.assertEqual(zoho.match_contacts(None, None), [])

    def test_blank_names_and_emails_never_match_each_other(self):
        blanks = zoho.match_contacts(
            [{"contact_id": "zx", "contact_name": "", "company_name": "", "email": ""}],
            [{"id": 99, "display_name": "", "email": ""}],
        )
        self.assertEqual(blanks, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
