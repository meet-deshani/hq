"""Outbound delivery through the WhatsApp bot at wa.dotsai.cloud.

HQ records every outbound message either way. What this module decides is
whether that record is allowed to claim the client actually received it.

Three outcomes, and the thread always says which one happened:

  ``sent``      the bot accepted the message and returned its own id
  ``failed``    the bot refused it, or could not be reached
  ``recorded``  no bot is configured — HQ logged the text, nothing was sent

An undelivered message is still worth keeping: it was written, it just has to be
said somewhere else as well. A thread that *looks* delivered when nothing left
the building is worse than one that admits it did nothing.

Addressing is the sharp edge. Conversations store only the last ten digits of a
number (see ``comms._digits``) because that is what makes the same person match
across three differently-formatted systems. Ten digits are not dialable — the
country code is exactly what was thrown away — so this module rebuilds the full
number from the linked contact wherever it can, and refuses to send when it
would have to guess. Delivering a client's message to a stranger who happens to
share their subscriber number is not a recoverable mistake.
"""

import logging
import os
import re
import time

import requests

from backend.crm_models import PartyContact

logger = logging.getLogger("whatsapp")

_DEFAULT_URL = "https://wa.dotsai.cloud"
_DEFAULT_COUNTRY_CODE = "91"
_TIMEOUT = 20

# A country code plus a subscriber number. Below this a number is a bare local
# subscriber number and cannot be dialled internationally; above it, E.164 says
# it is not a phone number at all.
_MIN_INTERNATIONAL_DIGITS = 11
_MAX_DIGITS = 15

# One host, many messages — TLS handshakes are not free.
_SESSION = requests.Session()

SETUP_HINT = (
    "Set WHATSAPP_BOT_API_TOKEN in the server environment (and WHATSAPP_BOT_URL "
    "if the bot is not at %s). The token is the same WHATSAPP_BOT_API_TOKEN the "
    "bot itself is started with." % _DEFAULT_URL
)


class WhatsAppError(Exception):
    """A send that did not happen, in words an operator can act on."""


def _env(name, default=None):
    value = (os.getenv(name) or "").strip()
    return value or default


def _country_code():
    """The code prefixed to a bare subscriber number when nothing better is on file.

    Unset means the India default, because that is where every customer in this
    book is. Set-but-blank means never guess — and that distinction is the only
    way an operator can turn the assumption off, so it is read from the raw
    environment rather than through _env, which cannot tell the two apart.
    """
    raw = os.environ.get("WHATSAPP_COUNTRY_CODE")
    if raw is None:
        raw = _DEFAULT_COUNTRY_CODE
    return re.sub(r"\D", "", raw)


def _config():
    """Read the environment on every use, so status reflects reality now."""
    return {
        "url": (_env("WHATSAPP_BOT_URL", _DEFAULT_URL) or _DEFAULT_URL).rstrip("/"),
        "token": _env("WHATSAPP_BOT_API_TOKEN"),
        "country_code": _country_code(),
    }


def is_configured():
    """True when HQ has a token to talk to the bot with."""
    return bool(_config()["token"])


def _digits(value):
    return re.sub(r"\D", "", str(value or ""))


def dial_address(db, conversation):
    """The full international number for a thread, or None if it can only be guessed.

    Preference runs from most to least trustworthy: the number on the linked
    contact, then the one on the linked customer, then the thread's own
    identifier. Each is taken only if it is long enough to be carrying a country
    code already.

    Only when everything on file is a bare ten-digit subscriber number is the
    configured country code prefixed, and that is the single assumption made
    here. With no country code configured the answer is None, and the caller
    declines to send rather than dial a number it invented.
    """
    # A group thread is addressed by the group. Falling through to the walk
    # below would find the linked CONTACT's number and deliver a message meant
    # for a group of people privately to one of them — the same class of mistake
    # as dialling a stranger who shares a subscriber number, and just as
    # unrecoverable once sent.
    from backend import comms

    if comms.is_group(conversation.contact_identifier):
        return conversation.contact_identifier

    candidates = []
    if conversation.party_contact_id:
        contact = db.query(PartyContact).filter(
            PartyContact.id == conversation.party_contact_id
        ).first()
        if contact:
            candidates += [contact.whatsapp, contact.phone]
    if conversation.party is not None:
        candidates.append(conversation.party.phone)
    candidates.append(conversation.contact_identifier)

    for candidate in candidates:
        digits = _digits(candidate)
        if _MIN_INTERNATIONAL_DIGITS <= len(digits) <= _MAX_DIGITS:
            return digits

    country_code = _config()["country_code"]
    bare = _digits(conversation.contact_identifier)
    if country_code and len(bare) == 10:
        return country_code + bare
    return None


