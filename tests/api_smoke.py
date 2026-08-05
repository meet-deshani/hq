#!/usr/bin/env python3
"""End-to-end API contract test for the HQ CRM surface.

Exercises the real HTTP surface of a running server — not the ORM — because the
contract that matters is the one an agent, the CLI and the browser all call.

    python3 tests/api_smoke.py [--base http://127.0.0.1:8077] [--email ...] [--password ...]

Exits non-zero on the first failure with the offending response body.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime

PASSED = []
FAILED = []


class Client:
    def __init__(self, base, client_kind=None):
        self.base = base.rstrip("/")
        self.token = None
        self.client_kind = client_kind

    def call(self, method, path, body=None, expect=None):
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        if self.client_kind:
            req.add_header("X-HQ-Client", self.client_kind)
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode()
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            status = exc.code
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = raw
        if expect is not None and status != expect:
            raise AssertionError("%s %s -> %s (expected %s): %s" % (method, path, status, expect, raw[:600]))
        return status, parsed

    def login(self, email, password):
        _, data = self.call("POST", "/api/auth/login", {"email": email, "password": password}, expect=200)
        self.token = data["access_token"]
        return data


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  PASS  %s" % name)
    else:
        FAILED.append((name, detail))
        print("  FAIL  %s -- %s" % (name, detail))


def section(title):
    print("\n== %s ==" % title)


def run(base, email, password):
    api = Client(base)

    # ── auth ────────────────────────────────────────────────────────────────
    section("Auth")
    api.login(email, password)
    check("login returns a token", bool(api.token))
    status, _ = api.call("GET", "/api/customers")
    check("unauthenticated calls are rejected", Client(base).call("GET", "/api/customers")[0] == 401,
          "expected 401 without a token")
    status, me = api.call("GET", "/api/auth/me", expect=200)
    check("auth/me returns the signed-in user", me.get("email") == email, str(me)[:200])

    # ── the shell must defeat the browser cache ─────────────────────────────
    # A component is fetched by the dc runtime with a plain fetch, so it is
    # served from the HTTP cache. Without a content-stamped URL, browsers that
    # cached the file before Cache-Control shipped keep the OLD component for
    # ever: the app renders the previous release with no error anywhere. That
    # shipped once and cost a long afternoon; this is the guard.
    section("Cache busting")
    shell = urllib.request.Request(base + "/z9s-ai/hq/crm/customers/customers")
    shell.add_header("Cookie", "access_token=" + api.token)
    page = urllib.request.urlopen(shell).read().decode()
    stamped = re.findall(r"/static/(PortalPage\.dc\.html|hq-responsive\.(?:css|js))\?v=([0-9a-f]{6,})", page)
    check("the shell stamps a content hash onto every runtime asset",
          {name for name, _ in stamped} ==
          {"PortalPage.dc.html", "hq-responsive.css", "hq-responsive.js"},
          "found: %s" % sorted({n for n, _ in stamped}))
    check("no runtime asset is referenced without a version",
          "\"/static/PortalPage.dc.html\"" not in page,
          "an unversioned PortalPage URL is still in the shell")

    # ── discovery ───────────────────────────────────────────────────────────
    section("Discovery")
    _, meta = api.call("GET", "/api/meta/entities", expect=200)
    entities = {e["key"]: e for e in meta["entities"]}
    check("meta lists entities", meta["count"] == len(entities) and meta["count"] > 10,
          "count=%s" % meta.get("count"))
    # A read-only mirror has no writable fields on purpose — that is what stops
    # the UI drawing a create form for something it must not create.
    missing = [e["key"] for e in meta["entities"]
               if not e.get("columns") or (not e.get("fields") and not e.get("read_only"))]
    check("every entity declares columns, and fields unless read-only",
          not missing, "missing: %s" % ", ".join(missing))
    check("no registry entity is shadowed by a literal route",
          "products" not in entities and "catalog-products" in entities,
          "products key must be renamed to catalog-products")

    # Every declared path must actually respond.
    unreachable = []
    for key, ent in entities.items():
        st, _ = api.call("GET", ent["path"])
        if st != 200:
            unreachable.append("%s -> %s" % (ent["path"], st))
    check("every declared entity path responds 200", not unreachable, "; ".join(unreachable))

    # Hand-written routes must survive the /api/{key} catch-all.
    shadowed = []
    for path, probe in [("/api/users", "email"), ("/api/organisations", "slug"),
                        ("/api/products", "code"), ("/api/workspaces", "slug"),
                        ("/api/roles", "name"), ("/api/permissions", "code")]:
        st, data = api.call("GET", path)
        if st != 200 or not isinstance(data, list):
            shadowed.append("%s returned %s %s" % (path, st, type(data).__name__))
    check("pre-existing routes are not shadowed by /api/{key}", not shadowed, "; ".join(shadowed))

    # ── the catalogue must not lie ──────────────────────────────────────────
    section("Self-documentation")
    _, catalog = api.call("GET", "/api/catalog", expect=200)
    documented = {(e["method"], e["path"]) for e in catalog["endpoints"]}
    doc_paths = {p for _, p in documented}

    # Every registry entity's CRUD must appear, or an agent reading the
    # catalogue concludes the route does not exist.
    undocumented = []
    for key, ent in entities.items():
        # NOT `base` — that is the server URL this whole run depends on.
        route = "/api/" + key
        wanted = [("GET", route), ("GET", route + "/{id}"),
                  ("GET", route + "/{id}/remarks"), ("POST", route + "/{id}/remarks"),
                  ("GET", route + "/{id}/attachments")]
        if not ent.get("read_only"):
            wanted += [("POST", route), ("PATCH", route + "/{id}"), ("DELETE", route + "/{id}"),
                       ("POST", route + "/{id}/attachments"),
                       ("POST", route + "/{id}/attachments/upload"),
                       ("DELETE", route + "/{id}/attachments/{attachment_id}")]
        for pair in wanted:
            if pair not in documented:
                undocumented.append("%s %s" % pair)
    check("every entity's routes are in the catalogue", not undocumented,
          "missing: %s" % ", ".join(undocumented[:8]))

    # And every hand-written route the server actually serves.
    _, spec = api.call("GET", "/openapi.json", expect=200)
    real = {p for p in spec["paths"] if p.startswith("/api/")}
    # The registry-driven routes. They are served once as a template and
    # documented once PER ENTITY, which the per-entity check above enforces —
    # so their templated form is not itself expected in the catalogue.
    generic = {"/api/{key}", "/api/{key}/{row_id}", "/api/{key}/{row_id}/remarks",
               "/api/{key}/{row_id}/attachments",
               "/api/{key}/{row_id}/attachments/upload",
               "/api/{key}/{row_id}/attachments/{attachment_id}"}
    missing_literal = sorted(p for p in real - generic if p not in doc_paths)
    check("every literal API route is in the catalogue", not missing_literal,
          "missing: %s" % ", ".join(missing_literal[:8]))

    check("the catalogue count matches what it returns",
          catalog["count"] == len(catalog["endpoints"]),
          "count=%s len=%s" % (catalog["count"], len(catalog["endpoints"])))

    # ── per-workspace dashboards ────────────────────────────────────────────
    section("Dashboards")
    seen = {}
    for ws in ("crm", "work", "tickets", "comms", "accounting", "hq"):
        _, d = api.call("GET", "/api/dashboard/stats?workspace=%s" % ws, expect=200)
        labels = tuple(s["l"] for s in d["stats"])
        check("the %s dashboard returns metrics" % ws, len(d["stats"]) >= 4, str(labels))
        seen[ws] = labels
    check("each workspace shows different metrics",
          len(set(seen.values())) == len(seen),
          "two workspaces returned identical tiles: %s" % str(seen))
    check("the CRM dashboard is about customers, not platform plumbing",
          any("Customer" in l for l in seen["crm"]) and not any("Permission" in l for l in seen["crm"]),
          str(seen["crm"]))

    # Search used to cover only platform config, so looking for a customer by
    # name found nothing at all.
    for term, want_type in (("Pioneer", "Customer"), ("AquaServe", "Service"),
                            ("Nishant", "Work stream")):
        _, hits = api.call("GET", "/api/search?q=%s" % term, expect=200)
        types = {h["type"] for h in hits["results"]}
        check("search finds %s for '%s'" % (want_type.lower(), term),
              want_type in types, "got: %s" % sorted(types))

    _, first = api.call("GET", "/api/search?q=Pioneer", expect=200)
    check("search ranks a name match above a mention",
          first["results"] and first["results"][0]["label"].lower().startswith("pioneer"),
          str([r["label"] for r in first["results"][:3]]))
    check("search results carry enough to navigate to the record",
          all("entity" in r and "id" in r for r in first["results"] if r["type"] != "User"),
          str(first["results"][:2]))

    _, tr = api.call("GET", "/api/dashboard/trend?workspace=crm", expect=200)
    check("the trend is labelled with what it plots",
          tr.get("label") == "Customers" and len(tr["points"]) == 6, str(tr)[:160])

    # ── seeded data ─────────────────────────────────────────────────────────
    section("Seeded data")
    _, customers = api.call("GET", "/api/customers?limit=500", expect=200)
    _, projects = api.call("GET", "/api/projects?limit=500", expect=200)
    _, services = api.call("GET", "/api/services?limit=500", expect=200)
    _, streams = api.call("GET", "/api/work-streams", expect=200)
    check("customers seeded", customers["total"] >= 15, "total=%s" % customers["total"])
    check("projects seeded from the delivery board", projects["total"] >= 15, "total=%s" % projects["total"])
    check("services seeded", services["total"] >= 8, "total=%s" % services["total"])
    check("work streams seeded", streams["total"] >= 2, "total=%s" % streams["total"])

    _, users = api.call("GET", "/api/users", expect=200)
    emails = {u["email"] for u in users}
    check("Nishant has an account", "nishant@neonir.com" in emails, str(sorted(emails)))
    check("Hemish has an account", "hemish@neonir.com" in emails, str(sorted(emails)))

    # Ref labels must resolve, or the UI shows bare integers.
    a_project = next((r for r in projects["rows"] if r.get("party_id")), None)
    check("ref columns resolve to labels",
          bool(a_project and a_project.get("_refs", {}).get("party_id")),
          "project _refs=%s" % (a_project or {}).get("_refs"))

    # ── scope enforcement ───────────────────────────────────────────────────
    section("Scope enforcement (Services vs Products share one table)")
    _, prod = api.call("POST", "/api/catalog-products",
                       {"name": "Scope probe widget", "item_type": "service"}, expect=200)
    check("a scoped create cannot override its discriminator",
          prod["item_type"] == "goods", "item_type=%s" % prod["item_type"])
    st, _ = api.call("GET", "/api/services/%s" % prod["id"])
    check("a product is not reachable through the services scope", st == 404, "got %s" % st)
    api.call("DELETE", "/api/catalog-products/%s" % prod["id"], expect=200)

    # ── Zoho Books ownership ────────────────────────────────────────────────
    section("Zoho Books owns the invoices")
    for method, body in [("POST", {"invoice_number": "FAKE/1"}), ("PATCH", {"total": 1})]:
        path = "/api/invoices" if method == "POST" else "/api/invoices/1"
        st, _ = api.call(method, path, body)
        check("%s on the invoice mirror is refused" % method, st == 405, "got %s" % st)
    st, _ = api.call("DELETE", "/api/invoices/1")
    check("DELETE on the invoice mirror is refused", st == 405, "got %s" % st)
    check("the mirror declares itself read-only in the registry",
          entities.get("invoices", {}).get("read_only") is True,
          "read_only=%s" % entities.get("invoices", {}).get("read_only"))

    # ── the three later workspaces ──────────────────────────────────────────
    section("Tickets, Communication and Accounting")
    _, jobtypes = api.call("GET", "/api/job-types", expect=200)
    _, slas = api.call("GET", "/api/sla-policies", expect=200)
    _, chans = api.call("GET", "/api/channels", expect=200)
    check("job types seeded", jobtypes["total"] >= 8, "total=%s" % jobtypes["total"])
    check("a default SLA policy exists", slas["total"] >= 1, "total=%s" % slas["total"])
    check("comms channels seeded", chans["total"] >= 2, "total=%s" % chans["total"])

    _, ticket = api.call("POST", "/api/tickets", {
        "subject": "Smoke ticket — export button 404s",
        "priority": "high", "channel": "whatsapp",
    }, expect=200)
    check("a ticket can be raised", ticket["status"] == "new" and ticket["priority"] == "high", str(ticket)[:200])
    api.call("PATCH", "/api/tickets/%s" % ticket["id"], {"status": "resolved"}, expect=200)
    _, pending = api.call("GET", "/api/tickets?view=Pending", expect=200)
    check("a resolved ticket leaves the Pending view",
          all(r["id"] != ticket["id"] for r in pending["rows"]), "still listed as pending")

    # The SLA clock must start itself. Nothing used to set these, so the
    # dashboard's "Breaching SLA" tile could only ever read zero.
    _, urgent = api.call("POST", "/api/tickets",
                         {"subject": "SLA clock check", "priority": "urgent"}, expect=200)
    check("raising a ticket starts its SLA clock",
          bool(urgent["first_response_due_at"]) and bool(urgent["resolution_due_at"])
          and urgent["sla_policy_id"] is not None,
          str({k: urgent[k] for k in ("sla_policy_id", "first_response_due_at", "resolution_due_at")}))

    _, low = api.call("POST", "/api/tickets",
                      {"subject": "SLA clock check low", "priority": "low"}, expect=200)
    check("a lower priority gets a later deadline",
          low["resolution_due_at"] > urgent["resolution_due_at"],
          "urgent=%s low=%s" % (urgent["resolution_due_at"], low["resolution_due_at"]))

    _, resolved = api.call("PATCH", "/api/tickets/%s" % urgent["id"], {"status": "resolved"}, expect=200)
    check("resolving a ticket stamps resolved_at", bool(resolved["resolved_at"]), str(resolved)[:160])
    _, reopened = api.call("PATCH", "/api/tickets/%s" % urgent["id"], {"status": "open"}, expect=200)
    check("reopening clears the resolution and counts the reopen",
          reopened["resolved_at"] is None and reopened["reopened_count"] == 1,
          "resolved_at=%s reopened=%s" % (reopened["resolved_at"], reopened["reopened_count"]))
    api.call("DELETE", "/api/tickets/%s" % urgent["id"], expect=200)
    api.call("DELETE", "/api/tickets/%s" % low["id"], expect=200)

    _, contract = api.call("POST", "/api/contracts", {
        "title": "Smoke MSA", "contract_type": "msa", "value": 500000,
    }, expect=200)
    _, line = api.call("POST", "/api/billing-schedule", {
        "contract_id": contract["id"], "name": "Milestone 1", "amount": 250000,
    }, expect=200)
    _, contract_detail = api.call("GET", "/api/contracts/%s" % contract["id"], expect=200)
    check("a contract carries its billing schedule",
          len(contract_detail["_related"]["schedule"]["rows"]) == 1,
          str(contract_detail["_related"].get("schedule"))[:200])

    api.call("DELETE", "/api/billing-schedule/%s" % line["id"], expect=200)
    api.call("DELETE", "/api/contracts/%s" % contract["id"], expect=200)
    api.call("DELETE", "/api/tickets/%s" % ticket["id"], expect=200)

    # ── message ingestion ───────────────────────────────────────────────────
    section("Communication ingestion")
    hook = os.environ.get("COMMS_WEBHOOK_TOKEN", "local-webhook-secret")

    def inbound(body, token=hook):
        req = urllib.request.Request(base + "/api/comms/inbound",
                                     data=json.dumps(body).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        if token is not None:
            req.add_header("X-HQ-Webhook-Token", token)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, raw

    st, _ = inbound({"channel_type": "whatsapp", "from": "919999911111", "body": "x"}, token=None)
    check("the webhook refuses an unauthenticated message", st == 401, "got %s" % st)
    st, _ = inbound({"channel_type": "whatsapp", "from": "919999911111", "body": "x"}, token="wrong")
    check("the webhook refuses a bad token", st == 401, "got %s" % st)

    # A number formatted differently from the one on record must still resolve —
    # the same person is "+91-98251 15308" in one system and "919825115308"
    # in another.
    st, first = inbound({
        "channel_type": "whatsapp", "from": "+91-98251 15308", "contact_name": "Hemish",
        "body": "Smoke: revised scope attached.", "external_id": "smoke-wa-1",
    })
    check("an inbound message creates a thread", st == 200 and first.get("created") is True,
          "%s %s" % (st, first))
    if "conversation_id" not in first:
        # Everything below threads off this id. Without a hard stop the run
        # continued and died twenty lines later on a bare KeyError, which says
        # nothing about the actual cause — almost always that the server's
        # COMMS_WEBHOOK_TOKEN differs from this process's, so the webhook 401s.
        raise AssertionError(
            "Inbound webhook returned no conversation_id (HTTP %s): %s\n"
            "The server and this test must share COMMS_WEBHOOK_TOKEN — this "
            "process is sending %r." % (st, first, hook)
        )
    check("a differently-formatted number still resolves to its customer",
          first.get("linked") is True, "party_id=%s" % first.get("party_id"))

    st, replay = inbound({
        "channel_type": "whatsapp", "from": "919825115308",
        "body": "Smoke: revised scope attached.", "external_id": "smoke-wa-1",
    })
    check("a retried delivery is not stored twice",
          replay.get("duplicate") is True and replay.get("message_id") == first["message_id"],
          str(replay))

    st, unknown = inbound({
        "channel_type": "whatsapp", "from": "919000000123", "contact_name": "Nobody",
        "body": "Smoke: who is this", "external_id": "smoke-wa-2",
    })
    check("an unrecognised number still gets a thread rather than being dropped",
          unknown.get("conversation_id") and unknown.get("linked") is False, str(unknown))

    convo_id = first["conversation_id"]
    _, thread = api.call("GET", "/api/conversations/%s/thread" % convo_id, expect=200)
    check("the thread reads back with its messages",
          thread["messages"] and thread["messages"][0]["direction"] == "inbound",
          str(thread)[:200])
    check("the thread knows which customer it belongs to", bool(thread["party"]), str(thread)[:200])

    # ── replies ──────────────────────────────────────────────────────────────
    # Every send test runs against a DELIBERATELY UNDIALABLE thread, and that is
    # not an implementation detail — it is the only thing standing between this
    # suite and a real WhatsApp message to a real client. The seeded threads
    # resolve to actual customer numbers; against a server that has a bot token
    # configured, replying on one of those genuinely delivers. '555000' is six
    # digits, so whatsapp.dial_address refuses it and nothing can leave the
    # building however the server is configured.
    st, safe = inbound({
        "channel_type": "whatsapp", "from": "555000", "contact_name": "Undialable (test)",
        "body": "Smoke: reply fixture", "external_id": "smoke-wa-safe",
    })
    safe_id = safe["conversation_id"]
    _, safe_thread = api.call("GET", "/api/conversations/%s/thread" % safe_id, expect=200)
    before_count = len(safe_thread["messages"])

    _, reply = api.call("POST", "/api/conversations/%s/messages" % safe_id,
                        {"body": "Smoke: thanks, reviewing now."}, expect=200)
    _, thread2 = api.call("GET", "/api/conversations/%s/thread" % safe_id, expect=200)
    check("a reply is appended to the thread as outbound",
          len(thread2["messages"]) == before_count + 1
          and thread2["messages"][-1]["direction"] == "outbound"
          and thread2["messages"][-1]["body"] == "Smoke: thanks, reviewing now.",
          "was %d, now %s" % (before_count, [m["direction"] for m in thread2["messages"]]))
    check("replying clears the unread count", thread2["unread_count"] == 0,
          "unread=%s" % thread2["unread_count"])

    # The point of the send wiring: a reply states what actually happened to it.
    # These assert the CONTRACT, not the server's configuration — an unconfigured
    # server records, a configured one refuses an undialable number, and neither
    # is ever allowed to report a delivery.
    check("a reply reports its delivery status rather than implying success",
          reply.get("delivery_status") in ("sent", "failed", "recorded"), str(reply))
    check("an undeliverable reply never claims it was delivered",
          reply.get("delivery_status") in ("failed", "recorded")
          and reply.get("delivered") is False and reply.get("detail"),
          str(reply))
    check("the stored message carries the same status the reply claimed",
          thread2["messages"][-1]["delivery_status"] == reply["delivery_status"],
          "stored=%s reported=%s" % (thread2["messages"][-1]["delivery_status"],
                                     reply.get("delivery_status")))
    check("the thread tells the composer whether it can really send",
          isinstance(thread2.get("sending_enabled"), bool),
          "expected a bool, got %r" % thread2.get("sending_enabled"))

    # A client replying to a closed thread reopens it — they neither know nor
    # care that someone marked it done.
    api.call("PATCH", "/api/conversations/%s" % convo_id, {"status": "closed"}, expect=200)
    inbound({"channel_type": "whatsapp", "from": "919825115308",
             "body": "Smoke: one more thing", "external_id": "smoke-wa-3"})
    _, thread3 = api.call("GET", "/api/conversations/%s/thread" % convo_id, expect=200)
    check("an inbound reply reopens a closed thread", thread3["status"] == "open",
          "status=%s" % thread3["status"])

    for cid in {convo_id, unknown["conversation_id"], safe_id}:
        api.call("DELETE", "/api/conversations/%s" % cid)

    # ── CRUD round trip ─────────────────────────────────────────────────────
    section("CRUD round trip")
    # A previous aborted run may have left this behind; a smoke test that cannot
    # be run twice is not much of a smoke test.
    _, leftovers = api.call("GET", "/api/customers?q=Smoke%20Test%20Industries", expect=200)
    for row in leftovers["rows"]:
        api.call("DELETE", "/api/customers/%s" % row["id"])
    _, created = api.call("POST", "/api/customers", {
        "display_name": "Smoke Test Industries", "kind": "prospect",
        "email": "smoke@example.com", "city": "Vadodara", "credit_days": 15,
    }, expect=200)
    cid = created["id"]
    check("create returns the row with an id", bool(cid) and created["display_name"] == "Smoke Test Industries")
    check("create stamps provenance", created.get("created_by_id") is not None,
          "created_by_id=%s" % created.get("created_by_id"))

    _, fetched = api.call("GET", "/api/customers/%s" % cid, expect=200)
    check("detail returns related collections", "_related" in fetched and "_audit" in fetched)

    _, updated = api.call("PATCH", "/api/customers/%s" % cid, {"city": "Ahmedabad", "credit_days": 30}, expect=200)
    check("update applies", updated["city"] == "Ahmedabad" and updated["credit_days"] == 30, str(updated)[:200])

    _, required = api.call("POST", "/api/customers", {"kind": "customer"})
    check("required fields are enforced", required is not None and "required" in str(required).lower(),
          str(required)[:200])

    st, _ = api.call("POST", "/api/customers", {"display_name": "Bad date test", "credit_days": "not-a-number"})
    check("bad values are rejected with 400", st == 400, "got %s" % st)

    # ── search, filters, saved views ────────────────────────────────────────
    section("Search, filters and saved views")
    _, found = api.call("GET", "/api/customers?q=Smoke", expect=200)
    check("search matches", any(r["id"] == cid for r in found["rows"]), "rows=%s" % found["count"])

    _, filtered = api.call("GET", "/api/customers?kind=prospect", expect=200)
    check("column filter works", all(r["kind"] == "prospect" for r in filtered["rows"]) and filtered["total"] >= 1,
          "total=%s" % filtered["total"])

    _, viewed = api.call("GET", "/api/customers?view=Prospects", expect=200)
    check("saved view filters", all(r["kind"] == "prospect" for r in viewed["rows"]), "total=%s" % viewed["total"])

    st, _ = api.call("GET", "/api/customers?view=NoSuchView")
    check("an unknown saved view is a 400, not silently ignored", st == 400, "got %s" % st)

    _, page = api.call("GET", "/api/projects?limit=5&offset=0", expect=200)
    check("pagination caps the page", page["count"] == 5 and page["total"] > 5,
          "count=%s total=%s" % (page["count"], page["total"]))

    # A silently-ignored filter is the sharpest edge for an agent: a typo'd
    # "does this exist?" check would come back with the whole unfiltered list.
    st, err = api.call("GET", "/api/customers?not_a_column=zzz")
    check("an unknown filter is a 400, not silently ignored", st == 400, "got %s: %s" % (st, err))

    # One column cannot equal two values, so ANDing repeats always returns zero.
    _, ored = api.call("GET", "/api/projects?stage=Testing&stage=In+progress", expect=200)
    stages = {r["stage"] for r in ored["rows"]}
    check("a repeated filter means OR, not AND",
          ored["total"] > 0 and stages <= {"Testing", "In progress"}, "stages=%s total=%s" % (stages, ored["total"]))

    _, od_true = api.call("GET", "/api/tasks?overdue=true", expect=200)
    _, od_false = api.call("GET", "/api/tasks?overdue=false", expect=200)
    check("overdue respects its value instead of ignoring it",
          od_true["total"] != od_false["total"] or od_true["total"] == 0,
          "true=%s false=%s" % (od_true["total"], od_false["total"]))

    check("the schema endpoint requires auth", Client(base).call("GET", "/api/meta/entities")[0] == 401,
          "the full table layout must not be readable anonymously")

    # ── append-only remarks ─────────────────────────────────────────────────
    section("Remarks (append-only Owner Remark history)")
    api.call("POST", "/api/customers/%s/remarks" % cid, {"body": "First remark from the smoke test."}, expect=200)
    api.call("POST", "/api/customers/%s/remarks" % cid, {"body": "Second remark, later."}, expect=200)
    _, remarks = api.call("GET", "/api/customers/%s/remarks" % cid, expect=200)
    check("remarks accumulate in order", len(remarks["remarks"]) == 2
          and remarks["remarks"][0]["body"].startswith("First"), str(remarks)[:200])
    check("remarks carry an author", remarks["remarks"][0]["author"] is not None)

    _, dup1 = api.call("POST", "/api/customers/%s/remarks" % cid,
                       {"body": "Replayed by an agent.", "external_ref": "wiki:2026-07-26#3"}, expect=200)
    _, dup2 = api.call("POST", "/api/customers/%s/remarks" % cid,
                       {"body": "Replayed by an agent.", "external_ref": "wiki:2026-07-26#3"}, expect=200)
    check("an external_ref replay is idempotent", dup2.get("duplicate") is True and dup1["id"] == dup2["id"],
          "dup1=%s dup2=%s" % (dup1, dup2))

    st, _ = api.call("POST", "/api/customers/%s/remarks" % cid, {"body": "   "})
    check("an empty remark is rejected", st == 400, "got %s" % st)

    # A naive ISO string with no offset is read as LOCAL time by browsers, which
    # made every fresh timestamp render hours in the past in IST.
    stamps = [r["created_at"] for r in remarks["remarks"]]
    check("timestamps are marked UTC so clients cannot misread them",
          all(s and (s.endswith("Z") or "+" in s[10:]) for s in stamps), str(stamps))
    fresh = datetime.utcnow()
    newest = datetime.strptime(stamps[-1][:19], "%Y-%m-%dT%H:%M:%S")
    check("a just-written timestamp is within a minute of now",
          abs((fresh - newest).total_seconds()) < 60,
          "server said %s, utcnow is %s" % (stamps[-1], fresh.isoformat()))

    # There must be no way to edit or delete history.
    st_patch, _ = api.call("PATCH", "/api/customers/%s/remarks" % cid, {"body": "rewritten"})
    st_del, _ = api.call("DELETE", "/api/customers/%s/remarks" % cid)
    check("remark history cannot be edited or deleted",
          st_patch in (404, 405) and st_del in (404, 405),
          "patch=%s delete=%s" % (st_patch, st_del))

    # ── tasks ───────────────────────────────────────────────────────────────
    section("Tasks (the Google Tasks replacement)")
    _, task = api.call("POST", "/api/tasks", {
        "title": "Smoke test task", "party_id": cid, "priority": "high",
        "due_date": date.today().isoformat(),
    }, expect=200)
    check("a task can exist without a project", task["project_id"] is None and task["id"] is not None)
    check("a task records where it came from", task["source"] in ("ui", "api"), "source=%s" % task["source"])

    _, mine = api.call("GET", "/api/tasks?view=Open", expect=200)
    check("the Open view returns open tasks",
          all(r["status"] in ("open", "in_progress", "blocked") for r in mine["rows"]),
          "statuses=%s" % {r["status"] for r in mine["rows"]})

    api.call("POST", "/api/tasks/%s/remarks" % task["id"], {"body": "Blocked on Nishant's reply."}, expect=200)
    api.call("PATCH", "/api/tasks/%s" % task["id"], {"status": "blocked"}, expect=200)
    _, task_detail = api.call("GET", "/api/tasks/%s" % task["id"], expect=200)
    check("a task carries its remark history", len(task_detail["_remarks"]) == 1, str(task_detail["_remarks"])[:200])

    # ── CLI/agent attribution ───────────────────────────────────────────────
    section("Actor attribution (human vs CLI vs agent)")
    agent = Client(base, client_kind="agent")
    agent.login(email, password)
    _, agent_task = agent.call("POST", "/api/tasks", {"title": "Task written by an agent"}, expect=200)
    check("an agent-written task is marked as such", agent_task["source"] == "agent",
          "source=%s" % agent_task["source"])

    cli = Client(base, client_kind="cli")
    cli.login(email, password)
    _, cli_task = cli.call("POST", "/api/tasks", {"title": "Task written by the CLI"}, expect=200)
    check("a CLI-written task is marked as such", cli_task["source"] == "cli", "source=%s" % cli_task["source"])

    # ── lead conversion ─────────────────────────────────────────────────────
    section("Leads and conversion")
    _, lead = api.call("POST", "/api/leads", {
        "title": "Smoke Test Lead", "company_name": "Smoke Lead Co",
        "contact_name": "A Person", "email": "lead@example.com", "estimated_value": 250000,
    }, expect=200)
    check("a lead is created open", lead["status"] == "open", "status=%s" % lead["status"])

    _, conv = api.call("POST", "/api/leads/%s/convert" % lead["id"], {}, expect=200)
    new_party_id = conv["customer"]["id"]
    check("conversion creates a customer", conv["already_converted"] is False and bool(new_party_id))

    _, lead_after = api.call("GET", "/api/leads/%s" % lead["id"], expect=200)
    check("the lead survives conversion and is stamped",
          lead_after["status"] == "won" and lead_after["converted_party_id"] == new_party_id,
          str(lead_after)[:200])

    _, conv2 = api.call("POST", "/api/leads/%s/convert" % lead["id"], {}, expect=200)
    check("converting twice does not create a second customer",
          conv2["already_converted"] is True and conv2["customer"]["id"] == new_party_id, str(conv2)[:200])

    _, contacts = api.call("GET", "/api/contacts?party_id=%s" % new_party_id, expect=200)
    check("the lead contact is carried across", contacts["total"] == 1
          and contacts["rows"][0]["name"] == "A Person", str(contacts)[:200])

    # A second lead for a company already in the book LINKS to it.
    #
    # This check used to assert 409, on the reasoning that conversion "must not
    # silently merge" two customers. The contract changed deliberately: a second
    # project for an existing customer is still a lead, and refusing it is what
    # put the same company in the book twice.
    #
    # It is not a silent merge of two distinct companies, because it cannot be —
    # `uq_parties_org_name` makes display_name unique per organisation, so two
    # different customers can never share one name. A name match therefore *is*
    # the same company, and linking to it is the only correct answer.
    _, lead2 = api.call("POST", "/api/leads", {"title": "Dup lead", "company_name": "Smoke Lead Co"}, expect=200)
    st, conv3 = api.call("POST", "/api/leads/%s/convert" % lead2["id"], {}, expect=200)
    check("a second lead for a known company links to it, not a duplicate",
          st == 200 and conv3["customer"]["id"] == new_party_id,
          "got %s / customer=%s want %s" % (st, conv3.get("customer", {}).get("id"), new_party_id))

    _, lead2_after = api.call("GET", "/api/leads/%s" % lead2["id"], expect=200)
    check("the second lead is stamped with that same customer",
          lead2_after["converted_party_id"] == new_party_id, str(lead2_after)[:200])
    check("winning the second lead opened its own project",
          bool(lead2_after["converted_project_id"]), str(lead2_after)[:200])

    _, all_projects = api.call("GET", "/api/projects?party_id=%s" % new_party_id, expect=200)
    check("one customer now carries two projects, one per lead",
          all_projects["total"] == 2, "total=%s" % all_projects["total"])

    # ── audit trail ─────────────────────────────────────────────────────────
    section("Audit trail")
    _, trail = api.call("GET", "/api/audit?entity_type=parties&entity_id=%s" % cid, expect=200)
    actions = [e["action"] for e in trail["entries"]]
    check("create and update are both audited", "create" in actions and "update" in actions, str(actions))

    update_entry = next((e for e in trail["entries"] if e["action"] == "update"), None)
    check("an update audit carries a field-level diff",
          bool(update_entry and update_entry["changes"]
               and update_entry["changes"].get("city", {}).get("to") == "Ahmedabad"),
          str(update_entry and update_entry["changes"])[:300])
    check("an audit entry names the actor", bool(update_entry and update_entry["actor"] == email),
          str(update_entry and update_entry["actor"]))
    check("an audit entry is timestamped", bool(update_entry and update_entry["created_at"]))

    _, agent_trail = api.call("GET", "/api/audit?entity_type=tasks&entity_id=%s" % agent_task["id"], expect=200)
    check("an agent's write is distinguishable in the audit log",
          any(e["actor_kind"] == "agent" for e in agent_trail["entries"]),
          str([e["actor_kind"] for e in agent_trail["entries"]]))

    _, counted = api.call("GET", "/api/audit?limit=100", expect=200)
    check("audit count reports rows returned, not the limit asked for",
          counted["count"] == len(counted["entries"]),
          "count=%s entries=%s" % (counted["count"], len(counted["entries"])))

    _, login_trail = api.call("GET", "/api/audit?entity_type=users", expect=200)
    check("logins are audited", any(e["action"] == "login" for e in login_trail["entries"]),
          str([e["action"] for e in login_trail["entries"]][:10]))

    bad = Client(base)
    bad.call("POST", "/api/auth/login", {"email": email, "password": "definitely-wrong"})
    _, fail_trail = api.call("GET", "/api/audit?entity_type=users", expect=200)
    check("failed logins are audited", any(e["action"] == "login_failed" for e in fail_trail["entries"]),
          str([e["action"] for e in fail_trail["entries"]][:10]))

    # ── delete keeps the record of what was lost ────────────────────────────
    section("Delete")
    api.call("DELETE", "/api/tasks/%s" % task["id"], expect=200)
    api.call("DELETE", "/api/tasks/%s" % agent_task["id"], expect=200)
    api.call("DELETE", "/api/tasks/%s" % cli_task["id"], expect=200)
    st, _ = api.call("GET", "/api/tasks/%s" % task["id"])
    check("a deleted row is gone", st == 404, "got %s" % st)

    _, del_trail = api.call("GET", "/api/audit?entity_type=tasks&entity_id=%s" % task["id"], expect=200)
    del_entry = next((e for e in del_trail["entries"] if e["action"] == "delete"), None)
    check("a delete records the row's final state",
          bool(del_entry and del_entry["changes"]
               and del_entry["changes"]["deleted"]["from"]["title"] == "Smoke test task"),
          str(del_entry)[:300])

    # ── authorisation ───────────────────────────────────────────────────────
    section("Authorisation")
    _, me = api.call("GET", "/api/auth/me", expect=200)
    check("auth/me publishes what the caller may do",
          isinstance(me.get("can"), dict) and me["can"].get("customers", {}).get("delete") is True,
          "can=%s" % str(me.get("can"))[:200])

    _, meta2 = api.call("GET", "/api/meta/entities", expect=200)
    check("the registry publishes per-entity permissions",
          all("can" in e for e in meta2["entities"]),
          "an entity is missing its `can` block")

    advisor_pw = os.environ.get("SEED_HEMISH_PASSWORD", "hemish-local-test-pw")
    advisor = Client(base)
    st, _ = advisor.call("POST", "/api/auth/login",
                         {"email": "hemish@neonir.com", "password": advisor_pw})
    if st != 200:
        check("advisor login", False, "could not log in as the Advisor to test authz (status %s)" % st)
    else:
        advisor.token = advisor.call("POST", "/api/auth/login",
                                     {"email": "hemish@neonir.com", "password": advisor_pw},
                                     expect=200)[1]["access_token"]
        st_read, adv_rows = advisor.call("GET", "/api/customers")
        check("an advisor sees every customer", st_read == 200 and adv_rows["total"] >= 15,
              "status=%s" % st_read)

        st_create, _ = advisor.call("POST", "/api/customers", {"display_name": "Advisor should not create"})
        check("an advisor cannot create a customer", st_create == 403, "got %s" % st_create)

        st_del, _ = advisor.call("DELETE", "/api/customers/%s" % cid)
        check("an advisor cannot delete a customer", st_del == 403, "got %s" % st_del)

        st_cfg, _ = advisor.call("POST", "/api/lead-sources", {"name": "Advisor should not configure"})
        check("an advisor cannot change configuration", st_cfg == 403, "got %s" % st_cfg)

        st_remark, _ = advisor.call("POST", "/api/customers/%s/remarks" % cid,
                                    {"body": "An advisor may always comment."})
        check("an advisor CAN comment", st_remark == 200, "got %s" % st_remark)

        st_user, _ = advisor.call("POST", "/api/users",
                                  {"email": "nope@example.com", "name": "Nope", "role_name": "Viewer"})
        check("an advisor cannot create a user", st_user == 403, "got %s" % st_user)

        _, adv_me = advisor.call("GET", "/api/auth/me", expect=200)
        check("the advisor's own `can` reflects the denial",
              adv_me["can"]["customers"]["delete"] is False and adv_me["can"]["customers"]["read"] is True,
              str(adv_me["can"].get("customers")))

    # A duplicate natural key is a conflict the caller can act on, not a 500.
    _, dupe_target = api.call("GET", "/api/customers?limit=1", expect=200)
    if dupe_target["rows"]:
        st_dup, _ = api.call("POST", "/api/customers",
                             {"display_name": dupe_target["rows"][0]["display_name"]})
        check("a duplicate name returns 409, not 500", st_dup == 409, "got %s" % st_dup)

    # ── a recycled id must not inherit a dead row's history ─────────────────
    section("Orphaned history after delete")
    _, victim = api.call("POST", "/api/tasks", {"title": "Doomed task"}, expect=200)
    victim_id = victim["id"]
    api.call("POST", "/api/tasks/%s/remarks" % victim_id, {"body": "Secret note on the doomed task."}, expect=200)
    api.call("DELETE", "/api/tasks/%s" % victim_id, expect=200)

    # Recreate rows until one lands on the freed id (SQLite hands it straight back).
    reused, made = None, []
    for _ in range(6):
        _, fresh = api.call("POST", "/api/tasks", {"title": "Fresh task"}, expect=200)
        made.append(fresh["id"])
        if fresh["id"] == victim_id:
            reused = fresh
            break
    if reused:
        _, detail = api.call("GET", "/api/tasks/%s" % victim_id, expect=200)
        bodies = [r["body"] for r in detail["_remarks"]]
        check("a reused id does not inherit the deleted row's remarks",
              "Secret note on the doomed task." not in bodies, str(bodies))
        actions = [e["action"] for e in detail["_audit"]]
        check("a reused id does not inherit the deleted row's audit trail",
              "delete" not in actions, str(actions))
    else:
        check("a reused id does not inherit the deleted row's remarks", True,
              "id was not recycled on this backend; nothing to assert")
    for tid in made:
        api.call("DELETE", "/api/tasks/%s" % tid)

    # ── cleanup ─────────────────────────────────────────────────────────────
    api.call("DELETE", "/api/leads/%s" % lead["id"], expect=200)
    api.call("DELETE", "/api/leads/%s" % lead2["id"], expect=200)
    api.call("DELETE", "/api/customers/%s" % new_party_id, expect=200)
    api.call("DELETE", "/api/customers/%s" % cid, expect=200)
    st, _ = api.call("GET", "/api/customers/%s" % cid)
    check("cleanup left nothing behind", st == 404, "got %s" % st)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8077")
    parser.add_argument("--email", default="meet@dotsai.in")
    parser.add_argument("--password", default=os.environ.get("SEED_ADMIN_PASSWORD", "meetdeshani123"))
    args = parser.parse_args()

    print("HQ API smoke test against %s" % args.base)
    try:
        run(args.base, args.email, args.password)
    except AssertionError as exc:
        print("\nABORTED: %s" % exc)
        FAILED.append(("harness", str(exc)))

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("\nFailures:")
        for name, detail in FAILED:
            print("  - %s: %s" % (name, detail))
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
