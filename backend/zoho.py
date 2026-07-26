"""Zoho Books — a read-only mirror of the money.

Zoho Books is the system of record for every rupee ZeroOne bills: invoices,
payments, credit notes and the GST hanging off them. HQ deliberately does not
take that job on. It mirrors the figures so a customer record can show what is
owed without opening a second tab, and links out to Zoho for anything a human
actually needs to change.

**HQ never writes to Zoho Books.** There is no create, update or delete call in
this module and there must never be one — two systems both claiming to author an
invoice is exactly how a numbering series and a GST return drift apart, and the
one in Zoho is the one the tax office sees. The OAuth scope the operator is told
to grant is read-only for the same reason: the credential itself should be
incapable of a write, not merely unused by today's code.

Everything here is optional. With no ZOHO_* variables set the app boots exactly
as it did before and the Zoho panel simply reports "not configured".

Verified against the Zoho Books v3 documentation (July 2026): the India data
centre is ``www.zohoapis.in``, tokens come from ``accounts.zoho.in``, an access
token lives one hour, lists page at a maximum of 200 rows via ``page`` /
``per_page`` with a ``page_context.has_more_page`` flag, and the per-organisation
limit is 100 requests a minute (HTTP 429, error code 44). What the docs do *not*
publish is a sample list payload, so every field below is read with ``.get`` —
a renamed or absent field must degrade to ``None``, never raise.
"""

import logging
import os
import re
import threading
import time

import requests

logger = logging.getLogger("zoho")

# ZeroOne's Zoho Books organisation, India DC. Both are overridable because a
# second entity (or a sandbox org) should not need a code change.
_DEFAULT_ORG_ID = "60078183686"
_DEFAULT_DC = "in"

# Every network call is bounded. A hung Zoho connection must not hold a worker.
_TIMEOUT = 30

# Zoho's documented maximum page size. Fewer round trips is the whole game when
# the budget is 100 requests a minute for the entire organisation.
_PER_PAGE = 200

# 50 pages x 200 rows = 10,000 records. Far beyond anything ZeroOne has, and a
# hard stop so a misbehaving has_more_page flag cannot spin forever.
_MAX_PAGES = 50

# Refresh a minute early rather than discover expiry as a mid-request 401.
_TOKEN_SAFETY_MARGIN = 60

# Rate limiting: two retries, then give up and let the caller decide. Zoho's
# window is per minute, so a short backoff is a courtesy, not a cure.
_MAX_THROTTLE_RETRIES = 2
_BACKOFF_SECONDS = (5.0, 15.0)
_MAX_RETRY_AFTER = 60.0

# Connection reuse. Zoho is a single host and TLS handshakes are not free.
_SESSION = requests.Session()

# The access token is cached process-wide, not per request — a token fetch is a
# billable API call, and FastAPI runs sync endpoints on a thread pool, so two
# concurrent requests would otherwise both refresh.
_TOKEN = {"value": None, "expires_at": 0.0}
_TOKEN_LOCK = threading.Lock()

_SETUP_HINT = (
    "Set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN in the "
    "server environment (ZOHO_ORG_ID defaults to %s, ZOHO_DC to '%s'). "
    "To obtain them: sign in to https://api-console.zoho.in as the Zoho Books "
    "admin, choose Self Client, copy the Client ID and Client Secret, then on "
    "the Generate Code tab request the scope "
    "ZohoBooks.contacts.READ,ZohoBooks.invoices.READ,ZohoBooks.settings.READ "
    "— READ operations only, because HQ must never be able to write to Zoho "
    "Books. Do NOT use ZohoBooks.fullaccess.all: it grants write access. "
    "(Zoho's scope format is ZohoBooks.<module>.<CREATE|READ|UPDATE|DELETE|ALL>; "
    "there is no 'fullaccess.READ' variant, verified against "
    "https://www.zoho.com/books/api/v3/oauth/ on 2026-07-26.) "
    "Exchange the resulting grant code (valid minutes, not days) for a refresh "
    "token by POSTing grant_type=authorization_code with the client id, secret "
    "and code to https://accounts.zoho.in/oauth/v2/token; the refresh_token in "
    "that response is the long-lived one HQ needs."
) % (_DEFAULT_ORG_ID, _DEFAULT_DC)


