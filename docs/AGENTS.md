# Agents

How an AI agent operates HQ. Read `docs/API.md` for the route reference; this
document is the operating discipline on top of it.

HQ is built to be driven by an agent. The whole surface is generated from one
declarative registry, published at `GET /api/meta/entities`, so an agent that
reads that endpoint knows every entity, every field, every filter and every
action — including entities added after the agent was written.

## The contract

**Fetch `GET /api/meta/entities`. Derive everything else from it. Hardcode
nothing but that one path.**

```bash
curl -s https://hq.dotsai.in/api/meta/entities
```

It requires a token: it exposes every field of every table, so it is not a
public surface. `/api/catalog` stays public if you need to plan before you
authenticate.

From each entry you get:

| Key | Use it for |
|---|---|
| `path` | The base URL for CRUD. Never construct `/api/<guess>`. |
| `fields[]` | The writable keys, with `type`, `options`, `required`, `default`. Validate locally before POSTing. |
| `columns[]` | What a human sees in a list — use it to decide what to show or summarise. |
| `search[]` | Which columns `?q=` actually searches. Searching for something outside this list finds nothing. |
| `saved_views[]` | Named filter sets. Prefer `?view=Open` over re-deriving the filter. |
| `actions[]` | Non-CRUD operations, with `method` and `path` (e.g. lead convert, add remark). |
| `relations[]` | Children returned on the detail route, under `_related`. |
| `scope` | A hidden discriminator you cannot override (Services vs Products). |
| `title_field` | Which column is the row's human name. |
| `key_facts[]` | The fields a human considers load-bearing. Good default for a summary. |
| `can` | What **your** role may do here: `read`, `create`, `update`, `delete`, `remark`. Check it before you plan a write, not after you get a 403. |
| `read_only` | `true` means the route refuses every write, whatever `can` says. Only `invoices` today. |

Twenty-five entities across six workspaces are published today (`"count": 25`) —
CRM, Config, Work, Tickets, Comms, Accounting. Do not carry a list of them in
your head or your prompt; read it.

Things that will bite you if you hardcode instead:

* The catalogue's product entity is keyed **`catalog-products`**, not
  `products` — `/api/products` is a different, pre-existing route.
* The helpdesk's category entity is keyed **`job-types`** on the table
  `ticket_categories`. The UI term and the table name disagree on purpose.
* `services` and `catalog-products` are the same table split by `scope`.
* The audit endpoint keys off the **table** name (`parties`), not the registry
  key (`customers`). `entity_type` in each registry entry gives you the mapping.
* `can` and `read_only` are two different answers. An Admin's
  `can.invoices.create` is `true` and `POST /api/invoices` is still `405`.
  Check `read_only` first.

## Authenticate, and declare yourself

```bash
TOKEN=$(curl -s -X POST https://hq.dotsai.in/api/auth/login \
  -H 'Content-Type: application/json' \
  -H 'X-HQ-Client: agent' \
  -d '{"email":"'"$HQ_EMAIL"'","password":"'"$HQ_PASSWORD"'"}' | jq -r .access_token)
```

Then, **on every single request**:

```
Authorization: Bearer $TOKEN
X-HQ-Client: agent
```

`X-HQ-Client: agent` is not optional and not cosmetic. It sets `actor_kind` on
every audit entry and `source` on every task and remark you write. Without it,
your writes are indistinguishable from a human's, and the first time someone
asks "who set this to done?" the answer is wrong. The header is the only way to
set `source` — passing `{"source": "agent"}` in the body is silently dropped.

What it buys, on the record:

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/audit?entity_type=tasks&entity_id=1"
```

```
[('remark','agent','meet@dotsai.in'),
 ('update','agent','meet@dotsai.in'),
 ('create','agent','meet@dotsai.in')]
