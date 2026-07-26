"""Message ingestion for the Communication workspace.

A client's message arrives from a carrier — the WhatsApp bot at wa.dotsai.cloud,
a mailbox — and has to land against the right thread, and ideally the right
customer, without anyone re-typing it.

Two things make this harder than it looks, and both are handled here rather than
hoped about:

**Identity.** A WhatsApp message carries a phone number, not a customer. The
number is matched against contacts and customers in that order, and when nothing
matches the thread is still created — unattached. An unattached thread is
visible and fixable; a dropped message is neither.

**Replay.** Carriers retry. Every message carries the provider's own id and that
is the idempotency key, so the same delivery arriving three times is one row.
"""

import logging
import os
import re
from datetime import datetime

from backend.crm_models import CommChannel, Conversation, ConversationMessage, Party, PartyContact

logger = logging.getLogger("comms")


def webhook_token():
    return (os.getenv("COMMS_WEBHOOK_TOKEN") or "").strip()


def webhook_enabled():
    return bool(webhook_token())


class Ignored(Exception):
    """This message is not one HQ should keep. A policy, not a failure."""


def known_senders_only():
    """Whether a message from a stranger should be dropped instead of threaded.

    Off by default, because normally a dropped message is the worst outcome: an
    unattached thread is visible and fixable, silence is neither.

    It exists because HQ's carrier is a WhatsApp bot running on a number that is
    also somebody's personal phone, and this inbox is read by the whole team.
    With it on, only senders already on record land here, and the family and the
    delivery notifications stay out. Set COMMS_KNOWN_SENDERS_ONLY=true on any
    deployment whose carrier is not a dedicated business line.
    """
    return (os.getenv("COMMS_KNOWN_SENDERS_ONLY") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _digits(value):
    """Compare phone numbers by their last 10 digits.

    The same person is +91-98251 15308 in one system, 919825115308 in another and
    09825115308 in a third. Country codes and punctuation are noise; the
    subscriber number is the identity.
    """
    if not value:
        return None
    only = re.sub(r"\D", "", str(value))
    return only[-10:] if len(only) >= 10 else (only or None)


def _normalise(identifier, channel_type):
    if channel_type == "email":
        return (identifier or "").strip().lower()
    return _digits(identifier) or (identifier or "").strip()


def resolve_party(db, organisation_id, identifier, channel_type):
    """Find who this address belongs to. Returns (party_id, party_contact_id).

    Never guesses: an address either matches something on record or it does not.
    """
    if not identifier:
        return None, None

    if channel_type == "email":
        email = (identifier or "").strip().lower()
        contact = db.query(PartyContact).filter(
            PartyContact.organisation_id == organisation_id,
            PartyContact.email.ilike(email),
        ).first()
        if contact:
            return contact.party_id, contact.id
        party = db.query(Party).filter(
            Party.organisation_id == organisation_id, Party.email.ilike(email)
        ).first()
        return (party.id if party else None), None

    wanted = _digits(identifier)
    if not wanted:
        return None, None

    # Compared in Python because the stored formats are inconsistent — a LIKE
    # against a column that might hold "+91-98251 15308" will not match.
    for contact in db.query(PartyContact).filter(
        PartyContact.organisation_id == organisation_id
    ).all():
        if wanted in (_digits(contact.phone), _digits(contact.whatsapp)):
            return contact.party_id, contact.id

    for party in db.query(Party).filter(Party.organisation_id == organisation_id).all():
        if wanted == _digits(party.phone):
            return party.id, None

    return None, None


def find_channel(db, organisation_id, channel_id=None, channel_type=None, identifier=None):
    """The channel a message arrived on."""
    query = db.query(CommChannel).filter(CommChannel.organisation_id == organisation_id)
    if channel_id:
        return query.filter(CommChannel.id == channel_id).first()
    if identifier:
        hit = query.filter(CommChannel.identifier == str(identifier)).first()
        if hit:
            return hit
    if channel_type:
        return query.filter(CommChannel.channel_type == channel_type,
                            CommChannel.status == "active").first()
    return None


def ingest(db, organisation_id, payload):
    """Land one inbound or outbound message. Idempotent on external_id.

    Returns (message, conversation, created) where `created` says whether this
    was a new message rather than a replay.
    """
    channel = find_channel(
        db, organisation_id,
        channel_id=payload.get("channel_id"),
        channel_type=payload.get("channel_type"),
        identifier=payload.get("to"),
    )
    if channel is None:
        raise ValueError(
            "No channel matched. Pass channel_id, or channel_type "
            "(whatsapp|email|sms), or a 'to' matching a configured channel."
        )

    identifier = _normalise(payload.get("from") or payload.get("contact_identifier"),
                            channel.channel_type)
    if not identifier:
        raise ValueError("A message needs a 'from' address to belong to a thread.")

    external_id = (payload.get("external_id") or "").strip() or None
    if external_id:
        # Carriers retry. The provider's id is the only reliable way to tell a
        # retry from a genuine second message with identical text.
        existing = db.query(ConversationMessage).filter(
            ConversationMessage.organisation_id == organisation_id,
            ConversationMessage.external_id == external_id,
        ).first()
        if existing:
            return existing, existing.conversation, False

    conversation = db.query(Conversation).filter(
        Conversation.organisation_id == organisation_id,
        Conversation.channel_id == channel.id,
        Conversation.contact_identifier == identifier,
    ).first()

    direction = (payload.get("direction") or "inbound").lower()
    if direction not in ("inbound", "outbound"):
        direction = "inbound"

    if conversation is None:
        party_id, contact_id = resolve_party(db, organisation_id, identifier, channel.channel_type)
        if party_id is None and known_senders_only():
            # Only ever reached for a sender with no thread here already. Once a
            # conversation exists its continuation is kept regardless, because a
            # half-recorded thread is worse than either whole answer.
            logger.info("Dropped a message on %s from unknown sender %s "
                        "(COMMS_KNOWN_SENDERS_ONLY is on)", channel.name, identifier)
            raise Ignored(
                "Sender %s is not a known contact, and this deployment only "
                "accepts messages from numbers already on record." % identifier
            )
        conversation = Conversation(
            organisation_id=organisation_id,
            channel_id=channel.id,
            contact_identifier=identifier,
            contact_name=payload.get("contact_name") or identifier,
            party_id=party_id,
            party_contact_id=contact_id,
            subject=payload.get("subject"),
            status="open",
        )
        db.add(conversation)
        db.flush()
        if party_id is None:
            logger.info("New unattached thread on %s from %s", channel.name, identifier)
    elif conversation.party_id is None:
        # A customer added after the thread started should adopt it.
        party_id, contact_id = resolve_party(db, organisation_id, identifier, channel.channel_type)
        if party_id:
            conversation.party_id = party_id
            conversation.party_contact_id = contact_id

    sent_at = payload.get("sent_at")
    if isinstance(sent_at, str):
        try:
            sent_at = datetime.fromisoformat(sent_at.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            sent_at = None
    sent_at = sent_at or datetime.utcnow()

    message = ConversationMessage(
        organisation_id=organisation_id,
        conversation_id=conversation.id,
        direction=direction,
        message_type=payload.get("message_type") or "text",
        body=payload.get("body"),
        media_url=payload.get("media_url"),
        external_id=external_id,
        delivery_status=payload.get("delivery_status"),
        sent_at=sent_at,
        author_id=payload.get("author_id"),
    )
    db.add(message)

    conversation.last_message_at = sent_at
    if direction == "inbound":
        conversation.last_inbound_at = sent_at
        conversation.unread_count = (conversation.unread_count or 0) + 1
        # A reply on a closed thread reopens it — the client does not know or
        # care that someone marked it done.
        if conversation.status in ("closed", "snoozed"):
            conversation.status = "open"
            conversation.closed_at = None
    else:
        conversation.unread_count = 0

    db.flush()
    return message, conversation, True


def thread(db, organisation_id, conversation_id, limit=200):
    """One conversation with its messages, oldest first."""
    convo = db.query(Conversation).filter(
        Conversation.organisation_id == organisation_id,
        Conversation.id == conversation_id,
    ).first()
    if convo is None:
        return None

    messages = db.query(ConversationMessage).filter(
        ConversationMessage.conversation_id == convo.id
    ).order_by(ConversationMessage.sent_at.asc()).limit(limit).all()

    return {
        "id": convo.id,
        "contact_name": convo.contact_name,
        "contact_identifier": convo.contact_identifier,
        "channel_id": convo.channel_id,
        "channel": convo.channel.name if convo.channel else None,
        "channel_type": convo.channel.channel_type if convo.channel else None,
        "party_id": convo.party_id,
        "party": convo.party.display_name if convo.party else None,
        "status": convo.status,
        "assigned_to": convo.assigned_to,
        "unread_count": convo.unread_count,
        "last_message_at": convo.last_message_at.isoformat() + "Z" if convo.last_message_at else None,
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "body": m.body,
                "message_type": m.message_type,
                "media_url": m.media_url,
                "delivery_status": m.delivery_status,
                "sent_at": m.sent_at.isoformat() + "Z" if m.sent_at else None,
                "author_id": m.author_id,
            }
            for m in messages
        ],
    }


def mark_read(db, conversation):
    conversation.unread_count = 0