class ZohoError(Exception):
    """Anything the caller cannot recover from, in words an operator can act on.

    Callers get this and only this — a raw requests exception leaking into a
    FastAPI handler turns a Zoho outage into an HQ 500 with a stack trace.
    """


# ── configuration ───────────────────────────────────────────────────────────

def _env(name, default=None):
    value = (os.getenv(name) or "").strip()
    return value or default


def _config():
    """Read the environment on every use, so status() reflects reality now."""
    return {
        "client_id": _env("ZOHO_CLIENT_ID"),
        "client_secret": _env("ZOHO_CLIENT_SECRET"),
        "refresh_token": _env("ZOHO_REFRESH_TOKEN"),
        "org_id": _env("ZOHO_ORG_ID", _DEFAULT_ORG_ID),
        # A leading dot is the obvious typo ('.in'); the DC suffix itself may
        # contain dots (com.au, com.cn), so only the leading one is stripped.
        "dc": (_env("ZOHO_DC", _DEFAULT_DC) or _DEFAULT_DC).lstrip(".").lower(),
    }


def _missing():
    cfg = _config()
    return [
        name
        for name, key in (
            ("ZOHO_CLIENT_ID", "client_id"),
            ("ZOHO_CLIENT_SECRET", "client_secret"),
            ("ZOHO_REFRESH_TOKEN", "refresh_token"),
        )
        if not cfg[key]
    ]


def is_configured():
    """True when the three secrets are present. Org id and DC always default."""
    return not _missing()


def _require_configured():
    missing = _missing()
    if missing:
        raise ZohoError(
            "Zoho Books is not configured — missing %s. %s"
            % (", ".join(missing), _SETUP_HINT)
        )


def status(last_sync=None):
    """A small dict the UI can render without knowing anything about OAuth.

    Proving the connection needs a token, so the first call costs one request to
    accounts.zoho; every later call is answered from the cached token.
    """
    cfg = _config()
    out = {
        "configured": is_configured(),
        "state": "not configured",
        "organisation_id": cfg["org_id"],
        "data_centre": cfg["dc"],
        "last_sync": last_sync,
        "detail": None,
    }
    if not out["configured"]:
        out["detail"] = "Missing %s. %s" % (", ".join(_missing()), _SETUP_HINT)
        return out
    try:
        _access_token()
        out["state"] = "connected"
    except ZohoError as exc:
        # A broken integration must render as a red dot, not a 500 — status() is
        # what the operator opens *because* something is wrong.
        out["state"] = "error"
        out["detail"] = str(exc)
    return out


# ── OAuth ───────────────────────────────────────────────────────────────────

def _accounts_url(cfg):
    return "https://accounts.zoho.%s/oauth/v2/token" % cfg["dc"]


def _api_url(cfg, path):
    return "https://www.zohoapis.%s/books/v3/%s" % (cfg["dc"], path.lstrip("/"))


def _forget_token():
    with _TOKEN_LOCK:
        _TOKEN["value"] = None
        _TOKEN["expires_at"] = 0.0


