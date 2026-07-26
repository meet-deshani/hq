# API

The REST surface of the HQ CRM layer. Every entity in `backend/registry.py` gets
the same routes; there is no per-entity API to learn.

Base URL is `https://hq.dotsai.in` in production and `http://127.0.0.1:8077` on a
local dev server. Every example below was run against a seeded local dev server;
row ids and totals are that database's, not yours.

The executable version of this contract is `tests/api_smoke.py`. If this document
and that file disagree, the file is right.

## Authentication

`POST /api/auth/login` with an email and password. It returns a JWT **and** sets
an httpOnly `access_token` cookie, so the same login works for a script and for
the browser SPA.

```bash
curl -s -X POST http://127.0.0.1:8077/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"meet@dotsai.in","password":"meetdeshani123"}'
```

```json
{"access_token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...","token_type":"bearer"}
```

Send it back either way — `backend/auth.py` checks the header first, then the
cookie:

```bash
# header (scripts, CLI, agents)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8077/api/auth/me

# cookie (browser; value is stored as "Bearer <jwt>")
curl -s -b cookies.txt http://127.0.0.1:8077/api/auth/me
```

Both return the signed-in user:

```json
{
  "email": "meet@dotsai.in",
  "name": "Meet Deshani",
  "status": "Active",
  "organisation_id": 1,
  "id": 1,
  "role_id": 1,
  "role": {"name": "Admin", "description": "Administrator with full permissions across all workspaces", "organisation_id": 1},
  "created_at": "2026-07-26T04:32:08.653382"
}
```

Tokens last a week (`ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7`), deliberately,
so a CLI session does not need re-authenticating mid-task. `POST /api/auth/logout`
clears the cookie; it does not revoke the JWT — there is no token blacklist.

Missing or invalid credentials:

```
{"detail":"Could not validate credentials"}   # HTTP 401
```

Logins and failed logins are both audited (`entity_type=users`, actions `login`
and `login_failed`).

## Start here: `GET /api/meta/entities`

This publishes the registry. It is the only thing an agent should hardcode —
every path, column, field, filter and action below is derived from it, so a new
entity appears here the moment it is added, and a client that reads it never
needs updating.

```bash
curl -s http://127.0.0.1:8077/api/meta/entities
```

It answers `200` **without a token** — discovery is public, the data behind it is
not.

Trimmed to one entity (`leads`):

```json
{
  "count": 17,
  "refs": {"users": {"path": "/api/users", "title_field": "name"}},
  "entities": [
    {
      "key": "leads",
      "entity_type": "leads",
      "label": "Lead",
      "plural": "Leads",
      "workspace": "CRM",
      "module": "Leads",
      "icon": "trend",
      "accent": "#FFCDB2",
      "order_by": "-created_at",
      "search": ["title", "company_name", "contact_name", "email", "phone"],
      "title_field": "title",
      "columns": [
        {"k": "title", "label": "Lead", "type": "text", "width": "2.2fr", "primary": true},
        {"k": "stage_id", "label": "Stage", "type": "ref", "ref": "pipeline-stages", "width": "1.2fr"},
        {"k": "estimated_value", "label": "One-time", "type": "money", "width": "1.1fr", "align": "right"}
      ],
      "fields": [
        {"k": "title", "label": "Lead title", "type": "text", "required": true, "group": "Lead"},
        {"k": "status", "label": "Status", "type": "select", "options": ["open", "won", "lost"],
         "default": "open", "group": "Outcome", "readonly_hint": "Use Convert to mark a lead won."}
      ],
      "key_facts": ["stage_id", "owner_id", "estimated_value", "monthly_value", "expected_close_date", "source_id"],
      "relations": [{"key": "tasks", "label": "Tasks", "entity": "tasks", "fk": "lead_id"}],
      "saved_views": [
        {"name": "Open", "filters": {"status": "open"}},
        {"name": "All", "filters": {}},
        {"name": "Won", "filters": {"status": "won"}},
        {"name": "Lost", "filters": {"status": "lost"}}
      ],
      "scope": {},
      "actions": [
        {"key": "convert", "label": "Convert to customer", "method": "POST",
         "path": "/api/leads/{id}/convert",
         "description": "Creates a parties row from the lead, stamps converted_party_id, marks the lead won. The lead is kept — the funnel history is the point."}
      ],
      "path": "/api/leads"
    }
  ]
}
```

