#!/usr/bin/env python3
"""TabDesk on Postgres — the dialect path production actually runs.

``tests/tabdesk_test.py`` proves the logic on SQLite, which is what local dev
uses. It therefore proves almost nothing about the code that only runs in
production: the guarded ``::numeric`` casts in the views, and the ``@>``
containment used for array filters. Both are written per dialect, and a bug in
either is invisible locally and total in production.

So this suite runs the same behaviours against a real Postgres. It is SKIPPED,
not failed, when no server is configured — a developer without one still gets a
green suite, they just do not get this coverage.

    TABDESK_PG_DSN=postgresql://user:pass@127.0.0.1:5433/scratch \\
        python3 tests/tabdesk_postgres_test.py

Point it ONLY at a throwaway database: setUp drops and recreates every table.

Use the same MAJOR version as production (hq.dotsai.in runs Postgres 17). CI
pins `postgres:17-alpine` for this reason — a dialect suite run against a
different major than production is most of the way to not testing it at all.
"""

import os
import sys
import unittest

DSN = os.getenv("TABDESK_PG_DSN", "").strip()

os.environ.setdefault("SECRET_KEY", "test-only")
# Set before importing backend.database, which reads it at import time.
if DSN:
    os.environ["DATABASE_URL"] = DSN

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if DSN:
    from sqlalchemy import text

    from backend import crm_models  # noqa: F401  (registers tables)
    from backend import permissions, tabdesk_access as access, tabdesk_models as tm
    from backend import tabdesk_sql as tsql
    from backend.database import Base, SessionLocal, engine
    from backend.models import Organisation, Role, User


def drop_all_tabdesk_views(bind):
    """Drop every TabDesk view before dropping tables.

    Not a test convenience — it documents a real operational consequence of the
    views. On Postgres a view DEPENDS on tabdesk_rows, so `DROP TABLE
    tabdesk_rows` fails with DependentObjectsStillExist while any view exists.
    SQLite does not enforce that dependency, so local dev never reveals it. Any
    future migration that alters or drops tabdesk_rows has to do this first.
    """
    with bind.begin() as conn:
        names = [
            row[0] for row in conn.execute(text(
                "SELECT table_name FROM information_schema.views "
                "WHERE table_schema = current_schema() AND table_name LIKE 'tabdesk_v_%'"
            )).fetchall()
        ]
        for name in names:
            conn.execute(text('DROP VIEW IF EXISTS "%s" CASCADE' % name))
    return len(names)