def _access_token():
    """Return a live access token, refreshing only when the cached one is done.

    Zoho access tokens last an hour and refreshing counts against the same
    per-minute budget as real reads, so refreshing per call would spend a fifth
    of the budget on nothing.
    """
    _require_configured()
    # Monotonic, not wall clock: an NTP correction must not make a live token
    # look expired (or worse, an expired one look live).
    now = time.monotonic()
    with _TOKEN_LOCK:
        if _TOKEN["value"] and now < _TOKEN["expires_at"]:
            return _TOKEN["value"]

        cfg = _config()
        try:
            resp = _SESSION.post(
                _accounts_url(cfg),
                # Form body, never the query string: a client secret in a URL
                # ends up in proxy and access logs.
                data={
                    "grant_type": "refresh_token",
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                    "refresh_token": cfg["refresh_token"],
                },
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ZohoError("Could not reach Zoho's OAuth service: %s" % exc)

        payload = _json(resp, "the OAuth token response")
        # Zoho answers a rejected refresh token with HTTP 200 and an "error"
        # key, so status_code alone is not enough to tell success from failure.
        if resp.status_code != 200 or payload.get("error"):
            reason = payload.get("error") or ("HTTP %s" % resp.status_code)
            raise ZohoError(
                "Zoho refused the refresh token (%s). The refresh token may have "
                "been revoked, or belong to a different data centre than "
                "ZOHO_DC=%s. %s" % (reason, cfg["dc"], _SETUP_HINT)
            )

        token = payload.get("access_token")
        if not token:
            raise ZohoError("Zoho returned no access_token in the token response.")

        expires_in = payload.get("expires_in")
        try:
            lifetime = float(expires_in)
        except (TypeError, ValueError):
            lifetime = 3600.0  # documented default when Zoho omits it
        _TOKEN["value"] = token
        _TOKEN["expires_at"] = now + max(lifetime - _TOKEN_SAFETY_MARGIN, 0.0)
        # Deliberately never logged: not the token, not the secret, not a prefix.
        logger.info("Zoho access token refreshed (valid %.0fs).", lifetime)
        return token


# ── HTTP ────────────────────────────────────────────────────────────────────

def _json(resp, what):
    """Parse a response body, or say plainly that it was not JSON."""
    try:
        parsed = resp.json()
    except ValueError:
        raise ZohoError(
            "Zoho returned a non-JSON body for %s (HTTP %s): %s"
            % (what, resp.status_code, (getattr(resp, "text", "") or "")[:200])
        )
    if not isinstance(parsed, dict):
        raise ZohoError("Zoho returned an unexpected body for %s: %r" % (what, parsed))
    return parsed


def _retry_delay(resp, attempt):
    """How long to wait after a 429.

    Zoho does not send Retry-After today, but honouring it when present costs
    two lines and is the only correct answer if they ever start.
    """
    header = (getattr(resp, "headers", None) or {}).get("Retry-After")
    if header:
        try:
            return min(max(float(str(header).strip()), 0.0), _MAX_RETRY_AFTER)
        except ValueError:
            pass  # an HTTP-date form is not worth parsing; fall back to backoff
    index = min(attempt, len(_BACKOFF_SECONDS)) - 1
    return _BACKOFF_SECONDS[max(index, 0)]


def _get(path, params):
    """One authenticated GET, with bounded recovery. The only verb in this file.

    At most four requests leave here: an optional single token refresh after a
    401, and at most two retries after a 429. Nothing here can loop.
    """
    cfg = _config()
    url = _api_url(cfg, path)
    query = dict(params or {})
    # Zoho spells it the American way; HQ spells it organisation everywhere else.
    query["organization_id"] = cfg["org_id"]

    refreshed = False
    throttled = 0
    while True:
        token = _access_token()
        try:
            resp = _SESSION.get(
                url,
                headers={"Authorization": "Zoho-oauthtoken %s" % token},
                params=query,
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ZohoError("Could not reach Zoho Books at /%s: %s" % (path.lstrip("/"), exc))

        if resp.status_code == 401 and not refreshed:
            # Exactly one retry. If a freshly minted token is also rejected the
            # problem is the grant, not the expiry, and retrying just burns
            # quota against a credential that will never work.
            refreshed = True
            _forget_token()
            logger.info("Zoho returned 401 on /%s; refreshing the token once.", path.lstrip("/"))
            continue

        if resp.status_code == 429 and throttled < _MAX_THROTTLE_RETRIES:
            throttled += 1
            delay = _retry_delay(resp, throttled)
            logger.warning(
                "Zoho rate-limited /%s; waiting %.0fs (retry %d of %d).",
                path.lstrip("/"), delay, throttled, _MAX_THROTTLE_RETRIES,
            )
            time.sleep(delay)
            continue

        if resp.status_code == 429:
            raise ZohoError(
                "Zoho Books is rate-limiting HQ (100 requests per minute per "
                "organisation) and did not recover after %d retries. Try again "
                "in a minute." % _MAX_THROTTLE_RETRIES
            )

        if resp.status_code == 401:
            raise ZohoError(
                "Zoho rejected the credentials for /%s even after refreshing. "
                "The refresh token is probably revoked, or lacks the read scope. "
                "%s" % (path.lstrip("/"), _SETUP_HINT)
            )

        if resp.status_code != 200:
            body = {}
            try:
                body = _json(resp, "an error response")
            except ZohoError:
                pass
            raise ZohoError(
                "Zoho Books returned HTTP %s for /%s: %s"
                % (resp.status_code, path.lstrip("/"), body.get("message") or "no message")
            )

        return _json(resp, "/%s" % path.lstrip("/"))


def _paginate(path, node):
    """Walk every page of a Zoho list endpoint, or say why it stopped.

    Returning only the first page is the failure mode that matters here: it does
    not look like an error, it looks like a customer having fewer invoices than
    they do.
    """
    rows = []
    page = 1
    while page <= _MAX_PAGES:
        payload = _get(path, {"page": page, "per_page": _PER_PAGE})
        batch = payload.get(node) or []
        if not isinstance(batch, list):
            raise ZohoError("Zoho returned a non-list '%s' node for /%s." % (node, path))
        rows.extend(item for item in batch if isinstance(item, dict))

        context = payload.get("page_context") or {}
        # An absent flag stops the walk. Guessing "there is probably more" would
        # loop against an unfamiliar payload shape and burn the minute's quota.
        if not context.get("has_more_page"):
            return rows
        if not batch:
            logger.warning("Zoho claims more pages of %s but returned none; stopping.", node)
            return rows
        page += 1

    logger.warning(
        "Stopped reading %s at the %d-page cap (%d rows); Zoho says there is more. "
        "Raise _MAX_PAGES if this organisation has genuinely outgrown it.",
        node, _MAX_PAGES, len(rows),
    )
    return rows


def _amount(value):
    """Money as a float, or None. A string sneaking through must not reach the UI."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── read-only endpoints ─────────────────────────────────────────────────────

def _contact(row):
    return {
        "contact_id": row.get("contact_id"),
        "contact_name": row.get("contact_name"),
        "company_name": row.get("company_name"),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "outstanding_receivable_amount": _amount(row.get("outstanding_receivable_amount")),
    }


def list_contacts():
    """Every customer in the Zoho Books organisation, all pages, as plain dicts.

    Zoho keeps customers and vendors in the same /contacts collection. Rather
    than trust an unverified server-side filter, the split is done here and errs
    towards keeping a row: an unrecognised contact_type is kept, so a Zoho field
    rename surfaces as a stray vendor rather than as missing customers.
    """
    kept = []
    dropped = 0
    for row in _paginate("contacts", "contacts"):
        kind = (row.get("contact_type") or "").strip().lower()
        if kind and kind != "customer":
            dropped += 1
            continue
        kept.append(_contact(row))
    if dropped:
        logger.info("Skipped %d non-customer Zoho contacts (vendors etc.).", dropped)
    return kept


def _invoice(row):
    return {
        "invoice_id": row.get("invoice_id"),
        "invoice_number": row.get("invoice_number"),
        "customer_id": row.get("customer_id"),
        "customer_name": row.get("customer_name"),
        "date": row.get("date"),
        "due_date": row.get("due_date"),
        "status": row.get("status"),
        "total": _amount(row.get("total")),
        "balance": _amount(row.get("balance")),
        "currency_code": row.get("currency_code"),
    }


def list_invoices():
    """Every invoice in the organisation, all pages, as plain dicts.

    Mirrored for display only — the invoice a customer receives is always the
    one Zoho generated, and HQ links to it rather than reprinting it.
    """
    return [_invoice(row) for row in _paginate("invoices", "invoices")]


# ── proposing links to HQ customers ─────────────────────────────────────────

# Words that say what kind of legal entity something is, not which one. Dropping
# them is what lets "NEO NIR ENGINEERING LLP" meet HQ's "NeoNir Engineering".
_LEGAL_TOKENS = {
    "private", "limited", "ltd", "pvt", "llp", "llc", "inc", "incorporated",
    "corp", "corporation", "company", "co", "enterprises", "enterprise",
    "and", "the",
}

# Below this length a shared prefix means nothing — "om" prefixes "omkar".
_MIN_PREFIX = 6

# Share three quarters of the shorter name's words and it is worth pre-ticking;
# share fewer and a human still has to look.
_LIKELY_OVERLAP = 0.75
_WEAK_OVERLAP = 0.40


def _tokens(name):
    """Meaningful words of a company name, lowercased and de-punctuated."""
    cleaned = re.sub(r"[^0-9a-z]+", " ", (name or "").casefold())
    return [word for word in cleaned.split() if word and word not in _LEGAL_TOKENS]


def _key(name):
    """Tokens run together, so 'Micro Chem' and 'Microchem' land on one string."""
    return "".join(_tokens(name))


def _clean_email(value):
    return (value or "").strip().casefold() or None


def _prefix_pair(a, b):
    """True when one key is the other plus a trailing descriptor."""
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    return len(shorter) >= _MIN_PREFIX and longer.startswith(shorter)


def _overlap(a_tokens, b_tokens):
    """Shared words as a fraction of the shorter name.

    Deliberately not Jaccard: "Feed Aqua Engineering" against "Feed Aqua" should
    not be punished for the extra word one side happens to carry.
    """
    a, b = set(a_tokens), set(b_tokens)
    if not a or not b:
        return 0.0, set()
    shared = a & b
    return len(shared) / float(min(len(a), len(b))), shared


def match_contacts(zoho_contacts, hq_customers):
    """Propose links between Zoho contacts and HQ customers. Proposes only.

    Nothing here writes, and nothing here is safe to auto-apply — least of all a
    weak match. The real data is the argument: Zoho's "GOA TRADING & TECHNICAL
    SERVICES" is HQ's "Michael Bhai", and no amount of string cleverness will
    ever derive one from the other. A person knows; an algorithm can only offer
    a shortlist and be honest about how sure it is.

    ``hq_customers`` is a list of dicts with id, display_name and (optionally)
    email. Returns a list of proposals, at most one per Zoho contact and at most
    one per HQ customer, each with a confidence and a reason a human can check
    in a second. "exact" is reserved for a match on a unique identifier — an
    email address — and is never awarded on a name however identical, because
    two unrelated firms sharing a name is a thing that happens.
    """
    zoho = []
    for row in zoho_contacts or []:
        # contact_name is what Zoho shows; company_name is the fallback for the
        # rows where a contact was created against an organisation only.
        name = (row.get("contact_name") or row.get("company_name") or "").strip()
        zoho.append({
            "id": row.get("contact_id"),
            "name": name,
            "email": _clean_email(row.get("email")),
            "key": _key(name),
            "tokens": _tokens(name),
        })

    hq = []
    for row in hq_customers or []:
        name = (row.get("display_name") or "").strip()
        hq.append({
            "id": row.get("id"),
            "name": name,
            "email": _clean_email(row.get("email")),
            "key": _key(name),
            "tokens": _tokens(name),
        })

    candidates = []
    for zi, z in enumerate(zoho):
        for hi, h in enumerate(hq):
            if z["email"] and h["email"] and z["email"] == h["email"]:
                candidates.append((0, 1.0, zi, hi, "exact",
                                   "same email address (%s)" % z["email"]))
                continue
            if z["key"] and z["key"] == h["key"]:
                candidates.append((1, 1.0, zi, hi, "likely",
                                   "names normalise to the same value ('%s')" % z["key"]))
                continue
            if _prefix_pair(z["key"], h["key"]):
                candidates.append((2, 0.9, zi, hi, "likely",
                                   "'%s' and '%s' differ only by a trailing descriptor"
                                   % (z["key"], h["key"])))
                continue
            score, shared = _overlap(z["tokens"], h["tokens"])
            if score >= _LIKELY_OVERLAP:
                candidates.append((3, score, zi, hi, "likely",
                                   "shares every significant word: %s" % ", ".join(sorted(shared))))
            elif score >= _WEAK_OVERLAP:
                candidates.append((4, score, zi, hi, "weak",
                                   "shares %d of %d words: %s"
                                   % (len(shared), min(len(set(z["tokens"])), len(set(h["tokens"]))),
                                      ", ".join(sorted(shared)))))

    # Strongest evidence first, then greedily one-to-one. A customer already
    # claimed by an email match must not also be offered on a shared word — that
    # is how a review queue fills with noise nobody reads.
    candidates.sort(key=lambda c: (c[0], -c[1], zoho[c[2]]["name"], hq[c[3]]["name"]))

    proposals = []
    taken_zoho = set()
    taken_hq = set()
    for _, _, zi, hi, confidence, reason in candidates:
        if zi in taken_zoho or hi in taken_hq:
            continue
        z, h = zoho[zi], hq[hi]
        taken_zoho.add(zi)
        taken_hq.add(hi)
        proposals.append({
            "zoho_contact_id": z["id"],
            "zoho_name": z["name"],
            "hq_customer_id": h["id"],
            "hq_name": h["name"],
            "confidence": confidence,
            "reason": reason,
        })
    return proposals