The 17 keys and their paths, as returned today:

```
customers /api/customers        contacts /api/contacts        party-groups /api/party-groups
leads /api/leads                lead-sources /api/lead-sources pipelines /api/pipelines
pipeline-stages /api/pipeline-stages                          lost-reasons /api/lost-reasons
services /api/services          catalog-products /api/catalog-products
item-categories /api/item-categories
projects /api/projects          milestones /api/milestones     project-members /api/project-members
tasks /api/tasks                work-streams /api/work-streams work-stream-members /api/work-stream-members
```

Note `catalog-products`, not `products`: `/api/products` is the platform's own
product-config route, and `check_route_collisions()` in `backend/crud.py` refuses
to boot if a registry key would shadow a hand-written one.

`GET /api/meta/entities/{key}` returns a single entry in the same shape.

## Generic routes

Seven routes per entity, generated in `backend/crud.py`. `{key}` is any registry
key.

| Method | Path | Does |
|---|---|---|
| GET | `/api/{key}` | List — search, filter, saved view, order, paginate |
| POST | `/api/{key}` | Create |
| GET | `/api/{key}/{id}` | Detail, plus related lists, remarks and recent audit |
| PATCH | `/api/{key}/{id}` | Partial update |
| DELETE | `/api/{key}/{id}` | Delete |
| GET | `/api/{key}/{id}/remarks` | Append-only remark history |
| POST | `/api/{key}/{id}/remarks` | Append a remark |

### List

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8077/api/customers?q=Pioneer&limit=1'
```

```json
{
  "entity": "customers",
  "total": 1,
  "count": 1,
  "offset": 0,
  "rows": [
    {
      "id": 2,
      "organisation_id": 1,
      "kind": "customer",
      "display_name": "Pioneer Engineering",
      "legal_name": null,
      "initials": "PE",
      "party_group_id": 1,
      "owner_id": 1,
      "gstin": null,
      "gst_treatment": "regular",
      "pan": null,
      "phone": null,
      "email": null,
      "website": null,
      "billing_address": null,
      "city": null,
      "state_code": null,
      "pincode": null,
      "credit_limit": null,
      "credit_days": null,
      "industry": "Water Treatment",
      "summary": null,
      "notes": null,
      "status": "Active",
      "custom_fields": {},
      "created_at": "2026-07-26T04:40:21.022352",
      "updated_at": "2026-07-26T04:40:21.022352",
      "created_by_id": 1,
      "updated_by_id": 1,
      "_label": "Pioneer Engineering",
      "_entity": "customers",
      "_refs": {"owner_id": "Meet Deshani", "party_group_id": "Water Treatment"}
    }
  ]
}
```

`total` is the row count before pagination; `count` is the rows in this page.

Every row carries three synthetic keys:

* `_label` — the row's `title_field` value, for display without knowing the schema.
* `_entity` — the registry key it came from.
* `_refs` — every `ref` column resolved to a human label, batched one query per
  referenced entity rather than one per row. Use this instead of chasing foreign
  keys yourself.

A saved view, by name:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8077/api/projects?view=Ongoing&limit=1'
```

```json
{
  "entity": "projects",
  "total": 14,
  "count": 1,
  "offset": 0,
  "rows": [
    {
      "id": 15,
      "doc_no": "HQ-P03",
      "name": "Parag Kaka — SupportDesk",
      "stage": "Testing",
      "status": "active",
      "next_action": "NK to test",
      "next_action_date": "2026-07-27",
      "_label": "Parag Kaka — SupportDesk",
      "_entity": "projects",
      "_refs": {"party_id": "Parag Kaka", "item_id": "SupportDesk",
                "manager_id": "Meet Deshani", "next_action_owner_id": "Meet Deshani"}
    }
  ]
}
```

(Row abbreviated — the real response carries every column.)

