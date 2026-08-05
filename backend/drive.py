"""Google Drive, through one ZeroOne service account.

The same shape as ``whatsapp.py`` and ``email_send.py``, and for the same
reason: HQ records what it did either way, and this module decides whether that
record is allowed to claim the file actually reached Drive.

Two jobs:

  **upload**    take bytes from the browser and put them in a Drive folder,
                returning the link HQ stores. HQ's container has no disk that
                survives a deploy, so the bytes are streamed straight through
                and never touch it.
  **describe**  given a link somebody pasted, ask Drive what it actually is —
                the real filename, the mime type, the size. Without this the
                card can only say "Google Sheet"; with it, it says what the
                sheet is called.

── the constraint that decides the whole design ──────────────────────────────

A service account has **no Drive storage quota of its own**. Uploading to a
normal My Drive folder fails with `403 storageQuotaExceeded`, and the old
workaround — have it create a Google Doc, which used not to count — was closed
in 2021. So the target MUST be a **Shared Drive**, where the drive itself owns
the storage and the service account is merely a member.

That is why every call here sets `supportsAllDrives=true`. Without it the API
pretends Shared Drives do not exist and answers 404 for a folder that is plainly
there — a confusing failure this module refuses to hand to an operator.

── setting it up ─────────────────────────────────────────────────────────────

1. Google Cloud console → a project → enable the Drive API.
2. Create a service account; create a JSON key for it.
3. In Drive, make (or pick) a **Shared Drive**, and add the service account's
   `client_email` as a **Content manager**. A folder in My Drive will not work.
4. Put the folder's id in GOOGLE_DRIVE_FOLDER_ID and the JSON in
   GOOGLE_SERVICE_ACCOUNT_JSON (the whole document, on one line).
"""

import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger("drive")

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_API = "https://www.googleapis.com/drive/v3"
_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
_TIMEOUT = 60

# Full drive scope, deliberately. `drive.file` would be tighter but only ever
# grants access to files THIS app created — which is enough to upload and
# nothing else. Reading the metadata of a link a human pasted, which is half of
# what this module is for, needs access to files the app did not create.
_SCOPE = "https://www.googleapis.com/auth/drive"

# Anything larger is refused before a byte is read. Not a Drive limit — a limit
# on what should pass through a request-scoped Python process that is also
# serving the rest of the portal.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_SESSION = requests.Session()
# `owner` is the client_email the cached token was minted for. Without it, a
# rotated service-account key would keep being ignored for up to an hour: the
# old token is still inside its expiry, so nothing would go and ask for a new
# one. Cached state that outlives the credentials it came from is a lie with a
# timer on it.
_TOKEN = {"value": None, "expires": 0, "owner": None}

SETUP_HINT = (
    "Set GOOGLE_SERVICE_ACCOUNT_JSON (the whole service-account key, on one "
    "line) and GOOGLE_DRIVE_FOLDER_ID in the server environment. The folder "
    "must be in a SHARED DRIVE with the service account added as a Content "
    "manager — a service account has no storage of its own and cannot write to "
    "a normal My Drive folder."
)


class DriveError(Exception):
    """A Drive operation that did not happen, in words an operator can act on."""


def _env(name, default=None):
    value = (os.getenv(name) or "").strip()
    return value or default


def _credentials():
    raw = _env("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise DriveError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON (%s). Paste the whole "
            "key file, including the braces." % exc
        )
    for field in ("client_email", "private_key"):
        if not data.get(field):
            raise DriveError(
                "GOOGLE_SERVICE_ACCOUNT_JSON has no %r — that is not a "
                "service-account key." % field
            )
    return data


def folder_id():
    return _env("GOOGLE_DRIVE_FOLDER_ID")


def is_configured():
    """True when HQ has both a key and somewhere to put files."""
    try:
        return bool(_credentials()) and bool(folder_id())
    except DriveError:
        return False