@unittest.skipUnless(DSN, "set TABDESK_PG_DSN to a throwaway Postgres to run these")
class PostgresDialect(unittest.TestCase):
    def setUp(self):
        self.assertEqual(engine.dialect.name, "postgresql",
                         "TABDESK_PG_DSN must point at Postgres, not %s" % engine.dialect.name)
        drop_all_tabdesk_views(engine)
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()
        self.org = Organisation(name="Z9S-AI", slug="z9s-ai")
        self.db.add(self.org)
        self.db.commit()
        permissions.seed(self.db, self.org.id)
        role = self.db.query(Role).filter(Role.name == "Admin").first()
        self.me = User(email="pg@test.local", password_hash="x", name="PG",
                       role_id=role.id, organisation_id=self.org.id)
        self.db.add(self.me)
        self.db.commit()

        self.tbl = tm.TabDeskTable(organisation_id=self.org.id, name="Site visits",
                                   slug="site-visits", created_by_id=self.me.id)
        self.db.add(self.tbl)
        self.db.commit()

        self.cols = {}
        for position, (key, kind) in enumerate([
            ("site", "text"), ("amount", "money"), ("visited", "date"),
            ("seen_at", "datetime"), ("status", "select"), ("tags", "multiselect"),
            ("done", "checkbox"), ("links", "relation"),
        ]):
            column = tm.TabDeskColumn(
                table_id=self.tbl.id, key=key, label=key.title(), type=kind, position=position,
                options=["Open", "Closed"] if kind == "select" else (
                    ["urgent", "site"] if kind == "multiselect" else []),
                ref_kind="entity" if kind == "relation" else None,
                ref_target="customers" if kind == "relation" else None,
            )
            self.db.add(column)
            self.cols[key] = column
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def add(self, **data):
        row = tm.TabDeskRow(table_id=self.tbl.id, organisation_id=self.org.id,
                            data=data, created_by_id=self.me.id)
        self.db.add(row)
        self.db.commit()
        return row

    def raw_insert(self, json_text):
        """Insert bypassing coercion, the way a legacy row or a hand edit would."""
        self.db.execute(text(
            "INSERT INTO tabdesk_rows (table_id, data, created_at, updated_at) "
            "VALUES (:t, CAST(:d AS json), NOW(), NOW())"
        ).bindparams(t=self.tbl.id, d=json_text))
        self.db.commit()

    def sites(self, key, op, values):
        clause = tsql.filter_clause(self.db, tm.TabDeskRow, self.cols[key], op, values, self.me)
        rows = self.db.query(tm.TabDeskRow).filter(
            tm.TabDeskRow.table_id == self.tbl.id).filter(clause).all()
        return sorted((r.data or {}).get("site") for r in rows)

    # ── filters ─────────────────────────────────────────────────────────────

    def test_numeric_filter_over_json(self):
        self.add(site="Warangal", amount=45000)
        self.add(site="Vasundhara", amount=12500)
        self.assertEqual(self.sites("amount", "gte", ["20000"]), ["Warangal"])

    def test_numeric_filter_survives_a_null(self):
        """A NULL amount must not make the whole comparison raise on Postgres."""
        self.add(site="Warangal", amount=45000)
        self.add(site="Empty", amount=None)
        self.assertEqual(self.sites("amount", "gte", ["1"]), ["Warangal"])

    def test_contains_is_case_insensitive_on_pg(self):
        self.add(site="Steel Plant")
        self.assertEqual(self.sites("site", "contains", ["steel"]), ["Steel Plant"])

    def test_has_on_multiselect_uses_json_containment(self):
        """The `@>` path. Must match by element, never by substring."""
        self.add(site="A", tags=["urgent"])
        self.add(site="B", tags=["site"])
        self.add(site="C", tags=[])
        self.assertEqual(self.sites("tags", "has", ["urgent"]), ["A"])
        self.assertEqual(self.sites("tags", "has", ["site"]), ["B"])

    def test_has_on_relation_does_not_confuse_1_and_12(self):
        """The bug a text LIKE over "[1,12]" would have: searching for 1 matching
        12. This is why containment is done as JSON, not as text."""
        self.add(site="one", links=[1])
        self.add(site="twelve", links=[12])
        self.assertEqual(self.sites("links", "has", [1]), ["one"])
        self.assertEqual(self.sites("links", "has", [12]), ["twelve"])

    def test_empty_matches_null_and_missing_key(self):
        self.add(site="has", amount=100)
        self.add(site="null", amount=None)
        self.raw_insert('{"site": "missing"}')
        self.assertEqual(self.sites("amount", "empty", ["true"]), ["missing", "null"])

    def test_date_and_datetime_filters(self):
        self.add(site="jul", visited="2026-07-12", seen_at="2026-07-12T10:30:00")
        self.add(site="jun", visited="2026-06-01", seen_at="2026-06-01T09:00:00")
        self.assertEqual(self.sites("visited", "gte", ["2026-07-01"]), ["jul"])
        self.assertEqual(self.sites("seen_at", "lt", ["2026-07-01T00:00:00"]), ["jun"])

    def test_checkbox_filter_on_pg(self):
        self.add(site="yes", done=True)
        self.add(site="no", done=False)
        self.assertEqual(self.sites("done", "eq", ["true"]), ["yes"])

    def test_sort_is_numeric_not_lexicographic(self):
        self.add(site="big", amount=45000)
        self.add(site="small", amount=12500)
        rows = self.db.query(tm.TabDeskRow).filter(
            tm.TabDeskRow.table_id == self.tbl.id
        ).order_by(tsql.sort_expression(tm.TabDeskRow, self.cols["amount"], True)).all()
        self.assertEqual((rows[0].data or {}).get("site"), "big")

    # ── views: the guarded casts ────────────────────────────────────────────

    def test_view_is_created_with_typed_columns(self):
        self.assertTrue(tsql.sync_view(self.db, self.tbl, list(self.cols.values())))
        self.add(site="Warangal", amount=45000, visited="2026-07-12")
        got = self.db.execute(text(
            'SELECT site, amount, visited FROM %s' % tsql.view_name(self.tbl)
        )).fetchall()
        self.assertEqual(got[0][0], "Warangal")
        self.assertEqual(float(got[0][1]), 45000.0)
        # A real DATE, not a string — the whole point of the typed view.
        self.assertEqual(str(got[0][2]), "2026-07-12")

    def test_one_bad_numeric_cell_does_not_break_the_view(self):
        """THE failure this design flagged as most likely.

        On Postgres (data->>'amount')::numeric RAISES on 'oops'. Unguarded, one
        bad cell takes down every column of the view for every reader — and
        because a view rebuild is deliberately non-fatal, it would fail silently.
        """
        tsql.sync_view(self.db, self.tbl, list(self.cols.values()))
        self.add(site="Good", amount=100)
        self.raw_insert('{"site": "Bad", "amount": "oops"}')

        got = self.db.execute(text(
            'SELECT site, amount FROM %s ORDER BY site' % tsql.view_name(self.tbl)
        )).fetchall()
        self.assertEqual([r[0] for r in got], ["Bad", "Good"])
        self.assertIsNone(got[0][1], "the bad cell must read as NULL")
        self.assertEqual(float(got[1][1]), 100.0)

    def test_bad_date_and_datetime_cells_do_not_break_the_view(self):
        tsql.sync_view(self.db, self.tbl, list(self.cols.values()))
        self.add(site="Good", visited="2026-07-12", seen_at="2026-07-12T10:00:00")
        self.raw_insert('{"site": "Bad", "visited": "not-a-date", "seen_at": "nope"}')
        got = self.db.execute(text(
            'SELECT site, visited, seen_at FROM %s ORDER BY site' % tsql.view_name(self.tbl)
        )).fetchall()
        self.assertEqual([r[0] for r in got], ["Bad", "Good"])
        self.assertIsNone(got[0][1])
        self.assertIsNone(got[0][2])

    def test_empty_string_in_a_numeric_cell_reads_null(self):
        """The exact value coercion is designed to prevent, proven harmless even
        if it reaches the database another way."""
        tsql.sync_view(self.db, self.tbl, list(self.cols.values()))
        self.raw_insert('{"site": "Blank", "amount": ""}')
        got = self.db.execute(text(
            'SELECT amount FROM %s' % tsql.view_name(self.tbl))).fetchall()
        self.assertIsNone(got[0][0])

    def test_checkbox_and_json_columns_in_the_view(self):
        tsql.sync_view(self.db, self.tbl, list(self.cols.values()))
        self.add(site="A", done=True, tags=["urgent"])
        got = self.db.execute(text(
            'SELECT done, tags FROM %s' % tsql.view_name(self.tbl))).fetchall()
        self.assertIs(got[0][0], True)
        self.assertEqual(got[0][1], ["urgent"])

    def test_view_rebuild_tracks_a_retyped_column(self):
        tsql.sync_view(self.db, self.tbl, list(self.cols.values()))
        self.cols["amount"].type = "text"
        self.db.commit()
        self.assertTrue(tsql.sync_view(self.db, self.tbl, list(self.cols.values())))
        self.add(site="A", amount="now text")
        got = self.db.execute(text(
            'SELECT amount FROM %s' % tsql.view_name(self.tbl))).fetchall()
        self.assertEqual(got[0][0], "now text")

    def test_view_survives_a_hostile_slug(self):
        hostile = tm.TabDeskTable(organisation_id=self.org.id, name="x",
                                  slug='x"; DROP TABLE tabdesk_rows; --',
                                  created_by_id=self.me.id)
        self.db.add(hostile)
        self.db.commit()
        self.assertTrue(tsql.sync_view(self.db, hostile, []))
        # The table it tried to drop is still there.
        self.db.execute(text("SELECT COUNT(*) FROM tabdesk_rows"))

    def test_sync_is_idempotent_on_pg(self):
        for _ in range(3):
            self.assertTrue(tsql.sync_view(self.db, self.tbl, list(self.cols.values())))

    # ── access, against the real engine ─────────────────────────────────────

    def test_visible_tables_query_runs_on_pg(self):
        """The sidebar query uses IN over a subquery; make sure it compiles here."""
        rows = access.visible_tables_query(self.db, self.me).all()
        self.assertEqual([t.id for t in rows], [self.tbl.id])


if __name__ == "__main__":
    if not DSN:
        print("TABDESK_PG_DSN not set — skipping the Postgres dialect suite.")
    unittest.main(verbosity=2)