```

`actor` stays the human whose credentials you are using — the header is a claim
about the client, not an authentication factor — but `actor_kind` becomes
`agent`, and every row you touched is separable from human edits for good. The
map is in `docs/API.md`; `cli` and `system` are the other two values, and
anything else (including nothing) is treated as `user`.

Tokens last a week. Do not log the token, and do not write it into a record.

## Authorisation: 403 and 405 are answers, not failures

Every route checks a permission before it runs. The account your agent uses has
a role, and that role decides what you may do — Admin, Partner, Advisor,
Operator or Viewer. The matrix is in `docs/API.md`; the live answer for your own
token is the `can` block on `GET /api/auth/me` and on every entity in
`GET /api/meta/entities`.

```json
{"detail":"Your role (Advisor) cannot delete Customers."}
```

**Respect a `403`. Do not retry it, do not vary the request until something
gets through, and do not route around it** — no deleting-by-blanking-fields, no
asking a different endpoint for the same effect. It is a policy decision made
deliberately, and the message names the role and the action so you can report it
precisely. Retrying a policy denial is how an agent turns a working control into
a wall of audit noise.

**Respect a `405` the same way.** On `/api/invoices` it means Zoho Books owns
that document and HQ has no write surface for it at all — not for you, not for
an Admin. If a task needs an invoice raised, say so; the answer is Zoho Books,
not a workaround in HQ. On `/api/{key}/{id}/remarks` it means history is
append-only.

Plan against `can` rather than discovering limits by collision: read it once
after authenticating, and skip the writes you are not entitled to make.

## Idempotency

An agent that runs on a schedule will re-see the same source data. Three rules
keep a replay from becoming duplicate rows.

### 1. Remarks: use `external_ref`

Any remark that originates outside HQ gets a stable `external_ref` derived from
the source — a wiki row id, a Google Tasks id, a message id.

```bash
curl -s -X POST "$BASE/api/tasks/1/remarks" \
  -H "Authorization: Bearer $TOKEN" -H 'X-HQ-Client: agent' -H 'Content-Type: application/json' \
  -d '{"body":"Closed in Google Tasks on 2026-07-26.","kind":"note","external_ref":"gtasks:TASK-77#closed"}'
```

First call:

```json
{"id":5,"body":"Closed in Google Tasks on 2026-07-26.","kind":"note","source":"agent",
 "author":"Meet Deshani","author_id":1,"created_at":"2026-07-26T04:40:29.456687","duplicate":false}
```

Replay:

```json
{"detail":"Remark already recorded","id":5,"duplicate":true}
```

Both are `200`. **Branch on `duplicate`, never on the status code.** Uniqueness
is `(entity_type, entity_id, external_ref)`, so the same ref on a different
record is a different remark — make the ref specific enough to be stable and
loose enough to be reusable across runs.

It is enforced by an application-level lookup, not a database constraint. Two
simultaneous replays can still both insert. Do not run two copies of the same
sync concurrently.

### 2. Records: check before you create

There is no upsert. For anything you create repeatedly, put a stable key in a
column you can filter on, and query it first. `tasks.external_ref` exists for
exactly this and is indexed:

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H 'X-HQ-Client: agent' \
  "$BASE/api/tasks?external_ref=gtasks:TASK-77&limit=1"
```

`total: 0` → create. `total: 1` → PATCH the row you found.

Two things to know:

* **A filter on a column that does not exist is a `400`**, listing the valid
  filters. It used to be ignored, which was the dangerous behaviour: a
  misspelled column returned the *whole* list, and a "does it exist?" check
  found a random unrelated row and updated it. Now it fails loudly. Read the
  error rather than falling back to an unfiltered list.
* Only `tasks` and `comments` have an `external_ref`. For other entities, match
  on a real business key — `parties.display_name`, `items.code`,
  `projects.doc_no`, `contracts.doc_no`, `tickets.doc_no` — and accept that it
  is fuzzier. `parties`, `contracts` and several others enforce a unique natural
  key, so a duplicate create is a **`409`**, not a silent second row:

  ```
  POST /api/customers {"display_name":"Dup Probe Ltd"}  -> 200
  POST /api/customers {"display_name":"Dup Probe Ltd"}  -> 409
  {"detail":"A customer with those details already exists. Names must be unique within the organisation."}
  ```

  Treat that `409` the way you treat a conversion collision: report it, do not
  rename around it.

### 3. Conversion is safe to retry

`POST /api/leads/{id}/convert` is idempotent by design. A second call returns
the customer created by the first:

```json
{"detail":"Lead already converted","already_converted":true,"customer_id":18}
```

But a `409` means a *different* customer already owns that name:

```json
{"detail":"A customer named 'Docs Lead Co' already exists (id 18). Link it manually or rename."}
```

**Do not "fix" a 409 by inventing a new name.** That creates a duplicate company
in the system of record. Stop and ask.

