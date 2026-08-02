#!/usr/bin/env python3
"""The half of schema_sync that only Postgres can prove.

`ALTER TABLE ... ADD COLUMN` carries neither the index nor the foreign key, so a
column added at boot used to be structurally poorer than the same column on a
fresh database. The visible cost is that `ondelete="SET NULL"` never fires:
delete a job type and its id stays behind on every task that used it, rendering
as a blank label rather than an error — data quietly going wrong, which is the
worst kind.

SQLite cannot express any of this. Its ALTER is deliberately tiny — no ADD
CONSTRAINT at all — and it does not even enforce foreign keys unless
`PRAGMA foreign_keys=ON`, which this app never sets. So a SQLite run proves
nothing here, and asserting it against the engine production actually uses is
the whole point of this file.

SKIPPED without a DSN, so a developer with no local Postgres still gets a green
suite:

    TABDESK_PG_DSN=postgresql://user:pass@127.0.0.1:5432/scratch \\
        python tests/schema_sync_postgres_test.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "schema-sync-pg-test-only")

DSN = os.getenv("TABDESK_PG_DSN", "").strip()
if not DSN:
    print("SKIPPED — set TABDESK_PG_DSN to run the Postgres schema-sync suite.")
    raise SystemExit(0)

from sqlalchemy import (  # noqa: E402
    Column, ForeignKey, Integer, MetaData, String, Table, create_engine, inspect, text,
)
from sqlalchemy.orm import declarative_base  # noqa: E402

from backend import schema_sync  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (label, got, want))
        failures.append(label)


def fresh_engine():
    engine = create_engine(DSN)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS ss_child CASCADE"))
        c.execute(text("DROP TABLE IF EXISTS ss_parent CASCADE"))
    return engine


def build_old(engine):
    """The schema as it was: the child table WITHOUT the new column."""
    old = MetaData()
    Table("ss_parent", old,
          Column("id", Integer, primary_key=True),
          Column("name", String(50)))
    Table("ss_child", old,
          Column("id", Integer, primary_key=True),
          Column("title", String(50)))
    old.create_all(engine)


def current_model():
    Base = declarative_base()

    class Parent(Base):
        __tablename__ = "ss_parent"
        id = Column(Integer, primary_key=True)
        name = Column(String(50))

    class Child(Base):
        __tablename__ = "ss_child"
        id = Column(Integer, primary_key=True)
        title = Column(String(50))
        # Exactly the shape of tasks.job_type_id.
        parent_id = Column(
            Integer, ForeignKey("ss_parent.id", ondelete="SET NULL"),
            nullable=True, index=True,
        )
    return Base


def test_adds_index_and_foreign_key():
    engine = fresh_engine()
    build_old(engine)
    Base = current_model()

    Base.metadata.create_all(engine)  # the no-op that misses the column
    before = {c["name"] for c in inspect(engine).get_columns("ss_child")}
    check("create_all alone does NOT add the column", "parent_id" in before, False)

    added = schema_sync.sync(engine, Base)
    check("the column was added", "ss_child.parent_id" in added, True)

    cols = {c["name"] for c in inspect(engine).get_columns("ss_child")}
    check("column present", "parent_id" in cols, True)

    idx = {i["name"] for i in inspect(engine).get_indexes("ss_child")}
    check("its index came with it", "ix_ss_child_parent_id" in idx, True)

    fks = inspect(engine).get_foreign_keys("ss_child")
    check("its foreign key came with it", len(fks), 1)
    if fks:
        check("pointing at the right table", fks[0]["referred_table"], "ss_parent")

    # THE BEHAVIOUR THAT WAS SILENTLY LOST: ON DELETE SET NULL.
    with engine.begin() as c:
        c.execute(text("INSERT INTO ss_parent (id, name) VALUES (1, 'Bug')"))
        c.execute(text("INSERT INTO ss_child (id, title, parent_id) VALUES (1, 'a task', 1)"))
    with engine.begin() as c:
        c.execute(text("DELETE FROM ss_parent WHERE id = 1"))
        orphan = c.execute(text("SELECT parent_id FROM ss_child WHERE id = 1")).scalar()
    check("deleting the parent NULLs the child, it does not orphan it", orphan, None)


def test_is_idempotent_including_the_constraint():
    """Boot happens on every deploy; ADD CONSTRAINT has no IF NOT EXISTS."""
    engine = fresh_engine()
    build_old(engine)
    Base = current_model()

    check("first run adds it", len(schema_sync.sync(engine, Base)), 1)
    check("second run adds nothing", len(schema_sync.sync(engine, Base)), 0)
    fks = inspect(engine).get_foreign_keys("ss_child")
    check("and did not duplicate the constraint", len(fks), 1)


def test_orphans_do_not_stop_the_boot():
    """A column already holding unmatched ids cannot take the constraint.

    Saying so is right; refusing to boot over it is not — the app must still
    come up, with the column usable and the failure in the log.
    """
    engine = fresh_engine()
    build_old(engine)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE ss_child ADD COLUMN parent_id INTEGER"))
        c.execute(text("INSERT INTO ss_child (id, title, parent_id) VALUES (9, 'orphan', 999)"))

    Base = current_model()
    added = schema_sync.sync(engine, Base)   # must not raise
    check("an existing column is left alone", added, [])
    with engine.begin() as c:
        still = c.execute(text("SELECT parent_id FROM ss_child WHERE id = 9")).scalar()
    check("and its data survives", still, 999)


def test_repairs_a_bare_column_added_by_an_earlier_version():
    """The case production is actually in.

    An earlier schema_sync emitted ADD COLUMN alone, so live tables carry
    columns with no index and no foreign key. They will never be "new" again, so
    only a repair pass reaches them.
    """
    engine = fresh_engine()
    build_old(engine)
    # Exactly what the old code left behind: the column, and nothing else.
    with engine.begin() as c:
        c.execute(text("ALTER TABLE ss_child ADD COLUMN parent_id INTEGER"))

    idx = {i["name"] for i in inspect(engine).get_indexes("ss_child")}
    check("starts with no index", "ix_ss_child_parent_id" in idx, False)
    check("starts with no foreign key", len(inspect(engine).get_foreign_keys("ss_child")), 0)

    Base = current_model()
    added = schema_sync.sync(engine, Base)
    check("nothing was added — the column was already there", added, [])

    idx2 = {i["name"] for i in inspect(engine).get_indexes("ss_child")}
    check("the missing index was repaired", "ix_ss_child_parent_id" in idx2, True)
    check("the missing foreign key was repaired",
          len(inspect(engine).get_foreign_keys("ss_child")), 1)

    with engine.begin() as c:
        c.execute(text("INSERT INTO ss_parent (id, name) VALUES (2, 'Repair')"))
        c.execute(text("INSERT INTO ss_child (id, title, parent_id) VALUES (2, 't', 2)"))
        c.execute(text("DELETE FROM ss_parent WHERE id = 2"))
        orphan = c.execute(text("SELECT parent_id FROM ss_child WHERE id = 2")).scalar()
    check("and ON DELETE SET NULL now fires on it", orphan, None)


TESTS = [
    ("index and foreign key follow the column", test_adds_index_and_foreign_key),
    ("a bare column from an earlier version is repaired", test_repairs_a_bare_column_added_by_an_earlier_version),
    ("idempotent, constraint included", test_is_idempotent_including_the_constraint),
    ("orphan values do not stop the boot", test_orphans_do_not_stop_the_boot),
]

if __name__ == "__main__":
    print("schema sync on Postgres")
    for label, fn in TESTS:
        print("\n%s" % label)
        fn()
    try:
        eng = create_engine(DSN)
        with eng.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS ss_child CASCADE"))
            c.execute(text("DROP TABLE IF EXISTS ss_parent CASCADE"))
    except Exception:
        pass
    print("\n%s" % ("-" * 58))
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("all green")
