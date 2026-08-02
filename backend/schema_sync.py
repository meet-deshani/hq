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


def _add_index(engine, table, column):
    """Give the new column the index its model asked for.

    ADD COLUMN alone carries neither the index nor the foreign key, so a column
    added here was structurally poorer than the same column on a fresh database
    — which is exactly the divergence this module exists to close.
    """
    if not column.index:
        return
    name = "ix_%s_%s" % (table.name, column.name)
    try:
        with engine.begin() as conn:
            conn.execute(text('CREATE INDEX IF NOT EXISTS %s ON %s (%s)'
                              % (name, table.name, column.name)))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not index %s.%s: %s", table.name, column.name, exc)


def _add_foreign_key(engine, table, column):
    """Re-attach the column's foreign key, ON DELETE rule included.

    This is the difference between a link that cleans itself up and one that
    rots. Without the constraint, `ondelete="SET NULL"` never fires: deleting a
    job type leaves its id behind on every task that used it, and the label
    silently renders blank. A fresh database gets this from create_all; before
    this, production never did.

    Postgres only — SQLite cannot add a constraint to an existing table at all
    (its ALTER is deliberately tiny). Dev and CI therefore run without it, which
    is the same asymmetry the app already lives with, and the reason the
    behaviour is asserted against Postgres rather than assumed.
    """
    if engine.dialect.name != "postgresql":
        return
    fks = list(getattr(column, "foreign_keys", ()) or ())
    if not fks:
        return
    fk = fks[0]
    try:
        target = fk.column.table.name
        target_col = fk.column.name
    except Exception:  # pragma: no cover - unresolvable target
        return

    name = "fk_%s_%s" % (table.name, column.name)
    ondelete = (fk.ondelete or "").upper()
    clause = (" ON DELETE %s" % ondelete) if ondelete in (
        "SET NULL", "CASCADE", "RESTRICT", "NO ACTION", "SET DEFAULT") else ""
    try:
        with engine.begin() as conn:
            # IF NOT EXISTS is not available for ADD CONSTRAINT, so a second boot
            # would raise DuplicateObject — asked first rather than caught, so a
            # genuine failure is not swallowed by the same handler.
            exists = conn.execute(text(
                "SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}).first()
            if exists:
                return
            conn.execute(text(
                'ALTER TABLE %s ADD CONSTRAINT %s FOREIGN KEY (%s) '
                'REFERENCES %s (%s)%s' % (table.name, name, column.name,
                                          target, target_col, clause)))
        logger.info("Schema sync added constraint %s%s", name, clause)
    except Exception as exc:
        # A column with orphan values already in it cannot take the constraint.
        # Saying so is right; refusing to boot over it is not.
        logger.warning("Could not add foreign key %s: %s", name, exc)


def _repair(engine, inspector, table, live):
    """Give already-present columns the index and foreign key they should have.

    Only ever ADDS what the model already declares. It does not drop, rename or
    alter anything, so the worst case on a healthy database is two reads.
    """
    if engine.dialect.name != "postgresql":
        return  # SQLite cannot add a constraint after the fact; nothing to do
    try:
        have_idx = {i.get("name") for i in inspector.get_indexes(table.name)}
        have_fk = set()
        for fk in inspector.get_foreign_keys(table.name):
            for col in fk.get("constrained_columns") or []:
                have_fk.add(col)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not inspect %s while repairing: %s", table.name, exc)
        return

    for column in table.columns:
        if column.name not in live:
            continue
        if column.index and ("ix_%s_%s" % (table.name, column.name)) not in have_idx:
            _add_index(engine, table, column)
        if getattr(column, "foreign_keys", None) and column.name not in have_fk:
            _add_foreign_key(engine, table, column)


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
                continue
            _add_index(engine, table, column)
            _add_foreign_key(engine, table, column)

        # ...and repair the columns an EARLIER version of this module added
        # bare. Between its first release and this one it emitted ADD COLUMN
        # alone, so production is carrying columns with no index and no foreign
        # key — including four added the day this was written. They will never
        # be "new" again, so fixing them on the way past is the only thing that
        # reaches them. Both helpers ask before they write, so this is a pair of
        # cheap reads per table on an already-correct database.
        _repair(engine, inspector, table, live)

    if added:
        logger.info("Schema sync added %d column(s): %s", len(added), ", ".join(added))
    return added
