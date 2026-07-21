# Database

HQ runs on the VPS and talks to PostgreSQL **directly** (SQLAlchemy) over the
internal `dotsai_net` Docker network. Its own FastAPI is the data/API layer, so
it does not need a PostgREST-style HTTPS API in front.

## Where HQ's data lives

HQ uses the **shared dotsai PostgreSQL** container, but in its **own database
`hq`** owned by a **dedicated least-privilege role `hq`** — *not* the `dotsai`
superuser. This gives you one place to query everything (pgAdmin) while keeping
HQ's blast radius scoped: a leaked `hq` credential can only reach the `hq`
database, never authentik or the other databases in the instance.

- HQ's DB is never exposed publicly — only `hq-portal` reaches it, internally.
- On first boot the app **creates every table and seeds defaults**
  (`Base.metadata.create_all` + the `seed_database` hook) — no manual schema or
  seed step. `database/schema.sql` / `seed.sql` are kept only as reference.
- `DB_REQUIRE=true` (set in `docker-compose.yml`) makes the app **fail fast**
  instead of silently using the local SQLite fallback if the DB is unreachable.

## One-time setup on the shared instance

Run this **once** as the `dotsai` superuser (e.g. from pgAdmin, or
`docker exec -it postgres psql -U dotsai`):

```sql
-- Dedicated login role for HQ (least privilege — owns only its own database)
CREATE ROLE hq WITH LOGIN PASSWORD '<a strong random password>';

-- HQ's own database, owned by that role so it can create its tables
CREATE DATABASE hq OWNER hq;
```

That's all the SQL HQ needs — it builds its own tables on first start.

## Deploy

1. Put the connection string in `/opt/apps/hq/.env` (mode 600, never committed):

   ```
   DATABASE_URL=postgresql://hq:<hq_role_password>@postgres:5432/hq
   SECRET_KEY=<a long random string>
   ```

   (`postgres` is the shared container's hostname on `dotsai_net`; use the actual
   name if it differs.)

2. Deploy:

   ```bash
   deploy hq          # or: docker compose up -d --build
   ```

   The app connects as `hq`, creates the 7 tables in the `hq` database, and seeds.

### Verify (also browsable in pgAdmin under the `hq` database)

```bash
docker logs hq-portal | grep -i postgres          #   Successfully connected to PostgreSQL database.
docker exec postgres psql -U hq -d hq -c '\dt'    # 7 tables
```

## Notes

- **Credentials never live in git.** `.env` is gitignored; the repo ships only
  `.env.example` with placeholders. Rotate with `ALTER ROLE hq PASSWORD '…';`
  then update `.env` and `docker compose up -d`.
- **Prefer not to share the instance?** Point `DATABASE_URL` at any other
  Postgres (e.g. a dedicated container). The app code is identical.

## Verified

The direct-connection path was validated end-to-end against a local PostgreSQL
using a **non-superuser `hq` role owning an `hq` database** (mirroring the scoped
setup above): the app connected, auto-created all 7 tables, seeded defaults, and
login/reads/writes persisted. With `DB_REQUIRE=true` and an unreachable DB,
startup fails loudly instead of falling back to SQLite.
