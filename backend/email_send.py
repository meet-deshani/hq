"""Outbound email through Resend.

Deliberately the same shape as ``backend/whatsapp.py``, because it makes the
same promise: HQ records every outbound message either way, and what this module
decides is whether that record is allowed to claim the client actually received
it.

Three outcomes, and the thread always says which one happened:

  ``sent``      Resend accepted the message and returned its own id
  ``failed``    Resend refused it, or could not be reached
  ``recorded``  no API key is configured — HQ logged the text, nothing was sent

Before this existed, sending on the seeded Email channel did the third thing
while *saying nothing at all*: the reply route had no email branch, so the API
answered ``delivered: false, detail: null`` and the thread showed a message that
looked posted and had never left the building. A thread that lies about delivery
is worse than one that admits it did nothing.

One asymmetry with WhatsApp worth stating plainly: **replies do not come back
yet.** Resend can post inbound mail to a webhook, and HQ already has the
endpoint to receive it (``POST /api/comms/inbound``), but nothing is wired
between them. Until it is, an email thread in HQ is one-sided — what we sent,
not what they said.
"""

import logging
import os
import re

import requests

logger = logging.getLogger("email_send")

_DEFAULT_URL = "https://api.resend.com"
_TIMEOUT = 20

# One host, many messages — TLS handshakes are not free.
_SESSION = requests.Session()

SETUP_HINT = (
    "Set RESEND_API_KEY in the server environment (and EMAIL_FROM to the address "
    "mail should come from — it must be on a domain verified in Resend). The key "
    "is created at https://resend.com/api-keys and only needs send permission."
)

# Good enough to catch a typo'd or empty address before it costs a round trip.
# Deliberately not RFC 5322 — that regex is famously unreadable and rejecting a
# genuinely valid oddity is worse here than letting Resend have the final say.
_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailError(Exception):
    """A send that did not happen, in words an operator can act on."""


def _env(name, default=None):
    value = (os.getenv(name) or "").strip()
    return value or default


def _config():
    """Read the environment on every use, so status reflects reality now."""
    return {
        "url": (_env("RESEND_API_URL", _DEFAULT_URL) or _DEFAULT_URL).rstrip("/"),
        "key": _env("RESEND_API_KEY"),
        "from": _env("EMAIL_FROM", "hello@dotsai.in"),
    }


def is_configured():
    """True when HQ has a key to send with."""
    return bool(_config()["key"])


def valid_address(value):
    return bool(_ADDRESS.match((value or "").strip()))


def mail_address(db, conversation):
    """The address for a thread, or None if there is nothing sendable on file.

    The email twin of ``whatsapp.dial_address``, and easier than its WhatsApp
    counterpart for one reason: ``comms._normalise`` keeps an email identifier
    whole, where it truncates a phone number to ten digits. So the thread's own
    identifier is usually already the answer.

    Preference still runs from most to least trustworthy — the linked contact,
    then the linked customer, then the thread identifier — because a thread can
    outlive the address it started on, and the contact record is what somebody
    maintains.
    """
    from backend.crm_models import PartyContact

    candidates = []
    if conversation.party_contact_id:
        contact = db.query(PartyContact).filter(
            PartyContact.id == conversation.party_contact_id
        ).first()
        if contact:
            candidates.append(contact.email)
    if conversation.party is not None:
        candidates.append(conversation.party.email)
    candidates.append(conversation.contact_identifier)

    for candidate in candidates:
        if valid_address(candidate):
            return (candidate or "").strip()
    return None


def send_email(to, subject, body, reply_to=None):
    """Hand one message to Resend. Returns the provider's message id.

    Raises EmailError whenever the message did not go out, for any reason at
    all. The caller records that failure against the thread; nothing here ever
    reports a success it did not get.
    """
    config = _config()
    if not config["key"]:
        raise EmailError("Email sending is not configured. " + SETUP_HINT)

    to = (to or "").strip()
    if not valid_address(to):
        raise EmailError(
            "%r is not an email address HQ can send to. Add a valid address to "
            "the contact and send again." % (to or "")
        )

    payload = {
        "from": config["from"],
        "to": [to],
        "subject": (subject or "").strip() or "(no subject)",
        # Sent as text, not HTML: everything HQ composes is plain typing, and
        # interpolating it into a template is how a stray angle bracket in a
        # customer's name becomes broken markup in their inbox.
        "text": body or "",
    }
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        response = _SESSION.post(
            config["url"] + "/emails",
            headers={"Authorization": "Bearer %s" % config["key"]},
            json=payload,
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise EmailError("Could not reach Resend at %s: %s" % (config["url"], exc))

    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.status_code in (401, 403):
        raise EmailError(
            "Resend rejected HQ's API key. Check RESEND_API_KEY is current and "
            "has send permission."
        )
    if response.status_code == 422:
        # Nearly always an unverified sending domain, and the raw message says
        # so much better than anything invented here.
        raise EmailError(
            "Resend refused the message: %s (is %s on a domain verified in "
            "Resend?)" % (data.get("message") or "unprocessable", config["from"])
        )
    if response.status_code == 429:
        raise EmailError("Resend is rate-limiting HQ. The message was not sent — try again shortly.")
    if not response.ok:
        raise EmailError(
            "Resend refused the message: %s"
            % (data.get("message") or data.get("error") or "HTTP %s" % response.status_code)
        )

    message_id = data.get("id")
    if not message_id:
        # Accepted, but unidentifiable — same reasoning as whatsapp.send_text:
        # it did go out, but without the provider's id a delivery or reply echo
        # cannot be recognised as this message.
        logger.warning("Resend accepted a message but returned no id")
    return message_id


def status():
    """A small dict the UI can render without knowing anything about Resend."""
    config = _config()
    out = {
        "configured": is_configured(),
        "state": "not configured",
        "from": config["from"],
        "detail": None,
    }
    if not out["configured"]:
        out["detail"] = SETUP_HINT
        return out
    try:
        # Listing domains is the cheapest authenticated call that proves both
        # that the key works and that a sending domain exists. It sends nothing.
        response = _SESSION.get(
            config["url"] + "/domains",
            headers={"Authorization": "Bearer %s" % config["key"]},
            timeout=_TIMEOUT,
        )
        if response.status_code in (401, 403):
            out["state"] = "error"
            out["detail"] = ("Resend rejected HQ's API key. Check RESEND_API_KEY is "
                             "current and has send permission.")
            return out
        if not response.ok:
            out["state"] = "error"
            out["detail"] = "Resend answered HTTP %s." % response.status_code
            return out

        data = response.json() or {}
        domains = data.get("data") or []
        sender_domain = (config["from"] or "").split("@")[-1].lower()
        verified = [
            d for d in domains
            if (d.get("status") or "").lower() == "verified"
        ]
        if any((d.get("name") or "").lower() == sender_domain for d in verified):
            out["state"] = "connected"
        elif verified:
            out["state"] = "error"
            out["detail"] = (
                "%s is not a verified sending domain in Resend (verified: %s). "
                "Mail from EMAIL_FROM will be refused."
                % (sender_domain, ", ".join(d.get("name") or "?" for d in verified))
            )
        else:
            out["state"] = "error"
            out["detail"] = ("No verified sending domain in Resend. Add and verify "
                             "one before HQ can send.")
    except (requests.RequestException, ValueError) as exc:
        # A broken integration must render as a red dot, not a 500 — status() is
        # what an operator opens *because* something is wrong.
        out["state"] = "error"
        out["detail"] = "Could not reach Resend at %s: %s" % (config["url"], exc)
    return out
