#!/usr/bin/env python3
"""Prove the boot-time column sync against a database that predates the columns.

This is the production case and the one a fresh-database test cannot reach: HQ's
tables were created months ago, so `create_all` will not look at them again, and
a new model column exists everywhere except where it matters.

Built the same way the real failure would be — a table created from an OLD
definition, then synced against the CURRENT one.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "schema-sync-test-only")

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect, text  # noqa: E402
from sqlalchemy.orm import declarative_base  # noqa: E402

from backend import schema_sync  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (label, got, want))
        failures.append(label)


def test_adds_missing_columns():
    engine = create_engine("sqlite://")

    # The schema as it was: a table with two columns.
    old = MetaData()
    Table("leads", old,
          Column("id", Integer, primary_key=True),
          Column("title", String(200)))
    old.create_all(engine)

    # The schema as it is now: three more columns on the same table.
    Base = declarative_base()

    class Lead(Base):
        __tablename__ = "leads"
        id = Column(Integer, primary_key=True)
        title = Column(String(200))
        party_id = Column(Integer, nullable=True)
        item_id = Column(Integer, nullable=True)
        converted_project_id = Column(Integer, nullable=True)

    Base.metadata.create_all(engine)  # the no-op that misses the columns
    before = {c["name"] for c in inspect(engine).get_columns("leads")}
    check("create_all alone does NOT add them", "party_id" in before, False)

    added = schema_sync.sync(engine, Base)
    after = {c["name"] for c in inspect(engine).get_columns("leads")}

    check("party_id added", "party_id" in after, True)
    check("item_id added", "item_id" in after, True)
    check("converted_project_id added", "converted_project_id" in after, True)
    check("all three reported", len(added), 3)

    # And it is usable, not merely present.
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO leads (title, party_id) VALUES ('x', 7)"))
        got = conn.execute(text("SELECT party_id FROM leads")).scalar()
    check("the new column actually stores a value", got, 7)


def test_is_idempotent():
    """Boot happens on every deploy — the second one must be a no-op."""
    engine = create_engine("sqlite://")
    old = MetaData()
    Table("leads", old, Column("id", Integer, primary_key=True))
    old.create_all(engine)

    Base = declarative_base()

    class Lead(Base):
        __tablename__ = "leads"
        id = Column(Integer, primary_key=True)
        party_id = Column(Integer, nullable=True)

    check("first run adds it", len(schema_sync.sync(engine, Base)), 1)
    check("second run adds nothing", len(schema_sync.sync(engine, Base)), 0)
    check("third run adds nothing", len(schema_sync.sync(engine, Base)), 0)


def test_refuses_to_guess_a_not_null_backfill():
    """A NOT NULL column with no default cannot be added to a table with rows."""
    engine = create_engine("sqlite://")
    old = MetaData()
    Table("leads", old,
          Column("id", Integer, primary_key=True),
          Column("title", String(200)))
    old.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO leads (title) VALUES ('existing row')"))

    Base = declarative_base()

    class Lead(Base):
        __tablename__ = "leads"
        id = Column(Integer, primary_key=True)
        title = Column(String(200))
        mandatory = Column(String(20), nullable=False)  # no default — unanswerable

    added = schema_sync.sync(engine, Base)
    check("it declined rather than guessed", added, [])
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT COUNT(*) FROM leads")).scalar()
    check("and the existing row survived", rows, 1)


def test_survives_a_table_it_cannot_touch():
    """One bad column must not stop the rest of the schema syncing."""
    engine = create_engine("sqlite://")
    old = MetaData()
    Table("leads", old, Column("id", Integer, primary_key=True))
    old.create_all(engine)

    Base = declarative_base()

    class Lead(Base):
        __tablename__ = "leads"
        id = Column(Integer, primary_key=True)
        party_id = Column(Integer, nullable=True)

    class NeverCreated(Base):
        __tablename__ = "not_in_the_database"
        id = Column(Integer, primary_key=True)
        whatever = Column(String(10), nullable=True)

    added = schema_sync.sync(engine, Base)
    check("skipped the absent table, synced the present one", added, ["leads.party_id"])


TESTS = [
    ("adds columns create_all misses", test_adds_missing_columns),
    ("idempotent across boots", test_is_idempotent),
    ("refuses to guess a NOT NULL backfill", test_refuses_to_guess_a_not_null_backfill),
    ("one absent table does not stop the rest", test_survives_a_table_it_cannot_touch),
]

if __name__ == "__main__":
    print("boot-time schema sync")
    for label, fn in TESTS:
        print("\n%s" % label)
        fn()
    print("\n%s" % ("-" * 58))
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("all green")
