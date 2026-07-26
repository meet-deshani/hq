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
  -d '{"email":"meet@dotsai.in","password":"<your-password>"}'
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

Both return the signed-in user, their role, the concrete permission codes they
hold and a per-entity `can` map:

```json
{
  "email": "meet@dotsai.in",
  "name": "Meet Deshani",
  "status": "Active",
  "organisation_id": 1,
  "id": 1,
  "role_id": 1,
  "role": {"name": "Admin", "description": "Full control, including platform configuration and deletion.", "organisation_id": 1},
  "created_at": "2026-07-26T06:11:53.639130",
  "permissions": ["audit:create", "audit:delete", "audit:read", "…"],
  "can": {"customers": {"read": true, "create": true, "update": true, "delete": true, "remark": true}, "…": {}}
}
```

`permissions` is the flat sorted list of codes; `can` is the same information
keyed for lookup, one entry per registry entity plus one per platform surface —
33 keys on this build. A client should branch on `can`, not on the role name:
role names are configuration, the map is the answer. See "Authorisation".

Tokens last a week (`ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7`), deliberately,
so a CLI session does not need re-authenticating mid-task. `POST /api/auth/logout`
clears the cookie; it does not revoke the JWT — there is no token blacklist.

Missing or invalid credentials:

```
{"detail":"Could not validate credentials"}   # HTTP 401
```

Logins and failed logins are both audited (`entity_type=users`, actions `login`
and `login_failed`).

## Authorisation

Authentication tells the server who you are. Authorisation decides what that
gets you, and it is enforced — on every generated registry route and on 25
hand-written platform routes. `backend/permissions.py` is the whole of it.

A permission is the string `<entity>:<action>`. Actions are `read`, `create`,
`update`, `delete`, `remark`. Entities are **every registry key** plus eight
platform surfaces: `users`, `roles`, `permissions`, `organisations`, `products`,
`workspaces`, `feedback`, `audit`. 33 keys × 5 actions = **165 codes**.

The codes are derived from the registry rather than listed by hand, so a new
entity is protected the moment it is added instead of being accidentally
unguarded. Grants are wildcard patterns (`*:read`, `customers:*`, `*:*`); there
are no deny rules, and absence is denial.

### The matrix

Observed by calling the API as each role, not read off the source. "Business"
is every registry entity except the six Config ones (`party-groups`,
`lead-sources`, `pipelines`, `pipeline-stages`, `lost-reasons`,
`item-categories`) — 19 keys. "Config" is those six. "Platform" is the eight
above.

| Role | read | remark | create / update | delete | codes |
|---|---|---|---|---|---|
| **Admin** | everything | everything | everything | everything | 165 |
| **Partner** | everything | everything | business + config (25) | business only (19) | 135 |
| **Operator** | everything | everything | business only (19) | — | 104 |
| **Advisor** | everything | everything | `tasks` only | — | 68 |
| **Viewer** | everything | — | — | — | 33 |

The shape of it is that **read is generous and delete is not**. Everyone above
Viewer reads the whole platform, because Nishant and Hemish are meant to see
everything. Deletion is the one irreversible action, so only Admin and Partner
hold it — and Partner's delete stops at business records: dropping a pipeline
stage or a lead source out from under live leads is not a thing a non-Admin
should be able to do by accident.

**Only Admin writes to the platform surfaces.** Partner, Operator, Advisor and
Viewer can read `users`, `roles`, `permissions`, `organisations`, `products`,
`workspaces`, `feedback` and `audit`, and remark on them, but cannot create,
change or delete any of them. Partner is "runs the business", not "runs the
platform".

Three routes are deliberately outside this: `POST /api/feedback` checks nothing
beyond being signed in — raising your hand should not need a grant, so
`feedback:create` exists as a code and is never asserted. `/api/dashboard/*`
and `/api/notifications/*` are likewise authenticated but not
permission-checked; the dashboards only aggregate rows the caller can already
list, and a notification belongs to its own user. `/api/search` covers platform
config records only (users, organisations, products, workspaces, roles) and is
not permission-checked either — treat it as a nav aid, not a data surface, and
note it does **not** search the CRM.

`remark` is deliberately separate from `update`: an advisor can add to a
record's history without being able to alter the record. Viewer is the only
role without it.

Partner and Operator hold `invoices:create` / `update` / `delete` because
`invoices` counts as a business entity. It makes no difference — the route
refuses every write with `405` regardless of role. `can` reports the
permission; `read_only` reports the refusal. Check both.

### What a denial looks like

Captured as `hemish@neonir.com` (Advisor):

```bash
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8077/api/customers/2
```

```json
{"detail":"Your role (Advisor) cannot delete Customers."}
```

`403`, with the role and the action named so the message is actionable rather
than a bare "Forbidden". The same account, same run:

```
POST   /api/customers        ->  403  {"detail":"Your role (Advisor) cannot create Customers."}
PATCH  /api/customers/2      ->  403  {"detail":"Your role (Advisor) cannot update Customers."}
DELETE /api/tasks/1          ->  403  {"detail":"Your role (Advisor) cannot delete Tasks."}
POST   /api/users            ->  403  {"detail":"Your role (Advisor) cannot create Users."}
GET    /api/customers        ->  200
GET    /api/users            ->  200
GET    /api/audit            ->  200
POST   /api/tasks            ->  200
POST   /api/customers/2/remarks -> 200
```

A `403` is a policy answer, not a transient failure. Do not retry it.

### Where grants live

Roles the platform defines (`Admin`, `Partner`, `Advisor`, `Operator`,
`Viewer`) take their grants from **code** — `permissions_for()` looks the role
name up in `permissions.ROLES` and expands the patterns — so a grant change
ships with a deploy instead of needing a data migration. The `permissions` table
and `role_permissions` rows are kept in step by `permissions.seed()` at boot, so
the Permissions screen shows the truth, but they are not what the check reads. A
hand-made role whose name is not in `ROLES` falls back to its linked rows.

## Start here: `GET /api/meta/entities`

This publishes the registry. It is the only thing an agent should hardcode —
every path, column, field, filter and action below is derived from it, so a new
entity appears here the moment it is added, and a client that reads it never
needs updating.

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8077/api/meta/entities
```

**It requires a token.** Without one it is a `401`, not a trimmed public
response — it exposes every field of every table and the whole workspace layout.
`/api/catalog` is the public surface; the data behind it is not. See
"Discovery".

Trimmed to one entity (`leads`):

```json
{
  "count": 25,
  "refs": {"users": {"path": "/api/users", "title_field": "name"}},
  "can": {"leads": {"read": true, "create": true, "update": true, "delete": true, "remark": true}, "…": {}},
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
      "read_only": false,
      "can": {"read": true, "create": true, "update": true, "delete": true, "remark": true},
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

Two keys were added when authorisation and the Zoho mirror landed:

* **`can`** — appears twice, once at the top level keyed by entity (33 keys:
  the 25 registry entities plus the eight platform surfaces) and once inside
  each entity, scoped to the caller's role. The SPA reads the per-entity one to
  hide buttons it cannot use.
* **`read_only`** — `true` only on `invoices`. It is not the same thing as
  having no `can`: an Admin's `can.invoices` says `create: true`, and the route
  still answers `405`. `read_only` is the route's answer; `can` is the role's.
  Check `read_only` first.

The 25 keys and their paths, as returned today, grouped by workspace:

```
CRM         customers /api/customers          contacts /api/contacts
            leads /api/leads                  services /api/services
            catalog-products /api/catalog-products
            projects /api/projects            milestones /api/milestones
            project-members /api/project-members

Config      party-groups /api/party-groups    lead-sources /api/lead-sources
            pipelines /api/pipelines          pipeline-stages /api/pipeline-stages
            lost-reasons /api/lost-reasons    item-categories /api/item-categories

Work        tasks /api/tasks                  work-streams /api/work-streams
            work-stream-members /api/work-stream-members

Tickets     tickets /api/tickets              job-types /api/job-types
            sla-policies /api/sla-policies

Comms       conversations /api/conversations  channels /api/channels

Accounting  contracts /api/contracts          billing-schedule /api/billing-schedule
            invoices /api/invoices            (read-only)
```

Two keys are not what you would guess, and both are deliberate:

* `catalog-products`, not `products` — `/api/products` is the platform's own
  product-config route, and `check_route_collisions()` in `backend/crud.py`
  refuses to boot if a registry key would shadow a hand-written one.
* `job-types`, on the table `ticket_categories` — the UI term and the module
  registry's table name disagree, and the registry entry carries both.

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

Each checks one permission before it runs — `<key>:read`, `<key>:create`,
`<key>:update`, `<key>:delete`, `<key>:remark` — and answers `403` if the
caller's role does not hold it. On `invoices` the four write routes answer `405`
before the permission check matters at all.

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

Remarks, activities and attachments are attached polymorphically by
`entity_type` + `entity_id`, with no foreign key, so nothing cascades them at the
database level. `delete_row` removes them explicitly instead. The audit trail is
deliberately kept — it is the record that the delete happened — and a record's
detail page scopes its `_audit` to that row's own lifetime, so a reused id never
shows a previous record's history.

Verified end to end. A customer with one remark, deleted, and its id reused by a
different record:

```
POST   /api/customers                 -> id 19, "Recycle Probe A"
POST   /api/customers/19/remarks      -> 1 remark
DELETE /api/customers/19              -> 200
       comments WHERE entity_type='parties' AND entity_id=19  ->  0 rows
       (a new row is then inserted at id 19, "Recycled Probe B")
GET    /api/customers/19  ->  "_remarks": [], "_audit": []
```

The dead record's trail is still readable where it belongs — through the audit
endpoint, which is not scoped to a live row:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8077/api/audit?entity_type=parties&entity_id=19'
# -> count 3: delete / remark / create, all labelled "Recycle Probe A"
```

## `invoices` is read-only

`invoices` mirrors Zoho Books, which is the only place an invoice may be raised
or changed. Every write is refused, for every role including Admin:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"invoice_number":"X-1"}' http://127.0.0.1:8077/api/invoices
```

```json
{"detail":"Invoices is a read-only mirror of Zoho Books. Raise or edit it in Zoho Books; HQ reflects it."}
```

`405` — same body and status for `POST /api/invoices`, `PATCH
/api/invoices/{id}` and `DELETE /api/invoices/{id}`. The registry entry carries
`"read_only": true` and an empty `fields[]`, so there is nothing writable to
send in the first place.

`GET /api/invoices`, `GET /api/invoices/{id}` and both remark routes work
normally — a remark is HQ's own commentary on a mirrored document, not an edit
to it.

Allowing a write here would create a second, divergent set of books. See
`docs/CRM.md` → "Zoho Books owns the money" for the configuration and the
OAuth scopes.

## Dashboards

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8077/api/dashboard/stats?workspace=tickets'
```

```json
{"stats":[{"l":"Open tickets","v":"0","d":"→ awaiting us"},
          {"l":"Unassigned","v":"0","d":"↘ nobody owns these"},
          {"l":"Breaching SLA","v":"0","d":"→ within promise"},
          {"l":"Urgent","v":"0","d":"→ high or urgent"},
          {"l":"Resolved this month","v":"0","d":"↗ since the 1st"},
          {"l":"Job types","v":"8","d":"→ configured"}]}
```

Six tiles, always: `l` label, `v` value, `d` a one-line note. Accepted
`workspace` values are `crm`, `work`, `tickets`, `comms` (`communication` is
accepted as an alias), `accounting` and `hq`. **An unrecognised value is not an
error** — it falls back to the `hq` platform view and returns `200`. Omitting
the parameter does the same.

`GET /api/dashboard/trend?workspace=…` returns the six-month cumulative growth
of that workspace's primary record — `parties` for CRM, `tasks` for Work,
`tickets`, `conversations`, `contracts`, and everything with a `created_at` for
`hq`:

```json
{"points":[{"label":"Feb","value":0},{"label":"Mar","value":0},{"label":"Apr","value":0},
           {"label":"May","value":0},{"label":"Jun","value":0},{"label":"Jul","value":17}],
 "label":"Customers"}
```

Every figure is a live count or sum over a table another workspace writes.
There is no dashboard table and no cache, so a tile cannot diverge from the list
it summarises. Source: `backend/dashboards.py`.

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

There is no `expand`. It was once reserved and ignored; it is now an unknown
filter like any other and returns `400`:

```
GET /api/customers?expand=x
-> 400 {"detail":"Unknown filter 'expand' for customers. Valid filters: billing_address, city, …"}
```

### Column filters

Any other query parameter is matched against a column of the same name:

```bash
curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8077/api/customers?industry=Water%20Treatment'
# -> total 9

curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8077/api/tasks?external_ref=gtasks:AbC123'
# -> total 1, rows[0].external_ref == "gtasks:AbC123"
```

Three gotchas, all verified:

* **A parameter that is not a column is a `400`,** listing the valid filters.
  A typo'd filter name fails loudly rather than quietly returning every row —
  which is the failure that matters, because a client asking "does this record
  exist?" with a misspelled column would otherwise get the whole table back and
  conclude yes.
* **Repeating a parameter means OR.** (One column cannot equal two values at
  once, so ANDing them could only ever return zero.) Captured:

  ```
  ?stage=Testing                            -> total 1
  ?stage=Onboarding%20Completed             -> total 4
  ?stage=Testing&stage=Onboarding%20Completed -> total 5
  ```

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

`overdue` respects its value: `?overdue=true` returns rows past their due date
and not done or cancelled, `?overdue=false` returns the rest — including rows
with no due date at all. Omit it to not filter. On an entity with no `due_date`
column it is a `400`: `{"detail":"'customers' has no due_date to be overdue
against"}`.

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
  "count": 2,
  "limit": 100,
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

Requires `audit:read`, which every role holds. Parameters: `entity_type` (the
**table** name, e.g. `parties`, not the registry key `customers`), `entity_id`,
`limit` (1–500, default 100), `offset`. Newest first.

**`count` is the number of entries actually returned**, not a total and not an
echo of `limit`. `limit` echoes what was asked for. Paginate on
`count < limit`. Verified against the same database in one run:

```
?limit=3    ->  {"count": 3, "limit": 3,   "offset": 0}   # 3 entries
?limit=500  ->  {"count": 6, "limit": 500, "offset": 0}   # 6 entries — that is all of them
```

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
| 400 | Unknown filter name | `{"detail":"Unknown filter 'expand' for customers. Valid filters: …"}` |
| 400 | `overdue` on an entity with no `due_date` | `{"detail":"'customers' has no due_date to be overdue against"}` |
| 401 | No/invalid token | `{"detail":"Could not validate credentials"}` |
| 403 | Role lacks the permission | `{"detail":"Your role (Advisor) cannot delete Customers."}` |
| 404 | Unknown registry key | `{"detail":"Unknown entity 'widgets'"}` |
| 404 | Row missing, or outside the entity's scope | `{"detail":"Service 9 not found"}` |
| 405 | Editing or deleting remark history | `{"detail":"Method Not Allowed"}` |
| 405 | Writing to `invoices` | `{"detail":"Invoices is a read-only mirror of Zoho Books. …"}` |
| 409 | Duplicate natural key | `{"detail":"A customer with those details already exists. Names must be unique within the organisation."}` |
| 409 | Conversion would collide with an existing customer | `{"detail":"A customer named '…' already exists (id 18). …"}` |
| 422 | `limit`/`offset` out of range | FastAPI validation body |

A duplicate natural key is a `409`, not a `500`. `_commit()` catches the
`IntegrityError`, rolls back and translates it, because a second customer with
the same name is a conflict the caller can act on, not a server fault:

```
POST /api/customers {"display_name":"Dup Probe Ltd"}   -> 200
POST /api/customers {"display_name":"Dup Probe Ltd"}   -> 409
```

## Discovery

| Path | Auth | What |
|---|---|---|
| `GET /api/catalog` | Public | Every endpoint with a copy-paste `usage` and an example `response`. 220 on this build. |
| `GET /api/cli` | Public | The `hq-cli` command reference. |
| `GET /api/meta/entities` | Token | The registry: every field of every table, plus the workspace layout and your `can` map. |

`/api/catalog` no longer drifts. Its per-entity half is generated from the
registry by `crud.catalog_entries()` — 175 of the 220 entries — so an entity
added to `backend/registry.py` appears in the catalogue on the next boot. The
remaining 45 are hand-written and cover the bespoke platform routes — auth,
users, roles, permissions, organisations, products, workspaces, dashboards,
search, notifications, audit and the meta routes — which are not
registry-driven and still have to be maintained by hand. Before it was
generated the list
claimed 39 endpoints while 58 existed, which is worse than publishing nothing:
an agent that trusts a stale catalogue concludes a route does not exist.

The two public endpoints are public by design, so an agent can plan before it
authenticates. **The data behind them is not.** `GET /api/meta/entities`
requires a token — it exposes every field of every table and the whole workspace
layout — and returns `401` without one.

## Not implemented

Be clear about the edges:

* **Communication has no ingestion.** No webhook, no polling job, no provider
  client — nothing writes a message into HQ. `conversation_messages` has no
  registry entry and therefore no route at all, so message text cannot be read
  or written through the API. `conversations` and `channels` are ordinary CRUD.
  The three-pane inbox UI is not built; the Comms workspace renders both as
  plain tables.
* **Nothing calls the Zoho Books client.** `backend/zoho.py` is complete and
  tested, but no route, job or CLI command imports it. The Zoho figures in the
  database were written by the seed from a manual read. `zoho_invoices` is empty.
* **No SLA clock.** Nothing computes `first_response_due_at` /
  `resolution_due_at` from an `sla_policies.targets` entry, and nothing sets the
  breach flags. The columns are writable; they are not calculated.
* `activities`, `attachments`, `task_participants`, `task_dependencies`,
  `saved_views` and `terminology_overrides` are tables with no REST route.
  `GET /api/activities` → `404 Unknown entity 'activities'`.
* No bulk create/update/delete endpoint. Loop.
* No cursor pagination, no `ETag`, no `If-Match`, no optimistic locking. Two
  concurrent PATCHes: last write wins, and both are in the audit log.
* No rate limiting.
* **Permissions are enforced, but reads are not row-scoped.** A role either sees
  an entity or it does not; there is no "only your own customers". Every role
  above Viewer reads everything, by design.
* `organisation_id` is stamped from the caller on create but is **not** applied
  as a filter on read. Listing an entity returns rows across organisations.
* `POST /api/auth/logout` clears the cookie but does not revoke the JWT. There
  is no token blacklist, so a leaked token stays valid for its week.