def send_text(number, body):
    """Hand one message to the bot. Returns the provider's message id.

    Raises WhatsAppError whenever the message did not go out, for any reason at
    all. The caller records that failure against the thread; nothing here ever
    reports a success it did not get.
    """
    config = _config()
    if not config["token"]:
        raise WhatsAppError("WhatsApp sending is not configured. " + SETUP_HINT)

    try:
        response = _SESSION.post(
            config["url"] + "/api/send/text",
            headers={"Authorization": "Bearer %s" % config["token"]},
            json={"to": number, "message": body},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise WhatsAppError(
            "Could not reach the WhatsApp bot at %s: %s" % (config["url"], exc)
        )

    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.status_code == 503:
        raise WhatsAppError(
            "The WhatsApp bot is running but not connected to WhatsApp — it "
            "probably needs its QR re-scanned at %s/api/qr." % config["url"]
        )
    if response.status_code in (401, 403):
        raise WhatsAppError(
            "The WhatsApp bot rejected HQ's API token. Check WHATSAPP_BOT_API_TOKEN "
            "matches the token the bot was started with."
        )
    if not response.ok or not data.get("success"):
        raise WhatsAppError(
            "The WhatsApp bot refused the message: %s"
            % (data.get("error") or "HTTP %s" % response.status_code)
        )

    message_id = data.get("messageId")
    if not message_id:
        # Accepted, but unidentifiable. It did go out, so this is still a send —
        # but without the provider's id the delivery echo cannot be recognised as
        # the same message, so it is worth a line in the log.
        logger.warning("Bot accepted a message but returned no messageId")
    return message_id


# ── groups ──────────────────────────────────────────────────────────────────
#
# A client is rarely only a DM. The work usually happens in a group with their
# people and ours in it, and until now HQ could not see those at all — so the
# WhatsApp button could only ever open a personal thread, and the conversation
# that actually mattered lived somewhere HQ had never heard of.
#
# Finding which groups a given customer is in costs one call to list the groups
# and one per group to read its members — 30-odd requests. Far too slow to do
# while somebody waits, and completely wasted when the answer is the same for
# every customer on the page. So the whole roster is fetched once and cached,
# and every customer is answered from memory.

_ROSTER_TTL = 600          # ten minutes; group membership is not volatile
_ROSTER = {"at": 0, "groups": None}


def _member_digits(participant):
    """The last ten digits of a participant's number, or None.

    The bot reports members as {"id": "...@lid", "phoneNumber":
    "917567838028@s.whatsapp.net"}. The `id` is a WhatsApp-internal identifier
    that is NOT a phone number, so matching on it would silently never hit —
    only `phoneNumber` is comparable to what HQ holds.
    """
    if not isinstance(participant, dict):
        return _digits(participant)[-10:] if _digits(participant) else None
    raw = participant.get("phoneNumber") or ""
    digits = _digits(raw.split("@")[0])
    return digits[-10:] if len(digits) >= 10 else None


def _fetch_roster():
    """Every group the bot is in, with its members' last-ten-digits."""
    config = _config()
    headers = {"Authorization": "Bearer %s" % config["token"]}
    response = _SESSION.get(config["url"] + "/api/group/list", headers=headers, timeout=_TIMEOUT)
    if not response.ok:
        raise WhatsAppError("The WhatsApp bot would not list groups: HTTP %s" % response.status_code)
    groups = (response.json() or {}).get("groups") or []

    roster = []
    for group in groups:
        jid = group.get("id")
        if not jid:
            continue
        members = set()
        try:
            info = _SESSION.get(
                "%s/api/group/info/%s" % (config["url"], jid),
                headers=headers, timeout=_TIMEOUT,
            )
            if info.ok:
                detail = (info.json() or {}).get("group") or {}
                for participant in detail.get("participants") or []:
                    got = _member_digits(participant)
                    if got:
                        members.add(got)
        except (requests.RequestException, ValueError) as exc:
            # One unreadable group is not a reason to lose the other thirty.
            logger.info("Could not read members of %s: %s", jid, exc)
        roster.append({"id": jid, "subject": group.get("subject") or jid, "members": members})
    return roster


def groups_for(number, refresh=False):
    """The groups this number is in. Empty when WhatsApp is not configured.

    Never raises: a customer page must still render when the bot is down, and
    "no groups" is a survivable answer where a 500 is not.
    """
    if not is_configured():
        return []
    now = time.time()
    if refresh or _ROSTER["groups"] is None or now - _ROSTER["at"] > _ROSTER_TTL:
        try:
            _ROSTER["groups"] = _fetch_roster()
            _ROSTER["at"] = now
        except (requests.RequestException, ValueError, WhatsAppError) as exc:
            logger.warning("Could not refresh the WhatsApp group roster: %s", exc)
            if _ROSTER["groups"] is None:
                return []

    wanted = _digits(number)
    wanted = wanted[-10:] if len(wanted or "") >= 10 else None
    if not wanted:
        return []
    return [
        {"id": g["id"], "subject": g["subject"]}
        for g in (_ROSTER["groups"] or []) if wanted in g["members"]
    ]


def status():
    """A small dict the UI can render without knowing anything about the bot."""
    config = _config()
    out = {
        "configured": is_configured(),
        "state": "not configured",
        "url": config["url"],
        "detail": None,
    }
    if not out["configured"]:
        out["detail"] = SETUP_HINT
        return out
    try:
        response = _SESSION.get(
            config["url"] + "/api/health",
            headers={"Authorization": "Bearer %s" % config["token"]},
            timeout=_TIMEOUT,
        )
        data = response.json() if response.ok else {}
        # The bot answers /api/health even while WhatsApp itself is disconnected,
        # which is the whole point of asking: "up" and "able to send" differ.
        if data.get("status") == "open":
            out["state"] = "connected"
        else:
            out["state"] = "error"
            out["detail"] = (
                "The bot is reachable but WhatsApp is %s. Re-pair it at %s/api/qr."
                % (data.get("status") or "not connected", config["url"])
            )
    except (requests.RequestException, ValueError) as exc:
        # A broken integration must render as a red dot, not a 500 — status() is
        # what an operator opens *because* something is wrong.
        out["state"] = "error"
        out["detail"] = "Could not reach the WhatsApp bot at %s: %s" % (config["url"], exc)
    return out