### Detail

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8077/api/projects/10
```

Returns every column plus three extras:

```json
{
  "id": 10,
  "doc_no": "HQ-P08",
  "name": "Om Enterprises — AquaServe",
  "party_id": 12,
  "stage": "Onboarding Completed",
  "next_action": "MD to assist till full adoption",
  "next_action_date": "2026-08-08",
  "_label": "Om Enterprises — AquaServe",
  "_entity": "projects",
  "_refs": {"party_id": "Om Enterprises", "item_id": "AquaServe",
            "manager_id": "Meet Deshani", "next_action_owner_id": "Meet Deshani"},
  "_related": {
    "milestones": {"label": "Milestones", "entity": "milestones", "rows": []},
    "tasks": {"label": "Tasks", "entity": "tasks", "rows": []},
    "members": {"label": "Team", "entity": "project-members", "rows": []}
  },
  "_remarks": [],
  "_audit": []
}
```

* `_related` — one entry per `relations` declaration in the registry, capped at
  100 child rows each, children serialised the same way (with their own `_refs`).
  Relations declared with `"via"` (a join table, e.g. contacts → tasks via
  `task_participants`) are **skipped** here; they are not resolved by this route.
* `_remarks` — the full append-only history, oldest first.
* `_audit` — the 25 most recent audit entries for this row, newest first.

A customer detail shows the same shape with real children:

```json
"_related": {
  "contacts":     {"label": "Contacts",     "entity": "contacts",     "rows": []},
  "projects":     {"label": "Projects",     "entity": "projects",     "rows": []},
  "tasks":        {"label": "Tasks",        "entity": "tasks",
                   "rows": [{"id": 2, "title": "Send the AquaServe proposal", "status": "open"}]},
  "work_streams": {"label": "Work streams", "entity": "work-streams", "rows": []}
}
```

### Create

Only keys listed in the entity's `fields` **and** backed by a real column are
written; everything else in the body is ignored, not rejected.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"display_name":"Docs Example Ltd","kind":"prospect","city":"Vadodara","credit_days":15}' \
  http://127.0.0.1:8077/api/customers
```

```json
{
  "id": 16,
  "organisation_id": 1,
  "kind": "prospect",
  "display_name": "Docs Example Ltd",
  "gst_treatment": "regular",
  "city": "Vadodara",
  "credit_days": 15,
  "status": "Active",
  "custom_fields": {},
  "created_at": "2026-07-26T04:37:37.950072",
  "updated_at": "2026-07-26T04:37:37.950072",
  "created_by_id": 1,
  "updated_by_id": 1,
  "_label": "Docs Example Ltd",
  "_entity": "customers",
  "_refs": {}
}
```

(Null columns elided.) The server fills in, without being asked:
`organisation_id` from the caller, `created_by_id`/`updated_by_id` from the
caller, registry `default` values for any field you omitted, `source` from the
`X-HQ-Client` header on tables that have a `source` column, and — on a scoped
entity — the scope discriminator.

Scope cannot be overridden from the body. Creating a Product while passing
`item_type: "service"`:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Docs scope probe","item_type":"service"}' \
  http://127.0.0.1:8077/api/catalog-products
```

```json
{"id": 9, "name": "Docs scope probe", "item_type": "goods", "is_active": true,
 "currency": "INR", "_entity": "catalog-products"}
```

and that row is invisible through the other scope:

```
GET /api/services/9  ->  404  {"detail":"Service 9 not found"}
```

### Update

```bash
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"city":"Ahmedabad","credit_days":30}' \
  http://127.0.0.1:8077/api/customers/16
```

```json
{"id": 16, "display_name": "Docs Example Ltd", "city": "Ahmedabad", "credit_days": 30,
 "updated_by_id": 1, "_label": "Docs Example Ltd", "_entity": "customers", "_refs": {}}
```

Scope columns are not writable on update either. An audit entry is written only
if something actually changed.

### Delete

```bash
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8077/api/catalog-products/9
```

```json
{"detail": "Product deleted", "id": 9}
```

Hard delete — there is no soft-delete flag and no undo. The row's **final state**
is preserved in the audit entry (`changes.deleted.from`), which is the only
record of what was lost.

Caveat, and it is a real one: remarks, activities and attachments are attached
polymorphically by `entity_type` + `entity_id`, with no foreign key and no
cascade. Deleting a record leaves its remarks behind. On Postgres the id is never
reissued so they are merely orphaned; on the SQLite dev database ids **are**
reused, and the orphans then show up as the history of whatever record next takes
that id.

## Query parameters

Five parameters control the request; everything else is treated as a column
filter.

| Param | Default | Does |
|---|---|---|
| `q` | — | Case-insensitive `LIKE` across the entity's `search` columns, OR-ed |
| `view` | — | Apply a named saved view's filters. Unknown name → `400` |
| `order` | entity's `order_by` | Column name; prefix `-` for descending |
| `limit` | 200 | 1–1000. Outside that → `422` |
| `offset` | 0 | ≥ 0 |

`expand` is accepted and ignored — it is reserved in `_CONTROL_PARAMS` but
nothing implements it.

### Column filters

Any other query parameter is matched against a column of the same name:

```bash
curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8077/api/customers?industry=Water%20Treatment'
# -> total 9

curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8077/api/tasks?external_ref=gtasks:AbC123'
# -> total 1, rows[0].external_ref == "gtasks:AbC123"
```

Three gotchas, all verified:

* **A parameter that is not a column is silently ignored.**
  `?not_a_column=zzz` returns the unfiltered list (`total 15`), not a `400`.
  Typo a filter name and you get too many rows, with no warning.
* **Repeating a parameter ANDs, it does not OR.**
  `?stage=Testing&stage=In+progress` applies both equality filters in turn and
  returns `total 0`. List-valued (`IN`) filters only work from a saved view's
  JSON, e.g. the tasks `Open` view's `{"status": ["open","in_progress","blocked"]}`.
* **Values are coerced to the column type.** A bad value is a `400`, not a
  silent zero.

### Special filter values

| Value | Applies to | Means |
|---|---|---|
| `me` | any column | `column == current_user.id` |
| `today` | any column | `column == today` (server date) |
| `null` / `none` / empty | any column | `column IS NULL` |
| `overdue` (as the **name**) | entities with `due_date` | `due_date < today` AND, if the table has `status`, `status NOT IN ('done','cancelled')` |

```bash
# tasks owned by whoever is holding this token
curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8077/api/tasks?owner_id=me'
# -> total 3

# same thing via the saved view
curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8077/api/tasks?view=Mine'
# -> total 3

# due today (server date; nothing was due on 2026-07-26)
curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8077/api/tasks?due_date=today'
# -> total 0

# overdue is a filter NAME, not a value
curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8077/api/tasks?overdue=true'
# -> total 1: {"id":3,"title":"Chase the Pioneer invoice","due_date":"2026-07-20","status":"open"}

# tasks with no project — most of them
curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8077/api/tasks?project_id=null'
```

`overdue` ignores whatever value you pass it; `?overdue=false` filters exactly
the same as `?overdue=true`. Omit the parameter to not filter.

### Ordering and pagination

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8077/api/projects?limit=3&offset=3&order=name'
```

```json
{"entity":"projects","total":15,"count":3,"offset":3,
 "rows":["FeedAqua — Website","Michael Bhai — AquaServe","Micro Chem — AquaServe"]}
```

(`rows` shown as names only.) An unknown `order` column is ignored and the
entity's default ordering applies.

## Remarks

The append-only Owner Remark history on any record. Available on every entity.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"body":"Intro call done. They want AquaServe."}' \
  http://127.0.0.1:8077/api/customers/16/remarks
```

```json
{
  "id": 6,
  "body": "Intro call done. They want AquaServe.",
  "kind": "remark",
  "source": "ui",
  "author": "Meet Deshani",
  "author_id": 1,
  "created_at": "2026-07-26T04:37:50.451993",
  "duplicate": false
}
```

`kind` is one of `remark`, `note`, `reply`, `correction`; anything else is a
`400`. An empty or whitespace-only `body` is a `400`.

Reading them back (a separate capture, after the dev database was re-seeded —
different remarks, same shape):

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8077/api/customers/16/remarks
```

```json
{
  "entity": "customers",
  "id": 16,
  "remarks": [
    {"id": 1, "body": "First remark from the smoke test.", "kind": "remark", "source": "ui",
     "author_id": 1, "author": "Meet Deshani", "created_at": "2026-07-26T04:40:22.356318", "external_ref": null},
    {"id": 2, "body": "Second remark, later.", "kind": "remark", "source": "ui",
     "author_id": 1, "author": "Meet Deshani", "created_at": "2026-07-26T04:40:22.360843", "external_ref": null},
    {"id": 3, "body": "Replayed by an agent.", "kind": "remark", "source": "ui",
     "author_id": 1, "author": "Meet Deshani", "created_at": "2026-07-26T04:40:22.365629",
     "external_ref": "wiki:2026-07-26#3"}
  ]
}
```

Oldest first, always.

### Append-only, enforced

There is no edit and no delete. A correction is a new remark with
`"kind": "correction"`, so the trail of what was believed when stays readable.