## Append-only: what must never be rewritten

Two things are history, not state:

* **Remarks** (`comments`). There is no edit and no delete —
  `PATCH`/`DELETE /api/{key}/{id}/remarks` return `405`. If you were wrong, post
  a new remark with `"kind": "correction"`. Do not attempt to overwrite by
  deleting the record and recreating it.
* **The audit log** (`audit_logs`). Read-only through `GET /api/audit`. There is
  no write endpoint, and there must never be one.

The rule behind both: the trail of what was believed when has to stay readable.
An agent that tidies up history destroys the only means of auditing the agent.

Everything else — the record's own columns — is normal mutable state and is
fine to PATCH, with each change diffed into the audit log automatically.

## Worked example: syncing an external task source

Sync an external task list into HQ, twice, without creating duplicates. Every
response below was captured from a real run.

**Pass 1 — the source row `TASK-77` has not been seen before.**

Check:

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H 'X-HQ-Client: agent' \
  "$BASE/api/tasks?external_ref=gtasks:TASK-77&limit=1"
```

```json
{"entity":"tasks","total":0,"count":0,"offset":0,"rows":[]}
```

Create:

```bash
curl -s -X POST "$BASE/api/tasks" \
  -H "Authorization: Bearer $TOKEN" -H 'X-HQ-Client: agent' -H 'Content-Type: application/json' \
  -d '{"title":"Send Q3 usage report to Pioneer","external_ref":"gtasks:TASK-77",
       "owner_id":1,"due_date":"2026-07-30","priority":"high"}'
```

```json
{"id":1,"title":"Send Q3 usage report to Pioneer","status":"open",
 "source":"agent","external_ref":"gtasks:TASK-77","due_date":"2026-07-30"}
```

Note what was **not** sent: no `project_id`. `tasks.project_id` is nullable on
purpose — most real work is not project work. Do not invent a project to hang a
task on.

**Pass 2 — the same source row, now closed upstream.**

Check first, every time:

```json
{"total":1,"rows":[{"id":1,...}]}
```

It exists, so PATCH rather than POST:

```bash
curl -s -X PATCH "$BASE/api/tasks/1" \
  -H "Authorization: Bearer $TOKEN" -H 'X-HQ-Client: agent' -H 'Content-Type: application/json' \
  -d '{"status":"done"}'
```

```json
{"id":1,"title":"Send Q3 usage report to Pioneer","status":"done","source":"agent"}
```

Record *why*, idempotently:

```bash
curl -s -X POST "$BASE/api/tasks/1/remarks" \
  -H "Authorization: Bearer $TOKEN" -H 'X-HQ-Client: agent' -H 'Content-Type: application/json' \
  -d '{"body":"Closed in Google Tasks on 2026-07-26.","kind":"note","external_ref":"gtasks:TASK-77#closed"}'
```

```json
{"id":5,"kind":"note","source":"agent","duplicate":false}
```

**Pass 3 — nothing changed upstream.** The same three calls run again produce:
`total: 1` (no create), a PATCH with no field change (no audit entry is written
when nothing changes), and:

```json
{"detail":"Remark already recorded","id":5,"duplicate":true}
```

Zero duplicates across three runs.

The result is attributable:

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/audit?entity_type=tasks&entity_id=1"
```

```
[('remark','agent','meet@dotsai.in'),
 ('update','agent','meet@dotsai.in'),
 ('create','agent','meet@dotsai.in')]
```

Every row the agent touched is stamped `agent` and separable from human edits
for good.

### The shape of a well-behaved sync

1. `GET /api/meta/entities` → confirm the entity, its path and its writable fields.
2. For each source row, derive a stable `external_ref`.
3. `GET /api/{key}?external_ref=<ref>&limit=1` → decide create or update.
4. Create with POST, or PATCH **only the fields that actually differ**.
5. Post a remark with an `external_ref` for anything a human would want to know.
6. Never delete. Never touch a row whose `external_ref` is not in your source.

Step 6 matters most: a sync that deletes anything it does not recognise will
eventually eat records a human typed by hand.

## What an agent must not do

* **Do not delete records without explicit confirmation.** `DELETE` is a hard
  delete — no soft-delete flag, no undo. The only trace left is the row snapshot
  in the audit entry. The record's remarks, activities and attachments are
  removed with it, and the audit trail on a detail page is scoped to the row's
  own lifetime, so a reused id never inherits a dead record's history.