def _access_token():
    """A bearer token, minted from the service-account key and cached.

    Google issues these for an hour; re-signing an assertion on every upload
    would be a needless round trip. Refreshed a minute early so a token cannot
    expire between the check and the call that uses it.
    """
    now = time.time()
    creds = _credentials()
    if not creds:
        raise DriveError("Google Drive is not configured. " + SETUP_HINT)

    if (_TOKEN["value"] and _TOKEN["expires"] - 60 > now
            and _TOKEN["owner"] == creds["client_email"]):
        return _TOKEN["value"]

    from jose import jwt  # already a dependency, for the same RS256 reason

    assertion = jwt.encode(
        {
            "iss": creds["client_email"],
            "scope": _SCOPE,
            "aud": _TOKEN_URL,
            "iat": int(now),
            "exp": int(now) + 3600,
        },
        creds["private_key"],
        algorithm="RS256",
    )
    try:
        response = _SESSION.post(
            _TOKEN_URL,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                  "assertion": assertion},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise DriveError("Could not reach Google to authenticate: %s" % exc)

    data = {}
    try:
        data = response.json()
    except ValueError:
        pass
    if not response.ok or not data.get("access_token"):
        raise DriveError(
            "Google refused HQ's service-account key: %s. Check the key is "
            "current and the Drive API is enabled on its project."
            % (data.get("error_description") or data.get("error")
               or "HTTP %s" % response.status_code)
        )

    _TOKEN["value"] = data["access_token"]
    _TOKEN["expires"] = now + int(data.get("expires_in") or 3600)
    _TOKEN["owner"] = creds["client_email"]
    return _TOKEN["value"]


def _explain(response, doing):
    """Turn a Drive error into something an operator can act on."""
    try:
        payload = response.json().get("error", {})
    except ValueError:
        payload = {}
    message = payload.get("message") or "HTTP %s" % response.status_code
    reasons = {e.get("reason") for e in (payload.get("errors") or [])}

    if "storageQuotaExceeded" in reasons or "storageQuotaExceeded" in message:
        return DriveError(
            "Google refused the upload: a service account has no storage of its "
            "own, so GOOGLE_DRIVE_FOLDER_ID must be a folder in a SHARED DRIVE, "
            "not in someone's My Drive. Move the folder into a shared drive and "
            "add the service account as a Content manager."
        )
    if response.status_code == 404:
        return DriveError(
            "Drive says that folder does not exist (%s). Either the id in "
            "GOOGLE_DRIVE_FOLDER_ID is wrong, or the service account has not "
            "been added to the shared drive that holds it — Drive reports a "
            "folder it cannot see as missing rather than forbidden." % message
        )
    if response.status_code in (401, 403):
        return DriveError(
            "Google refused HQ's access while %s: %s. Check the service account "
            "is a member of the shared drive." % (doing, message)
        )
    return DriveError("Google refused the request while %s: %s" % (doing, message))