```
PATCH  /api/customers/16/remarks  ->  405  {"detail":"Method Not Allowed"}
DELETE /api/customers/16/remarks  ->  405  {"detail":"Method Not Allowed"}
```

### `external_ref` — the idempotency key

Pass `external_ref` when the remark comes from somewhere else (a wiki row, a
Google Tasks id, a message id). The same `external_ref` on the same record is a
no-op, not a duplicate:

```bash
# first call
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'X-HQ-Client: agent' \
  -d '{"body":"Closed in Google Tasks on 2026-07-26.","kind":"note","external_ref":"gtasks:TASK-77#closed"}' \
  http://127.0.0.1:8077/api/tasks/1/remarks
```

```json
{"id": 5, "body": "Closed in Google Tasks on 2026-07-26.", "kind": "note", "source": "agent",
 "author": "Meet Deshani", "author_id": 1, "created_at": "2026-07-26T04:40:29.456687", "duplicate": false}
```

```bash
# byte-identical replay
```

```json
{"detail": "Remark already recorded", "id": 5, "duplicate": true}
```

Both return `200`. Branch on `duplicate`, not on the status code. Uniqueness is
scoped to `(entity_type, entity_id, external_ref)` — the same ref on a different
record is a different remark. This is enforced by a lookup in application code,
not a database constraint, so two simultaneous replays can still race.

## Lead conversion

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{}' http://127.0.0.1:8077/api/leads/2/convert
```

```json
{
  "detail": "Lead converted",
  "already_converted": false,
  "lead_id": 2,
  "customer": {
    "id": 18,
    "display_name": "Docs Lead Co",
    "kind": "customer",
    "email": "r@example.com",
    "phone": "+91 90000 00000",
    "owner_id": 1,
    "status": "Active",
    "_label": "Docs Lead Co",
    "_entity": "customers"
  }
}
```

Optional body keys: `display_name` (overrides the derived name) and `kind`
(defaults to `customer`).

The lead survives, stamped:

```json
{"id": 2, "title": "Docs Example — AquaServe", "status": "won",
 "converted_party_id": 18, "converted_at": "2026-07-26T04:39:07.530096"}
```

A `contact_name` on the lead becomes a primary contact on the new customer:

```
GET /api/contacts?party_id=18  ->  total 1, [("R Patel", is_primary=true, "r@example.com", "+91 90000 00000")]
```

**Retrying is safe.** A second convert returns the same customer:

```json
{"detail": "Lead already converted", "already_converted": true, "customer_id": 18}
```

**A colliding name is refused, not merged.** If a customer with that
`display_name` already exists in the organisation:

```
POST /api/leads/3/convert  ->  409
{"detail":"A customer named 'Docs Lead Co' already exists (id 18). Link it manually or rename."}
```

Resolve it by passing a different `display_name`, or by linking the lead to the
existing customer by hand. The API will not guess.

## Audit trail

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8077/api/audit?entity_type=tasks&entity_id=3'
```

```json
{
  "count": 100,
  "offset": 0,
  "entries": [
    {"id": 42, "action": "create", "entity_type": "tasks", "entity_id": 3,
     "entity_label": "Chase the Pioneer invoice", "actor": "meet@dotsai.in",
     "actor_kind": "agent", "actor_id": 1, "changes": null,
     "created_at": "2026-07-26T04:38:35.799421"},
    {"id": 23, "action": "delete", "entity_type": "tasks", "entity_id": 3,
     "entity_label": "Task written by the CLI", "actor": "meet@dotsai.in",
     "actor_kind": "user", "actor_id": 1,
     "changes": {"deleted": {"from": {"id": 3, "title": "Task written by the CLI",
                                      "status": "open", "priority": "medium", "source": "cli"},
                             "to": null}},
     "created_at": "2026-07-26T04:32:11.784803"}
  ]
}
```

(The `deleted.from` snapshot is abbreviated; the real one carries every column.)

Parameters: `entity_type` (the **table** name, e.g. `parties`, not the registry
key `customers`), `entity_id`, `limit` (1–500, default 100), `offset`. Newest
first.

`count` is the requested `limit`, not the number of entries returned. Use
`len(entries)`.

Actions recorded: `create`, `update`, `delete`, `remark`, `convert`, `login`,
`login_failed`. An `update` carries a field-level diff:

```json
"changes": {"credit_days": {"from": 15, "to": 30}, "city": {"from": "Vadodara", "to": "Ahmedabad"}}
```

