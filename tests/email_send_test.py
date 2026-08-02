#!/usr/bin/env python3
"""Outbound email through Resend, offline.

Every request is faked. Nothing here may reach the network, and above all
nothing may deliver a message — see the `tests-must-not-message-real-people`
lesson: the smoke suite once WhatsApp'd a real client the day sending was wired.

The case worth protecting is the send-only key. Resend issues keys with
"sending access" that can post an email and are refused everything else,
including listing domains — and that is the key HQ actually holds. Reading that
refusal as a dead integration puts a red light next to a key that authenticates
fine; calling it "connected" puts a green one next to an integration that 403s
every send. Both are lies, so it reports "unverified" and says what to do.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "email-test-only")

from backend import email_send  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (label, got, want))
        failures.append(label)


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.ok = 200 <= status < 300

    def json(self):
        return self._payload


class FakeSession:
    """Records what was asked of it and answers from a script."""

    def __init__(self, script):
        self.script = script          # (method, path-suffix) -> FakeResponse
        self.calls = []

    def _answer(self, method, url, **kw):
        self.calls.append((method, url, kw.get("json")))
        for (m, suffix), resp in self.script.items():
            if m == method and url.endswith(suffix):
                return resp
        raise AssertionError("unscripted %s %s" % (method, url))

    def get(self, url, **kw):
        return self._answer("GET", url, **kw)

    def post(self, url, **kw):
        return self._answer("POST", url, **kw)


def with_env(**kw):
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_unconfigured_is_honest():
    with_env(RESEND_API_KEY=None)
    check("not configured", email_send.is_configured(), False)
    st = email_send.status()
    check("state says so", st["state"], "not configured")
    check("and explains how to fix it", "RESEND_API_KEY" in (st["detail"] or ""), True)

    try:
        email_send.send_email("someone@example.invalid", "s", "b")
        check("sending without a key raises", True, False)
    except email_send.EmailError as exc:
        check("sending without a key raises", "not configured" in str(exc), True)


def test_send_only_key_reads_as_unverified():
    """The regression this file exists for."""
    with_env(RESEND_API_KEY="re_sendonly_fake", EMAIL_FROM="hello@dotsai.in")
    fake = FakeSession({
        ("GET", "/domains"): FakeResponse(401, {"message": "restricted"}),
        ("POST", "/emails"): FakeResponse(422, {"name": "missing_required_field"}),
    })
    real, email_send._SESSION = email_send._SESSION, fake
    try:
        st = email_send.status()
    finally:
        email_send._SESSION = real

    # Not "connected": auth is proven, delivery is not. Resend checks the
    # recipient before the sending domain, so a probe naming nobody can never
    # reach the domain check — and this exact key 403s every real send because
    # dotsai.in is unverified in its account.
    check("a send-only key is UNVERIFIED, not connected", st["state"], "unverified")
    check("and not an error either", st["state"] != "error", True)
    check("and says the sends will 403 until the domain is verified",
          "403" in (st["detail"] or ""), True)
    # The probe must be incapable of delivering anything.
    probe = [c for c in fake.calls if c[0] == "POST"]
    check("the probe posted exactly once", len(probe), 1)
    check("the probe named NO recipient", probe[0][2], {})


def test_a_genuinely_bad_key_still_errors():
    with_env(RESEND_API_KEY="re_revoked_fake", EMAIL_FROM="hello@dotsai.in")
    fake = FakeSession({
        ("GET", "/domains"): FakeResponse(401, {}),
        ("POST", "/emails"): FakeResponse(401, {}),
    })
    real, email_send._SESSION = email_send._SESSION, fake
    try:
        st = email_send.status()
    finally:
        email_send._SESSION = real
    check("a revoked key is an error", st["state"], "error")
    check("named as a key problem", "API key" in (st["detail"] or ""), True)


def test_full_access_key_checks_the_domain():
    with_env(RESEND_API_KEY="re_full_fake", EMAIL_FROM="hello@dotsai.in")
    fake = FakeSession({("GET", "/domains"): FakeResponse(
        200, {"data": [{"name": "dotsai.in", "status": "verified"}]})})
    real, email_send._SESSION = email_send._SESSION, fake
    try:
        st = email_send.status()
    finally:
        email_send._SESSION = real
    check("verified sending domain -> connected", st["state"], "connected")

    # ...and an unverified one is caught before a customer sees a bounce.
    fake2 = FakeSession({("GET", "/domains"): FakeResponse(
        200, {"data": [{"name": "somewhere-else.com", "status": "verified"}]})})
    real, email_send._SESSION = email_send._SESSION, fake2
    try:
        st2 = email_send.status()
    finally:
        email_send._SESSION = real
    check("wrong sending domain -> error", st2["state"], "error")
    check("and names the domain", "dotsai.in" in (st2["detail"] or ""), True)


def test_a_bad_address_never_reaches_the_network():
    with_env(RESEND_API_KEY="re_full_fake", EMAIL_FROM="hello@dotsai.in")
    fake = FakeSession({})          # any call at all would raise
    real, email_send._SESSION = email_send._SESSION, fake
    try:
        for bad in ("", "   ", "not-an-address", "a@b", "two@@at.com"):
            try:
                email_send.send_email(bad, "s", "b")
                failures.append("accepted %r" % bad)
                print("  FAIL accepted a bad address %r" % bad)
            except email_send.EmailError:
                pass
    finally:
        email_send._SESSION = real
    check("no request was made for any bad address", len(fake.calls), 0)


def test_send_reports_only_what_it_got():
    with_env(RESEND_API_KEY="re_full_fake", EMAIL_FROM="hello@dotsai.in")

    ok = FakeSession({("POST", "/emails"): FakeResponse(200, {"id": "abc-123"})})
    real, email_send._SESSION = email_send._SESSION, ok
    try:
        check("a good send returns the provider id",
              email_send.send_email("x@example.com", "Hi", "Body"), "abc-123")
        check("it was sent as text, never HTML", "html" in (ok.calls[0][2] or {}), False)
    finally:
        email_send._SESSION = real

    # 403 must NOT be reported as a key problem: it is an unverified sending
    # domain, and blaming the key sends an operator hunting a good key.
    for status, fragment in ((401, "API key"), (403, "not verified"),
                             (422, "could not process"),
                             (429, "rate-limiting"), (500, "refused")):
        payload = ({"message": "The dotsai.in domain is not verified."}
                   if status == 403 else {})
        bad = FakeSession({("POST", "/emails"): FakeResponse(status, payload)})
        real, email_send._SESSION = email_send._SESSION, bad
        try:
            email_send.send_email("x@example.com", "Hi", "Body")
            check("HTTP %s raises" % status, True, False)
        except email_send.EmailError as exc:
            check("HTTP %s raises and explains" % status, fragment in str(exc), True)
        finally:
            email_send._SESSION = real


TESTS = [
    ("unconfigured is honest", test_unconfigured_is_honest),
    ("a send-only key reads as unverified", test_send_only_key_reads_as_unverified),
    ("a genuinely bad key still errors", test_a_genuinely_bad_key_still_errors),
    ("a full-access key checks the domain", test_full_access_key_checks_the_domain),
    ("a bad address never reaches the network", test_a_bad_address_never_reaches_the_network),
    ("send reports only what it got", test_send_reports_only_what_it_got),
]

if __name__ == "__main__":
    print("outbound email (Resend)")
    for label, fn in TESTS:
        print("\n%s" % label)
        fn()
    print("\n%s" % ("-" * 58))
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("all green")