* **Do not rewrite history.** No editing remarks, no deleting them by proxy, no
  writing to the audit log. Corrections are new remarks.
* **Do not fabricate money.** `estimated_value`, `monthly_value`,
  `one_time_amount`, `monthly_amount`, `credit_limit`, milestone `amount` — if
  you do not have the figure from a source, leave it `null`. The seed file makes
  the same call explicitly: *"Money is deliberately absent: the board's per-row
  One-Time / Monthly values were not readable, and a fabricated figure in an
  accounting-adjacent system is worse than a blank one."* A guessed number in a
  CRM is indistinguishable from a real one a week later.
* **Do not invent structure to satisfy a nullable column.** No placeholder
  customer to hang a task on, no fake project, no `"Unknown"` contact. Nullable
  means nullable.
* **Do not resolve a 409 by renaming.** Report the collision.
* **Do not modify `status` on a lead to `won`.** Use `POST /api/leads/{id}/convert`;
  the registry marks the field with `"readonly_hint": "Use Convert to mark a lead
  won."` Setting it by hand skips the customer, the contact and the stamp.
* **Do not treat `X-HQ-Client` as optional**, and do not send `user` to make your
  writes look human.
* **Do not retry a 403, and do not route around it.** It is your role's answer.
  Report which permission you needed.
* **Do not try to raise or edit an invoice.** `invoices` is a read-only mirror
  of Zoho Books: `POST`, `PATCH` and `DELETE` return `405` for every role. Zoho
  Books is the system of record for money and the only place an invoice may be
  created or changed. HQ records the *plan* to bill (`contracts`,
  `billing-schedule`) and mirrors the *fact* (`invoices`). If a task needs an
  invoice, say the invoice must be raised in Zoho Books.
* **Do not link a Zoho contact to an HQ customer on a name.** The names do not
  match — Zoho's `GOA TRADING & TECHNICAL SERVICES` is HQ's "Michael Bhai" — and
  attaching the wrong receivable to the wrong customer is a money error.
  `match_contacts()` proposes; a human confirms. Nothing auto-applies.
* **Do not assume the newer modules do more than they do.** Tickets, Comms and
  Accounting have tables, registry entries and full CRUD, but:
  **Communication has no ingestion at all** — no webhook, no polling, no
  provider client, and `conversation_messages` has no route, so you can neither
  read nor write message text; and **nothing calls the Zoho client**, so the
  mirrored figures are whatever the seed wrote. `activities`, `attachments`,
  `task_participants`, `task_dependencies`, per-user `saved_views` and
  `terminology_overrides` are still tables with no API —
  `GET /api/activities` returns `404 Unknown entity 'activities'`. If a task
  needs one of these, say so rather than improvising a home for the data in
  `notes`.

## Things to know before you trust a read

* **Reads are not organisation-scoped.** `organisation_id` is stamped on create
  but is not applied as a filter on list or detail. Filter on it yourself if it
  matters.
* **Permissions are per-entity and enforced.** What you may do depends on the
  role of the account your agent signs in as. Read the `can` block; do not
  assume the write will land. But reads are *not* row-scoped — a role either
  sees a whole entity or none of it, so a read returning rows is not evidence
  that they are yours.
* **`?q=` only searches the entity's declared `search` columns.** For `tasks`
  that is `title`, `description`, `external_ref` — searching for a customer name
  will not find their tasks. Filter on `party_id` instead.
* **Repeating a query parameter means OR.** `?stage=A&stage=B` returns rows in
  either stage.
* **`overdue` respects its value.** `?overdue=true` returns overdue rows,
  `?overdue=false` returns the rest; omit it to not filter.
* **An unknown filter is a 400,** not a silent no-op — a typo'd column name
  fails loudly instead of returning the unfiltered list. There is no `expand`
  parameter; passing one is a `400` like any other unknown filter.
* **A conversation with no messages is normal, not a sync bug.** Nothing
  ingests messages. Do not conclude a thread is empty because it was read
  wrongly, and do not invent message rows to fill it.
* **No optimistic locking.** If a human edits a record between your read and your
  write, your write wins silently. Keep the gap short, and PATCH only the fields
  you mean to change.
