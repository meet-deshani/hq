"""Add columns that `create_all` cannot.

HQ has no Alembic. `Base.metadata.create_all` builds any table that is missing
and then stops caring — it never looks *inside* a table that already exists. So
a new model column is created on a developer's fresh database and silently
absent from production, where the table was made last month. The failure lands
at runtime as `column leads.party_id does not exist`, on the first request that
touches it, which is a bad place to find out.

The alternative was a hand-run `ALTER` on the production Postgres, remembered
and typed correctly at deploy time, once per column, forever. This module does
it instead: additive, idempotent, and run at boot next to `create_all` so the
schema is whole before the first request rather than after someone remembers.

Deliberately narrow — it only ever ADDs a nullable column. It does not drop,
rename, retype or backfill anything, because those are the operations that lose
data when a guess is wrong, and a guess made at boot cannot be reviewed.
"""

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger("schema_sync")


def _sql_type(column, dialect):
    """The column's DDL type, asked of the dialect that has to run it."""
    return column.type.compile(dialect=dialect)


def sync(engine, base):
    """Add every mapped column that the live table is missing.

    Returns the list of "table.column" strings added, for the caller to log.
    Never raises: a portal that boots with a stale schema and says so is better
    than one that refuses to start and says it in a container log nobody reads.
    """
    added = []
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Could not inspect the schema, skipping column sync: %s", exc)
        return added

    for table in base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all already owns this case
        try:
            live = {c["name"] for c in inspector.get_columns(table.name)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Could not read columns of %s: %s", table.name, exc)
            continue

        for column in table.columns:
            if column.name in live:
                continue
            # A column added to a table with rows in it cannot be NOT NULL
            # without a default, and inventing one is exactly the guess this
            # module refuses to make.
            if not column.nullable and column.default is None and column.server_default is None:
                logger.warning(
                    "%s.%s is missing and NOT NULL with no default — add it by hand",
                    table.name, column.name,
                )
                continue
            try:
                ddl = 'ALTER TABLE %s ADD COLUMN %s %s' % (
                    table.name, column.name, _sql_type(column, engine.dialect),
                )
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                added.append("%s.%s" % (table.name, column.name))
            except Exception as exc:
                # Losing one column is not a reason to skip the rest, and a
                # concurrent boot that won the race is not an error.
                logger.error("Could not add %s.%s: %s", table.name, column.name, exc)

    if added:
        logger.info("Schema sync added %d column(s): %s", len(added), ", ".join(added))
    return added
