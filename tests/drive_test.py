#!/usr/bin/env python3
"""Google Drive uploads, offline.

Every request is faked. Nothing here reaches Google, uploads a byte, or needs a
credential — the fake key is a real RSA key generated in-process purely so the
RS256 assertion can be signed, which is the one thing that cannot be stubbed
without stubbing the code under test.

The case this file exists for is the one that decides the whole design: a
service account has NO Drive storage of its own. Upload it to a normal My Drive
folder and Google answers 403 storageQuotaExceeded. The target must be a shared
drive — and the failure has to SAY that, because "upload failed" would send an
operator to check a key that is perfectly fine.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "drive-test-only")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from backend import drive  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (label, got, want))
        failures.append(label)


_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()).decode()

FAKE_CREDS = json.dumps({"client_email": "hq@zeroone.iam.gserviceaccount.com",
                         "private_key": _KEY, "type": "service_account"})


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.ok = 200 <= status < 300

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def _answer(self, method, url, **kw):
        self.calls.append({"method": method, "url": url, "params": kw.get("params"),
                           "files": kw.get("files"), "data": kw.get("data")})
        for (m, frag), resp in self.script.items():
            if m == method and frag in url:
                return resp
        raise AssertionError("unscripted %s %s" % (method, url))

    def get(self, url, **kw):
        return self._answer("GET", url, **kw)

    def post(self, url, **kw):
        return self._answer("POST", url, **kw)


TOKEN_OK = FakeResponse(200, {"access_token": "fake-token", "expires_in": 3600})


def configure(folder="folder-123"):
    os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = FAKE_CREDS
    os.environ["GOOGLE_DRIVE_FOLDER_ID"] = folder
    drive._TOKEN.update({"value": None, "expires": 0, "owner": None})


def unconfigure():
    os.environ.pop("GOOGLE_SERVICE_ACCOUNT_JSON", None)
    os.environ.pop("GOOGLE_DRIVE_FOLDER_ID", None)
    drive._TOKEN.update({"value": None, "expires": 0, "owner": None})


def with_session(script, fn):
    fake = FakeSession(script)
    real, drive._SESSION = drive._SESSION, fake
    try:
        return fn(), fake
    finally:
        drive._SESSION = real


def test_unconfigured_is_honest():
    unconfigure()
    check("not configured", drive.is_configured(), False)
    st = drive.status()
    check("state says so", st["state"], "not configured")
    check("and names both variables",
          "GOOGLE_SERVICE_ACCOUNT_JSON" in st["detail"] and "GOOGLE_DRIVE_FOLDER_ID" in st["detail"],
          True)
    try:
        drive.upload("x.pdf", b"data")
        check("uploading without config raises", True, False)
    except drive.DriveError as exc:
        check("uploading without config raises", "not configured" in str(exc), True)
    check("describe() stays quiet rather than raising", drive.describe(
        "https://drive.google.com/file/d/abc/view"), None)


def test_bad_credentials_json_is_explained():
    os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = "{not json"
    os.environ["GOOGLE_DRIVE_FOLDER_ID"] = "f"
    st = drive.status()
    check("a mangled key is an error", st["state"], "error")
    check("and says what it should be", "valid JSON" in (st["detail"] or ""), True)

    os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps({"client_email": "a@b.c"})
    st2 = drive.status()
    check("a key with no private_key is an error", st2["state"], "error")
    check("and names the missing field", "private_key" in (st2["detail"] or ""), True)
    unconfigure()


def test_the_storage_quota_trap_is_named():
    """THE case. A service account writing to My Drive fails, and must say why."""
    configure()
    script = {
        ("POST", "oauth2.googleapis.com"): TOKEN_OK,
        ("POST", "upload/drive/v3/files"): FakeResponse(403, {"error": {
            "message": "Service Accounts do not have storage quota.",
            "errors": [{"reason": "storageQuotaExceeded"}]}}),
    }
    def run():
        try:
            drive.upload("spec.pdf", b"bytes", "application/pdf")
            return "no error"
        except drive.DriveError as exc:
            return str(exc)
    msg, _ = with_session(script, run)
    check("it blames the folder, not the key", "SHARED DRIVE" in msg, True)
    check("and does NOT tell them to check the key", "key is current" in msg, False)
    unconfigure()


def test_a_missing_folder_explains_both_causes():
    configure()
    script = {("POST", "oauth2.googleapis.com"): TOKEN_OK,
              ("POST", "upload/drive/v3/files"): FakeResponse(404, {"error": {"message": "File not found"}})}
    def run():
        try:
            drive.upload("x.txt", b"x")
            return ""
        except drive.DriveError as exc:
            return str(exc)
    msg, _ = with_session(script, run)
    # Drive reports a folder it cannot SEE as missing, so the id being wrong and
    # the account not being a member are indistinguishable. Say both.
    check("names the wrong-id cause", "GOOGLE_DRIVE_FOLDER_ID" in msg, True)
    check("and the not-a-member cause", "added to the shared drive" in msg, True)
    unconfigure()


def test_a_good_upload_returns_what_hq_stores():
    configure()
    script = {("POST", "oauth2.googleapis.com"): TOKEN_OK,
              ("POST", "upload/drive/v3/files"): FakeResponse(200, {
                  "id": "file-9", "name": "Scope.pdf", "mimeType": "application/pdf",
                  "size": "2048", "webViewLink": "https://drive.google.com/file/d/file-9/view"})}
    (out, fake) = with_session(script, lambda: drive.upload("Scope.pdf", b"x" * 2048, "application/pdf"))
    check("returns the Drive link", out["url"], "https://drive.google.com/file/d/file-9/view")
    check("and the real name", out["filename"], "Scope.pdf")
    check("and the size", out["size"], 2048)

    upload_call = [c for c in fake.calls if "upload" in c["url"]][0]
    # Without supportsAllDrives the API pretends shared drives do not exist and
    # 404s a folder that is plainly there.
    check("supportsAllDrives was sent", upload_call["params"].get("supportsAllDrives"), "true")
    meta = json.loads(upload_call["files"]["metadata"][1])
    check("uploaded into the configured folder", meta["parents"], ["folder-123"])
    unconfigure()


def test_oversize_and_empty_are_refused_before_any_call():
    configure()
    fake = FakeSession({})          # any request at all would raise
    real, drive._SESSION = drive._SESSION, fake
    try:
        for label, blob in (("oversize", b"x" * (drive.MAX_UPLOAD_BYTES + 1)), ("empty", b"")):
            try:
                drive.upload("big.bin", blob)
                failures.append("accepted %s" % label)
                print("  FAIL accepted an %s file" % label)
            except drive.DriveError:
                pass
    finally:
        drive._SESSION = real
    check("neither reached the network", len(fake.calls), 0)
    unconfigure()


def test_status_rejects_a_my_drive_folder_before_anyone_tries():
    configure()
    # Reachable, and still unusable: no driveId means it is not in a shared drive.
    script = {("POST", "oauth2.googleapis.com"): TOKEN_OK,
              ("GET", "drive/v3/files/"): FakeResponse(200, {"id": "folder-123", "name": "My Stuff"})}
    st, _ = with_session(script, drive.status)
    check("a My Drive folder is an error", st["state"], "error")
    check("caught before an upload is attempted", "not in a shared drive" in (st["detail"] or ""), True)

    script2 = {("POST", "oauth2.googleapis.com"): TOKEN_OK,
               ("GET", "drive/v3/files/"): FakeResponse(200, {
                   "id": "folder-123", "name": "ZeroOne Files", "driveId": "0AB"})}
    st2, _ = with_session(script2, drive.status)
    check("a shared-drive folder is connected", st2["state"], "connected")
    check("and names it", "ZeroOne Files" in (st2["detail"] or ""), True)
    unconfigure()


def test_file_ids_are_read_from_every_link_shape():
    cases = [
        ("https://docs.google.com/document/d/1AbC-d/edit", "1AbC-d"),
        ("https://docs.google.com/spreadsheets/d/1Sheet9/edit#gid=0", "1Sheet9"),
        ("https://docs.google.com/presentation/d/1Deck7/edit", "1Deck7"),
        ("https://drive.google.com/file/d/1File3/view", "1File3"),
        ("https://drive.google.com/drive/folders/1Folder2", "1Folder2"),
        ("https://drive.google.com/open?id=1Open1", "1Open1"),
        # The published shape. Without (?:e/)? this returns the literal "e".
        ("https://docs.google.com/spreadsheets/d/e/2PACX-abc/pubhtml", "2PACX-abc"),
        ("https://example.com/not-drive.pdf", None),
        ("", None),
    ]
    for url, want in cases:
        check("id from %-56s" % (url[:56] or "(empty)"), drive.file_id_from(url), want)


def test_describe_never_breaks_an_attachment():
    """A lookup that fails must not stop a link being filed."""
    configure()
    for label, script in (
        ("a file we cannot see", {("POST", "oauth2.googleapis.com"): TOKEN_OK,
                                  ("GET", "drive/v3/files/"): FakeResponse(404, {})}),
        ("a refused token", {("POST", "oauth2.googleapis.com"): FakeResponse(401, {"error": "invalid_grant"})}),
    ):
        # A token cached by the previous sub-case would skip the token call
        # entirely and make the next script unreachable.
        drive._TOKEN.update({"value": None, "expires": 0, "owner": None})
        out, _ = with_session(script, lambda: drive.describe(
            "https://docs.google.com/document/d/1AbC/edit"))
        check("describe returns None on %s" % label, out, None)

    ok = {("POST", "oauth2.googleapis.com"): TOKEN_OK,
          ("GET", "drive/v3/files/"): FakeResponse(200, {
              "id": "1AbC", "name": "Ranger scope.docx",
              "mimeType": "application/vnd.google-apps.document", "size": "8100"})}
    out, _ = with_session(ok, lambda: drive.describe("https://docs.google.com/document/d/1AbC/edit"))
    check("and the real filename when it can", out["filename"], "Ranger scope.docx")
    check("with its size", out["size"], 8100)
    unconfigure()


def test_a_rotated_key_is_not_ignored():
    """A cached token must not outlive the credentials it was minted for.

    Google issues these for an hour. Cache them without remembering WHOSE they
    are and a rotated service-account key is silently ignored until the old
    token expires — the app keeps authenticating as an identity that may have
    just been revoked.
    """
    configure()
    first = {("POST", "oauth2.googleapis.com"): FakeResponse(
        200, {"access_token": "token-for-old-key", "expires_in": 3600})}
    tok1, _ = with_session(first, drive._access_token)
    check("mints a token", tok1, "token-for-old-key")

    # Same process, same expiry window, DIFFERENT service account.
    rotated = json.loads(FAKE_CREDS)
    rotated["client_email"] = "hq-rotated@zeroone.iam.gserviceaccount.com"
    os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps(rotated)

    second = {("POST", "oauth2.googleapis.com"): FakeResponse(
        200, {"access_token": "token-for-new-key", "expires_in": 3600})}
    tok2, fake = with_session(second, drive._access_token)
    check("a rotated key mints a NEW token", tok2, "token-for-new-key")
    check("it really did re-authenticate", len(fake.calls), 1)

    # ...and an unchanged key still uses the cache rather than re-signing.
    tok3, fake3 = with_session({}, drive._access_token)   # any call would raise
    check("an unchanged key reuses the cached token", tok3, "token-for-new-key")
    check("with no request at all", len(fake3.calls), 0)
    unconfigure()


TESTS = [
    ("unconfigured is honest", test_unconfigured_is_honest),
    ("a rotated key is not ignored", test_a_rotated_key_is_not_ignored),
    ("a mangled key is explained", test_bad_credentials_json_is_explained),
    ("the storage-quota trap is named", test_the_storage_quota_trap_is_named),
    ("a missing folder explains both causes", test_a_missing_folder_explains_both_causes),
    ("a good upload returns what HQ stores", test_a_good_upload_returns_what_hq_stores),
    ("oversize and empty never reach the network", test_oversize_and_empty_are_refused_before_any_call),
    ("status rejects a My Drive folder", test_status_rejects_a_my_drive_folder_before_anyone_tries),
    ("file ids from every link shape", test_file_ids_are_read_from_every_link_shape),
    ("describe never breaks an attachment", test_describe_never_breaks_an_attachment),
]

if __name__ == "__main__":
    print("Google Drive")
    for label, fn in TESTS:
        print("\n%s" % label)
        fn()
    unconfigure()
    print("\n%s" % ("-" * 58))
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("all green")
