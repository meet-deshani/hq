#!/usr/bin/env python3
"""End-to-end API contract test for the HQ CRM surface.

Exercises the real HTTP surface of a running server — not the ORM — because the
contract that matters is the one an agent, the CLI and the browser all call.

    python3 tests/api_smoke.py [--base http://127.0.0.1:8077] [--email ...] [--password ...]

Exits non-zero on the first failure with the offending response body.
"""

import argparse
import json
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

    # ── discovery ───────────────────────────────────────────────────────────
    section("Discovery")
    _, meta = api.call("GET", "/api/meta/entities", expect=200)
    entities = {e["key"]: e for e in meta["entities"]}
    check("meta lists entities", meta["count"] == len(entities) and meta["count"] > 10,
          "count=%s" % meta.get("count"))
    check("every entity declares columns and fields",
          all(e.get("columns") and e.get("fields") for e in meta["entities"]
              if e["key"] not in ("work-stream-members",)),
          "an entity is missing columns/fields")
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

    # ── CRUD round trip ─────────────────────────────────────────────────────
    section("CRUD round trip")
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

    # A conversion that would collide with an existing customer must not
    # silently merge into it.
    _, lead2 = api.call("POST", "/api/leads", {"title": "Dup lead", "company_name": "Smoke Lead Co"}, expect=200)
    st, _ = api.call("POST", "/api/leads/%s/convert" % lead2["id"], {})
    check("a colliding conversion is refused with 409", st == 409, "got %s" % st)

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
    parser.add_argument("--password", default="meetdeshani123")
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
