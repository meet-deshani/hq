#!/usr/bin/env python3
"""WhatsApp groups, offline. Every request faked; nothing is ever sent.

A client is rarely only a DM — the work usually happens in a group with their
people and ours in it. Two things had to be got right, and both fail silently
rather than loudly, which is why they are tested here rather than trusted.

1. A GROUP ID IS NOT A PHONE NUMBER. `comms._digits` reduces any string to its
   last ten digits, so "120363428659623387@g.us" becomes "3659623387" — a
   plausible-looking subscriber number that would file the group under a fake
   contact and could collide with a real one.

2. A GROUP MESSAGE MUST GO TO THE GROUP. `dial_address` walks the linked
   contact's number first, so on a group thread it would have returned one
   person's number and delivered a message meant for everybody privately to
   them. That is the same class of mistake as dialling a stranger who shares a
   subscriber number, and just as unrecoverable once sent.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "wa-groups-test-only")

from backend import comms, whatsapp  # noqa: E402

failures = []
GROUP = "120363428659623387@g.us"


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (label, got, want))
        failures.append(label)


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.ok = 200 <= status < 300

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        for frag, resp in self.script.items():
            if frag in url:
                return resp
        raise AssertionError("unscripted GET %s" % url)


class FakeConversation:
    def __init__(self, identifier, party=None, contact_id=None):
        self.contact_identifier = identifier
        self.party = party
        self.party_contact_id = contact_id


def test_a_group_id_survives_normalisation():
    check("recognised as a group", comms.is_group(GROUP), True)
    check("a phone number is not", comms.is_group("+91-9825115308"), False)
    # THE trap: without the guard this returns "3659623387".
    check("kept whole, not reduced to ten digits",
          comms._normalise(GROUP, "whatsapp"), GROUP)
    check("a real number is still reduced",
          comms._normalise("+91-98251 15308", "whatsapp"), "9825115308")
    check("case is normalised so one group is one thread",
          comms._normalise(GROUP.upper(), "whatsapp"), GROUP)


def test_a_group_message_is_addressed_to_the_group():
    convo = FakeConversation(GROUP, party=None, contact_id=None)
    check("dial_address returns the group id", whatsapp.dial_address(None, convo), GROUP)

    # ...even when a contact IS linked — the walk must not win here.
    class Party:
        phone = "+919999999999"
    convo2 = FakeConversation(GROUP, party=Party(), contact_id=None)
    got = whatsapp.dial_address(None, convo2)
    check("a linked customer's number never hijacks a group thread", got, GROUP)
    check("and it is definitely not that person's number", got == "919999999999", False)


def test_membership_matches_on_phone_not_internal_id():
    """The bot reports two identifiers per member; only one is a phone number."""
    os.environ["WHATSAPP_BOT_API_TOKEN"] = "fake-token"
    whatsapp._ROSTER.update({"at": 0, "groups": None})

    listing = FakeResponse(200, {"groups": [
        {"id": GROUP, "subject": "NeoNir x ZeroOne"},
        {"id": "999@g.us", "subject": "Somebody Else"},
    ]})
    info = FakeResponse(200, {"group": {"participants": [
        # `id` is a WhatsApp-internal @lid, NOT a phone number. Matching on it
        # would never hit, and the customer would appear to be in no groups.
        {"id": "116479563415771@lid", "phoneNumber": "919825115308@s.whatsapp.net"},
        {"id": "220000000000000@lid", "phoneNumber": "917567838028@s.whatsapp.net"},
    ]}})
    empty = FakeResponse(200, {"group": {"participants": []}})

    fake = FakeSession({"/api/group/list": listing,
                        "/api/group/info/" + GROUP: info,
                        "/api/group/info/999@g.us": empty})
    real, whatsapp._SESSION = whatsapp._SESSION, fake
    try:
        got = whatsapp.groups_for("+91-98251 15308")
        check("finds the group the customer is actually in",
              [g["subject"] for g in got], ["NeoNir x ZeroOne"])
        check("and not the one they are not", len(got), 1)

        # A second customer, answered from cache — no further requests.
        before = len(fake.calls)
        other = whatsapp.groups_for("7567838028")
        check("the other member is found too",
              [g["subject"] for g in other], ["NeoNir x ZeroOne"])
        check("answered from cache, not re-fetched", len(fake.calls), before)

        check("a stranger is in no groups", whatsapp.groups_for("+91-9000000000"), [])
        check("a blank number is in no groups", whatsapp.groups_for(""), [])
    finally:
        whatsapp._SESSION = real
        whatsapp._ROSTER.update({"at": 0, "groups": None})
        os.environ.pop("WHATSAPP_BOT_API_TOKEN", None)


def test_a_broken_bot_never_breaks_a_customer_page():
    os.environ["WHATSAPP_BOT_API_TOKEN"] = "fake-token"
    whatsapp._ROSTER.update({"at": 0, "groups": None})
    fake = FakeSession({"/api/group/list": FakeResponse(503, {})})
    real, whatsapp._SESSION = whatsapp._SESSION, fake
    try:
        check("a bot that will not answer yields no groups, not an error",
              whatsapp.groups_for("9825115308"), [])
    finally:
        whatsapp._SESSION = real
        whatsapp._ROSTER.update({"at": 0, "groups": None})
        os.environ.pop("WHATSAPP_BOT_API_TOKEN", None)

    check("and neither does an unconfigured one", whatsapp.groups_for("9825115308"), [])


TESTS = [
    ("a group id survives normalisation", test_a_group_id_survives_normalisation),
    ("a group message is addressed to the group", test_a_group_message_is_addressed_to_the_group),
    ("membership matches on phone, not internal id", test_membership_matches_on_phone_not_internal_id),
    ("a broken bot never breaks a customer page", test_a_broken_bot_never_breaks_a_customer_page),
]

if __name__ == "__main__":
    print("WhatsApp groups")
    for label, fn in TESTS:
        print("\n%s" % label)
        fn()
    print("\n%s" % ("-" * 58))
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("all green")
