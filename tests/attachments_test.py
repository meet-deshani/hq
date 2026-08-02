#!/usr/bin/env python3
"""Attaching files to a record, end to end.

Needs a running server:
    python tests/attachments_test.py --base http://127.0.0.1:8077

HQ stores a LINK, never the bytes — its container has no disk that survives a
deploy — so what is worth proving is that a pasted URL comes back correctly
TYPED, that a junk URL is refused rather than filed, and that unlinking removes
HQ's reference without pretending to have deleted anything at Google.
"""

import argparse
import json
import os
import urllib.request

_p = argparse.ArgumentParser()
_p.add_argument("--base", default="http://127.0.0.1:8077")
_p.add_argument("--password", default=os.environ.get("SEED_ADMIN_PASSWORD", "local-admin-test-pw"))
_opt = _p.parse_args()
BASE = _opt.base
fails = []


def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (label, got, want))
        fails.append(label)


_, auth = call("POST", "/api/auth/login",
               body={"email": "meet@dotsai.in", "password": _opt.password})
tok = auth["access_token"]
print("logged in\n")

st, cust = call("POST", "/api/customers", tok,
                {"display_name": "Attach Test Co", "kind": "customer", "status": "Active"})
check("created a customer to attach to", st, 200)
cid = cust["id"]

# Every Google surface Meet named, plus the older Drive share shapes.
CASES = [
    ("https://docs.google.com/document/d/1AbC_dEf-123/edit", "Google Doc"),
    ("https://docs.google.com/spreadsheets/d/1XyZ987/edit#gid=0", "Google Sheet"),
    ("https://docs.google.com/presentation/d/1PqR456/edit", "Google Slides"),
    ("https://docs.google.com/forms/d/1FoRm789/edit", "Google Form"),
    ("https://drive.google.com/drive/folders/1FolDer00", "Drive folder"),
    ("https://drive.google.com/file/d/1FiLe111/view", "Drive file"),
    ("https://drive.google.com/open?id=1OpEn222", "Drive file"),
    ("https://example.com/spec.pdf", "example.com"),
]
made = []
for url, want_kind in CASES:
    st, a = call("POST", "/api/customers/%s/attachments" % cid, tok, {"url": url})
    check("attached %-46s -> %s" % (url[:46], want_kind), (st, a.get("kind")), (200, want_kind))
    if a.get("id"):
        made.append(a["id"])

# With no name given, the link's own kind names it — never blank.
st, named = call("POST", "/api/customers/%s/attachments" % cid, tok,
                 {"url": "https://docs.google.com/document/d/1NoName/edit"})
check("an unnamed attachment is not nameless", named.get("filename"), "Google Doc")
made.append(named["id"])
st, custom = call("POST", "/api/customers/%s/attachments" % cid, tok,
                  {"url": "https://docs.google.com/document/d/1Named/edit", "filename": "Scope of work"})
check("a supplied name is kept", custom.get("filename"), "Scope of work")
made.append(custom["id"])

# Junk must be refused, not filed.
for bad, why in (("", "empty"), ("   ", "blank"), ("javascript:alert(1)", "not http"),
                 ("drive.google.com/file/d/x", "no scheme")):
    st, err = call("POST", "/api/customers/%s/attachments" % cid, tok, {"url": bad})
    check("refused a %s url" % why, st, 400)

# Readable back, newest first.
st, listed = call("GET", "/api/customers/%s/attachments" % cid, tok)
check("attachments list reads back", st, 200)
check("every attachment is listed", len(listed.get("attachments", [])), len(made))

# ...and on the record itself, so the detail page needs no second call.
_, rec = call("GET", "/api/customers/%s" % cid, tok)
check("the record carries its attachments", len(rec.get("_attachments", [])), len(made))

_, trail = call("GET", "/api/audit?entity_type=parties&entity_id=%s" % cid, tok)
check("attaching is audited", "attach" in [e["action"] for e in trail.get("entries", [])], True)

# Unlinking removes HQ's reference only.
st, gone = call("DELETE", "/api/customers/%s/attachments/%s" % (cid, made[0]), tok)
check("an attachment can be unlinked", st, 200)
_, after = call("GET", "/api/customers/%s/attachments" % cid, tok)
check("and is gone from the list", len(after.get("attachments", [])), len(made) - 1)

st, _ = call("DELETE", "/api/customers/%s/attachments/%s" % (cid, made[0]), tok)
check("unlinking it twice is a 404, not a 500", st, 404)

# An attachment belongs to ONE record: another record's id must not reach it.
st2, other = call("POST", "/api/customers", tok,
                  {"display_name": "Other Attach Co", "kind": "customer", "status": "Active"})
st3, _ = call("DELETE", "/api/customers/%s/attachments/%s" % (other["id"], made[1]), tok)
check("cannot unlink another record's attachment", st3, 404)

# Deleting the record takes its attachments with it (crud.py's cascade).
call("DELETE", "/api/customers/%s" % cid, tok)
call("DELETE", "/api/customers/%s" % other["id"], tok)
st, after_del = call("GET", "/api/customers/%s/attachments" % cid, tok)
check("a deleted record's attachments are unreachable", st, 404)

print("\n" + "-" * 58)
print("FAILED: %s" % ", ".join(fails) if fails else "all green")
raise SystemExit(1 if fails else 0)
