"""The Call / WhatsApp / Email buttons on a customer, end to end.

Needs a running server: `python tests/reach_test.py --base http://127.0.0.1:8077`.

The check worth having here is the MERGE one. A thread opened from a customer
and an inbound message from that same person arrive with wildly different
formatting of the same number ("+91 98251 15308" against a stored "9825115308").
If the button keyed its thread any differently from `comms.ingest`, one person
would end up with two threads and half a history in each, and nothing would look
broken until someone went looking for a reply that was filed elsewhere.
"""
import argparse
import json
import os
import urllib.request

_args = argparse.ArgumentParser()
_args.add_argument("--base", default="http://127.0.0.1:8077")
_args.add_argument("--password", default=os.environ.get("SEED_ADMIN_PASSWORD", "local-admin-test-pw"))
_opt = _args.parse_args()
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

st, status = call("GET", "/api/comms/status", tok)
check("comms status route exists", st, 200)
check("it reports whatsapp", "whatsapp" in status, True)
check("it reports email", "email" in status, True)
check("email is honestly unconfigured here", status["email"]["configured"], False)
print("      email detail: %s\n" % (status["email"]["detail"] or "")[:70])

# A customer with a full international number and an email.
st, cust = call("POST", "/api/customers", tok, {
    "display_name": "Reach Test Co", "kind": "customer", "status": "Active",
    "phone": "+91-9825115308", "email": "reach@example.com",
})
check("created a customer", st, 200)
cid = cust["id"]

# WhatsApp: opens a thread keyed the way inbound would key it.
st, wa = call("POST", "/api/customers/%s/conversations" % cid, tok,
              {"channel_type": "whatsapp"})
check("whatsapp thread opens", st, 200)
check("it was created", wa.get("created"), True)
check("thread key is the last 10 digits (matches inbound)",
      wa.get("contact_identifier"), "9825115308")
check("but the dialable address is kept whole", wa.get("address"), "+91-9825115308")

# Idempotence: the button pressed twice must not make a second thread.
st, wa2 = call("POST", "/api/customers/%s/conversations" % cid, tok,
               {"channel_type": "whatsapp"})
check("pressing it again finds the same thread", wa2.get("conversation_id"),
      wa.get("conversation_id"))
check("and did not create one", wa2.get("created"), False)

# THE MERGE TEST: an inbound message from the same person, formatted totally
# differently, must land in that SAME thread — not a second one.
st, inbound = call("POST", "/api/comms/inbound", None, {
    "channel_type": "whatsapp", "from": "919825115308",
    "body": "Hello from the customer", "external_id": "reach-test-1",
})
# webhook is token-gated; send the token header instead
req = urllib.request.Request(BASE + "/api/comms/inbound", method="POST")
req.add_header("Content-Type", "application/json")
req.add_header("X-HQ-Webhook-Token", os.environ.get("COMMS_WEBHOOK_TOKEN", "local-webhook-secret"))
try:
    with urllib.request.urlopen(req, json.dumps({
        "channel_type": "whatsapp", "from": "+91 98251 15308",
        "body": "Hello from the customer", "external_id": "reach-test-1",
    }).encode()) as r:
        inbound = json.loads(r.read() or b"{}")
        ist = r.status
except urllib.error.HTTPError as e:
    ist, inbound = e.code, json.loads(e.read() or b"{}")
check("an inbound message is accepted", ist, 200)
check("differently-formatted inbound lands in the SAME thread",
      inbound.get("conversation_id"), wa.get("conversation_id"))

# Email thread.
st, em = call("POST", "/api/customers/%s/conversations" % cid, tok,
              {"channel_type": "email"})
check("email thread opens", st, 200)
check("email thread key is the lowercased address",
      em.get("contact_identifier"), "reach@example.com")
check("it is a different thread from whatsapp",
      em.get("conversation_id") != wa.get("conversation_id"), True)
check("and reports sending is off", em.get("sending_enabled"), False)

# Sending on the email thread must now EXPLAIN itself, not return detail=null.
st, sent = call("POST", "/api/conversations/%s/messages" % em["conversation_id"], tok,
                {"body": "Test email body"})
check("email send returns 200 with the message recorded", st, 200)
check("it admits nothing was delivered", sent.get("delivered"), False)
check("delivery_status is recorded", sent.get("delivery_status"), "recorded")
check("and it SAYS WHY (was silently null before)", bool(sent.get("detail")), True)
print("      detail: %s\n" % (sent.get("detail") or "")[:80])

# A customer with nothing on file must not get an unaddressable thread.
st, bare = call("POST", "/api/customers", tok,
                {"display_name": "No Contact Co", "kind": "customer", "status": "Active"})
st2, err = call("POST", "/api/customers/%s/conversations" % bare["id"], tok,
                {"channel_type": "email"})
check("a customer with no address is refused, not given a dead thread", st2, 400)
check("and the error names the fix", "Add one" in (err.get("detail") or ""), True)

# Call logging.
st, logged = call("POST", "/api/customers/%s/calls" % cid, tok, {
    "subject": "Intro call", "body": "Discussed the Ranger System",
    "duration_minutes": 25, "outcome": "positive",
})
check("a call is logged", st, 200)
check("it is typed as a call", logged.get("activity_type"), "call")
check("with its subject", logged.get("subject"), "Intro call")

_, trail = call("GET", "/api/audit?entity_type=parties&entity_id=%s" % cid, tok)
check("the call shows in the customer's audit trail",
      "call" in [e["action"] for e in trail.get("entries", [])], True)

# Cleanup — conversations first. A conversation outliving its party leaves a
# dangling party_id that the next suite reads as a thread whose customer
# vanished, which is a real-looking failure with no real cause.
for c in (wa.get("conversation_id"), em.get("conversation_id")):
    if c:
        call("DELETE", "/api/conversations/%s" % c, tok)
call("DELETE", "/api/customers/%s" % cid, tok)
call("DELETE", "/api/customers/%s" % bare["id"], tok)

_, left = call("GET", "/api/conversations?limit=200", tok)
check("cleanup left nothing behind",
      [r for r in left.get("rows", []) if r.get("contact_name") == "Reach Test Co"], [])

print("\n" + "-" * 58)
print("FAILED: %s" % ", ".join(fails) if fails else "all green")
raise SystemExit(1 if fails else 0)