def upload(filename, content, mime=None):
    """Put bytes in the configured folder. Returns what HQ should store.

    The bytes are handed straight to Google and never written to disk — the
    container's filesystem does not survive a deploy, so anything left there is
    already lost.
    """
    if not is_configured():
        raise DriveError("Google Drive is not configured. " + SETUP_HINT)
    if len(content) > MAX_UPLOAD_BYTES:
        raise DriveError(
            "That file is %.1f MB. The limit is %d MB — put larger files in "
            "Drive yourself and paste the link instead."
            % (len(content) / 1048576.0, MAX_UPLOAD_BYTES // 1048576)
        )
    if not content:
        raise DriveError("That file is empty.")

    metadata = {"name": filename or "Untitled", "parents": [folder_id()]}
    try:
        response = _SESSION.post(
            _UPLOAD,
            params={"uploadType": "multipart", "supportsAllDrives": "true",
                    "fields": "id,name,mimeType,size,webViewLink"},
            headers={"Authorization": "Bearer %s" % _access_token()},
            files={
                "metadata": ("metadata", json.dumps(metadata), "application/json"),
                "file": (filename or "Untitled", content,
                         mime or "application/octet-stream"),
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise DriveError("Could not reach Google Drive: %s" % exc)

    if not response.ok:
        raise _explain(response, "uploading")

    data = response.json()
    return {
        "id": data.get("id"),
        "filename": data.get("name") or filename,
        "url": data.get("webViewLink") or (
            "https://drive.google.com/file/d/%s/view" % data.get("id")),
        "mime": data.get("mimeType") or mime,
        "size": int(data["size"]) if str(data.get("size") or "").isdigit() else len(content),
    }


_ID_PATTERNS = [
    r"/document/d/(?:e/)?([\w-]+)",
    r"/spreadsheets/d/(?:e/)?([\w-]+)",
    r"/presentation/d/(?:e/)?([\w-]+)",
    r"/forms/d/(?:e/)?([\w-]+)",
    r"/drive/folders/([\w-]+)",
    r"/file/d/([\w-]+)",
    r"[?&]id=([\w-]+)",
]


def file_id_from(url):
    """The Drive id inside a link, or None if it is not a Drive link.

    `(?:e/)?` on the document shapes because a PUBLISHED link is
    /spreadsheets/d/e/2PACX-.../pubhtml — without it the id captured is the
    literal "e", which is a wrong answer rather than no answer.
    """
    for pattern in _ID_PATTERNS:
        match = re.search(pattern, url or "", re.I)
        if match:
            return match.group(1)
    return None


def describe(url):
    """What Drive says a pasted link actually is, or None if it cannot say.

    Returns None rather than raising for every ordinary reason a lookup fails —
    not a Drive link, not shared with the service account, Drive unreachable.
    An attachment whose real name could not be read is still a perfectly good
    attachment; refusing to file it would be the worse answer.
    """
    if not is_configured():
        return None
    file_id = file_id_from(url)
    if not file_id:
        return None
    try:
        response = _SESSION.get(
            "%s/files/%s" % (_API, file_id),
            params={"supportsAllDrives": "true",
                    "fields": "id,name,mimeType,size"},
            headers={"Authorization": "Bearer %s" % _access_token()},
            timeout=_TIMEOUT,
        )
        if not response.ok:
            logger.info("Drive could not describe %s: HTTP %s", file_id, response.status_code)
            return None
        data = response.json()
    except (requests.RequestException, ValueError, DriveError) as exc:
        logger.info("Drive lookup failed for %s: %s", file_id, exc)
        return None

    return {
        "id": data.get("id"),
        "filename": data.get("name"),
        "mime": data.get("mimeType"),
        "size": int(data["size"]) if str(data.get("size") or "").isdigit() else None,
    }


def status():
    """A small dict the UI can render without knowing anything about Drive."""
    out = {"configured": False, "state": "not configured",
           "folder": folder_id(), "detail": None}
    try:
        creds = _credentials()
    except DriveError as exc:
        out["state"] = "error"
        out["detail"] = str(exc)
        return out

    if not creds or not folder_id():
        out["detail"] = SETUP_HINT
        return out
    out["configured"] = True

    try:
        response = _SESSION.get(
            "%s/files/%s" % (_API, folder_id()),
            params={"supportsAllDrives": "true", "fields": "id,name,driveId,mimeType"},
            headers={"Authorization": "Bearer %s" % _access_token()},
            timeout=_TIMEOUT,
        )
        if not response.ok:
            out["state"] = "error"
            out["detail"] = str(_explain(response, "checking the folder"))
            return out
        data = response.json()
        if not data.get("driveId"):
            # Reachable, and still unusable: a My Drive folder accepts the
            # metadata call and refuses every upload. Better to say so now than
            # at the moment somebody tries to attach a file.
            out["state"] = "error"
            out["detail"] = (
                "'%s' is not in a shared drive. A service account has no storage "
                "of its own, so uploads to it will fail — move it into a shared "
                "drive and add the service account as a Content manager."
                % (data.get("name") or folder_id())
            )
            return out
        out["state"] = "connected"
        out["detail"] = "Uploading into '%s'." % (data.get("name") or folder_id())
    except (requests.RequestException, ValueError) as exc:
        out["state"] = "error"
        out["detail"] = "Could not reach Google Drive: %s" % exc
    except DriveError as exc:
        out["state"] = "error"
        out["detail"] = str(exc)
    return out
