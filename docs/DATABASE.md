# Database

HQ runs on the VPS, so its FastAPI backend talks to PostgreSQL **directly** over
the internal Docker network (SQLAlchemy) — HQ's own API *is* the data/API layer,
so it does not need a PostgREST-style HTTPS data API in front (that pattern is
for apps running *off* the VPS).

## Topology — HQ owns its database

Per the "each production app gets its own Postgres container" rule, `docker-compose.yml`
bundles a dedicated database with the app:

```
  nginx ──► hq-portal (:8005→8000)      FastAPI + SQLAlchemy
                 │  private network: hq_net
                 ▼
             hq-db                       PostgreSQL 17-alpine
                                         no host port · volume hq_pgdata
```

- `hq-db` publishes **no host port** — only `hq-portal` can reach it, on `hq_net`.
- Data lives in the named volume `hq_pgdata`, so it survives rebuilds.
- One set of credentials (`DB_USER` / `DB_PASSWORD` / `DB_NAME` in `.env`)
  configures both the `hq-db` container and the app's connection to it.
- On first boot the app **creates all 7 tables and seeds defaults**
  (`Base.metadata.create_all` + the `seed_database` startup hook) — no manual
  schema or seed step. `database/schema.sql` and `database/seed.sql` remain only
  as reference.
- `DB_REQUIRE=true` (set in compose) makes the app **fail fast** rather than
  silently fall back to the local SQLite file if the database is unreachable.

## Deploying it on the VPS

Only two things are needed — everything else is automatic:

1. **Set the secrets** in `/opt/apps/hq/.env` (mode 600, never committed):

   ```
   DB_USER=hq
   DB_PASSWORD=<a strong random password>
   DB_NAME=hq
   SECRET_KEY=<a long random string>
   ```

2. **Deploy** — brings up `hq-db` then `hq-portal`:

   ```bash
   deploy hq            # or: docker compose up -d --build
   ```

   The app waits for `hq-db` to be healthy (compose `depends_on` + healthcheck),
   connects, creates the tables, and seeds defaults.

### Verify

```bash
docker compose -f /opt/apps/hq/docker-compose.yml ps    # hq-db healthy, hq-portal up
docker logs hq-portal | grep -i postgres                #   Successfully connected to PostgreSQL database.
docker exec hq-db psql -U hq -d hq -c '\dt'             # 7 tables
```

## Notes

- **Credentials never live in git.** `.env` is gitignored; the repo ships only
  `.env.example` with placeholders. Rotate a password by editing `.env` and
  running `docker compose up -d`.
- **Backups:** if the VPS backup job (`pg_dumpall` per container) discovers
  containers automatically, `hq-db` is included; otherwise add it to the backup
  list.
- **Using an external Postgres instead** (e.g. a shared instance): set
  `DATABASE_URL=postgresql://<user>:<pass>@<host>:5432/<db>` in `.env` and drop
  the `hq-db` service. The app path is identical.

## Verified

The direct-connection path was validated end-to-end against a local
**PostgreSQL 16** instance (the code is version-agnostic; PG17 behaves
identically): the app built the connection URL from the `DB_*` parts, connected,
auto-created all 7 tables, seeded the defaults, and login/reads/writes persisted.
With `DB_REQUIRE=true` and an unreachable database, startup fails loudly instead
of falling back to SQLite.
