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

It answers `200` without a token, so you can plan before you authenticate.

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

Things that will bite you if you hardcode instead:

* The catalogue's product entity is keyed **`catalog-products`**, not
  `products` — `/api/products` is a different, pre-existing route.
* `services` and `catalog-products` are the same table split by `scope`.
* The audit endpoint keys off the **table** name (`parties`), not the registry
  key (`customers`). `entity_type` in each registry entry gives you the mapping.

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

Tokens last a week. Do not log the token, and do not write it into a record.

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

Two traps:

* **A filter on a column that does not exist is silently ignored.** Filtering on
  a misspelled column returns the *whole* list, and your "does it exist?" check
  will find a random unrelated row and update it. Confirm the column name
  against `fields[]`/`columns[]` from the registry first.
* Only `tasks` and `comments` have an `external_ref`. For other entities, match
  on a real business key — `parties.display_name`, `items.code`, `projects.doc_no`
  — and accept that it is fuzzier.

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
  in the audit entry. Deleting also orphans that record's remarks: they are
  attached by `entity_type` + `entity_id` with no foreign key and no cascade, so
  they survive the record and, on any database that reuses ids, reappear as the
  history of whatever record takes that id next.
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
* **Do not assume unbuilt modules exist.** Tickets, Communication and Accounting
  from the PRD are **not built** — no tables, no routes. Neither are
  `activities`, `attachments`, `task_participants`, `task_dependencies`,
  per-user `saved_views` or `terminology_overrides`; those tables exist but have
  no API. `GET /api/activities` returns `404 Unknown entity 'activities'`. If a
  task needs one of these, say so rather than improvising a home for the data in
  `notes`.

## Things to know before you trust a read

* **Reads are not organisation-scoped.** `organisation_id` is stamped on create
  but is not applied as a filter on list or detail. Filter on it yourself if it
  matters.
* **There are no per-entity permissions.** Any authenticated user — including
  the account your agent uses — can read and write every entity. Scope your own
  behaviour; the API will not do it for you.
* **`?q=` only searches the entity's declared `search` columns.** For `tasks`
  that is `title`, `description`, `external_ref` — searching for a customer name
  will not find their tasks. Filter on `party_id` instead.
* **Repeating a query parameter ANDs.** `?stage=A&stage=B` returns nothing. Use a
  saved view for `IN`-style filters, or make separate calls.
* **`overdue` is a filter name, not a value.** `?overdue=true` and
  `?overdue=false` behave identically; omit it to not filter.
* **`count` on `/api/audit` is the requested `limit`, not the number of entries.**
  Use `len(entries)`.
* **No optimistic locking.** If a human edits a record between your read and your
  write, your write wins silently. Keep the gap short, and PATCH only the fields
  you mean to change.