A `convert` carries both sides of the transition:

```json
"changes": {"converted_party_id": {"from": null, "to": 18}, "status": {"from": "open", "to": "won"}}
```

`created_at`, `updated_at`, `created_by_id` and `updated_by_id` are excluded from
diffs, or every update would be noise.

The actor's email is denormalised onto the row so history survives the user being
deleted. An audit write that fails is logged and swallowed — it never rolls back
or 500s the business write that succeeded.

## `X-HQ-Client`

Send `X-HQ-Client: cli`, `agent` or `system` on every request. Anything else, or
nothing, is treated as a human (`user`).

It drives two things:

1. **`actor_kind` on every audit entry** — how you tell an agent's write from a
   person's after the fact.
2. **The `source` column** on tables that have one (`tasks`, `comments`), via
   this map in `backend/crud.py`:

   | `X-HQ-Client` | `actor_kind` | `source` |
   |---|---|---|
   | *(absent)* | `user` | `ui` |
   | `cli` | `cli` | `cli` |
   | `agent` | `agent` | `agent` |
   | `system` | `system` | `api` |

Verified end to end:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'X-HQ-Client: agent' \
  -d '{"title":"Chase the Pioneer invoice","owner_id":1,"external_ref":"gtasks:AbC123","due_date":"2026-07-20"}' \
  http://127.0.0.1:8077/api/tasks
```

```json
{"id": 3, "title": "Chase the Pioneer invoice", "status": "open", "priority": "medium",
 "project_id": null, "source": "agent", "external_ref": "gtasks:AbC123",
 "due_date": "2026-07-20", "owner_id": 1, "created_by_id": 1,
 "_label": "Chase the Pioneer invoice", "_entity": "tasks",
 "_refs": {"owner_id": "Meet Deshani"}}
```

The same body with `X-HQ-Client: cli` yields `"source": "cli"`; with no header,
`"source": "ui"`.

It is a claim, not an authentication factor — the JWT still identifies the human
whose credentials the client is using. `actor` stays `meet@dotsai.in` while
`actor_kind` becomes `agent`.

The header is the **only** way to set `source`. `backend/crud.py` will honour an
explicit `source` in the create body, but only for an entity that declares
`source` as a writable field, and none currently do — so passing
`{"source":"import"}` to `POST /api/tasks` is silently dropped and the row still
comes back `"source": "ui"`. Verified.

## Errors

| Status | When | Body |
|---|---|---|
| 400 | Missing required field | `{"detail":"'Display name' is required"}` |
| 400 | Uncoercible value | `{"detail":"Invalid value for 'credit_days': 'not-a-number'"}` |
| 400 | Unknown saved view | `{"detail":"Unknown view 'NoSuchView' for customers"}` |
| 400 | Empty remark body | `{"detail":"'body' is required"}` |
| 400 | Bad remark `kind` | `{"detail":"kind must be remark, note, reply or correction"}` |
| 401 | No/invalid token | `{"detail":"Could not validate credentials"}` |
| 404 | Unknown registry key | `{"detail":"Unknown entity 'widgets'"}` |
| 404 | Row missing, or outside the entity's scope | `{"detail":"Service 9 not found"}` |
| 405 | Editing or deleting remark history | `{"detail":"Method Not Allowed"}` |
| 409 | Conversion would collide with an existing customer | `{"detail":"A customer named '…' already exists (id 18). …"}` |
| 422 | `limit`/`offset` out of range | FastAPI validation body |

## Not implemented

Be clear about the edges:

* **Tickets, Communication and Accounting** from the PRD do not exist. No
  tables, no registry entries, no routes.
* `activities`, `attachments`, `task_participants`, `task_dependencies`,
  `saved_views` and `terminology_overrides` are tables with no REST route.
  `GET /api/activities` → `404 Unknown entity 'activities'`.
* No bulk create/update/delete endpoint. Loop.
* No cursor pagination, no `ETag`, no `If-Match`, no optimistic locking. Two
  concurrent PATCHes: last write wins, and both are in the audit log.
* No rate limiting.
* No per-entity permissions. Any authenticated user can read and write every
  entity; `roles` and `permissions` exist as records but are not enforced on
  these routes.
* `organisation_id` is stamped from the caller on create but is **not** applied
  as a filter on read. Listing an entity returns rows across organisations.
* `GET /api/meta/entities` needs no token.
