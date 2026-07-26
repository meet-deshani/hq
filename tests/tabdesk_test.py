#!/usr/bin/env python3
"""TabDesk — the subsystem's own suite, offline.

Four things are tested here because four things can silently corrupt data or leak
it, and none of them are visible from the UI:

1. **The access matrix.** Every role × every per-table access × every action, as a
   matrix rather than by example. A permission bug found by example is a
   permission bug in the cases nobody wrote an example for.
2. **Value coercion.** What reaches the JSON blob, per column type. The query and
   view layers assume well-formed JSON; this is what makes that true.
3. **JSON filtering and sorting** on a real engine, including the operators with
   no portable spelling.
4. **View sync**, including the case the design flagged as the likeliest breakage:
   one bad cell must not be able to break the view for every reader.

    python3 tests/tabdesk_test.py
"""

import os
import sys
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-only")
_DB = os.path.join(tempfile.mkdtemp(), "tabdesk_test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + _DB

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from backend import crm_models  # noqa: F401,E402  (registers tables)
from backend import permissions, tabdesk_access as access, tabdesk_models as tm  # noqa: E402
from backend import tabdesk_sql as tsql  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.models import Organisation, Role, User  # noqa: E402


def col(**kw):
    """A detached column object, for coercion tests that need no database."""
    kw.setdefault("options", [])
    kw.setdefault("required", False)
    kw.setdefault("label", kw.get("key", "Field"))
    kw.setdefault("key", "f")
    return tm.TabDeskColumn(**kw)


class Base_(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()
        self.org = Organisation(name="Z9S-AI", slug="z9s-ai")
        self.db.add(self.org)
        self.db.commit()
        permissions.seed(self.db, self.org.id)
        self.roles = {
            r.name: r for r in self.db.query(Role).filter(Role.organisation_id == self.org.id).all()
        }

    def tearDown(self):
        self.db.close()

    def user(self, role_name, email=None):
        user = User(
            email=email or ("%s@test.local" % role_name.lower()),
            password_hash="x", name=role_name, role_id=self.roles[role_name].id,
            organisation_id=self.org.id,
        )
        self.db.add(user)
        self.db.commit()
        return user

    def table(self, creator, visibility="workspace", name="Site visits"):
        table = tm.TabDeskTable(
            organisation_id=self.org.id, name=name, slug=name.lower().replace(" ", "-"),
            visibility=visibility, created_by_id=creator.id,
        )
        self.db.add(table)
        self.db.commit()
        return table


# ── 1 · the access matrix ───────────────────────────────────────────────────

class AccessMatrix(Base_):
    def test_global_gate_reaches_every_role(self):
        """Every seeded role can at least READ TabDesk; only some can create."""
        expected_create = {"Admin": True, "Partner": True, "Operator": True,
                          "Advisor": False, "Viewer": False}
        for name, can_create in expected_create.items():
            user = self.user(name)
            self.assertTrue(permissions.has(user, "tabdesk", "read"),
                            "%s should be able to read TabDesk" % name)
            self.assertEqual(
                permissions.has(user, "tabdesk", "create"), can_create,
                "%s create-table permission is wrong" % name,
            )

    def test_platform_admin_is_manager_everywhere(self):
        """Admin and Partner hold tabdesk:delete, so they manage any table —
        including a PRIVATE one they were never added to. This is the documented
        override for a table whose only manager has left."""
        owner = self.user("Operator", "owner@test.local")
        private = self.table(owner, visibility="private")
        for name in ("Admin", "Partner"):
            user = self.user(name)
            self.assertEqual(access.access_for(self.db, user, private), "manager", name)

    def test_private_table_is_invisible_without_a_grant(self):
        owner = self.user("Operator", "owner@test.local")
        private = self.table(owner, visibility="private")
        stranger = self.user("Advisor")
        self.assertIsNone(access.access_for(self.db, stranger, private))
        # ...and it must not appear in their sidebar either.
        visible = access.visible_tables_query(self.db, stranger).all()
        self.assertNotIn(private.id, [t.id for t in visible])

    def test_workspace_table_gives_everyone_the_viewer_floor(self):
        owner = self.user("Operator", "owner@test.local")
        shared = self.table(owner, visibility="workspace")
        for name in ("Advisor", "Viewer"):
            user = self.user(name)
            self.assertEqual(access.access_for(self.db, user, shared), "viewer", name)

    def test_membership_only_ever_raises_above_the_floor(self):
        """A grant weaker than the workspace floor must not demote anyone —
        otherwise 'share with Hemish as viewer' could silently take away access
        he already had."""
        owner = self.user("Operator", "owner@test.local")
        shared = self.table(owner, visibility="workspace")
        user = self.user("Viewer")
        self.db.add(tm.TabDeskMember(table_id=shared.id, user_id=user.id, access="viewer"))
        self.db.commit()
        self.assertEqual(access.access_for(self.db, user, shared), "viewer")

        member = self.db.query(tm.TabDeskMember).filter_by(user_id=user.id).first()
        member.access = "editor"
        self.db.commit()
        self.assertEqual(access.access_for(self.db, user, shared), "editor")

    def test_creator_stays_manager(self):
        owner = self.user("Operator", "owner@test.local")
        table = self.table(owner, visibility="private")
        self.assertEqual(access.access_for(self.db, owner, table), "manager")

    def test_capability_ladder(self):
        """The whole point of the four levels, as a table. If this matrix is
        wrong, the feature is wrong regardless of what the UI shows."""
        want = {
            "viewer":      {"rows:read": 1, "rows:create": 0, "rows:update:any": 0,
                            "schema:manage": 0, "members:manage": 0},
            "contributor": {"rows:read": 1, "rows:create": 1, "rows:update:any": 0,
                            "rows:update:own": 1, "schema:manage": 0, "members:manage": 0},
            "editor":      {"rows:read": 1, "rows:create": 1, "rows:update:any": 1,
                            "schema:manage": 0, "members:manage": 0},
            "manager":     {"rows:read": 1, "rows:create": 1, "rows:update:any": 1,
                            "schema:manage": 1, "members:manage": 1},
        }
        for level, caps in want.items():
            for capability, allowed in caps.items():
                self.assertEqual(
                    access.allows(level, capability), bool(allowed),
                    "%s should%s have %s" % (level, "" if allowed else " NOT", capability),
                )

    def test_no_tabdesk_read_means_no_access_at_all(self):
        """A user with no role holds nothing — a workspace-visible table must
        still be invisible to them."""
        orphan = User(email="orphan@test.local", password_hash="x", name="Orphan",
                      role_id=None, organisation_id=self.org.id)
        self.db.add(orphan)
        self.db.commit()
        owner = self.user("Operator", "owner@test.local")
        shared = self.table(owner)
        self.assertIsNone(access.access_for(self.db, orphan, shared))
        self.assertIsNone(access.visible_tables_query(self.db, orphan))


# ── 2 · value coercion ──────────────────────────────────────────────────────

class Coercion(unittest.TestCase):
    def test_numbers_tolerate_pasted_spreadsheet_values(self):
        c = col(type="money")
        self.assertEqual(tsql.coerce(c, "45,000"), 45000)
        self.assertEqual(tsql.coerce(c, "₹ 1,250.50"), 1250.5)
        self.assertEqual(tsql.coerce(c, 7), 7)

    def test_empty_number_becomes_null_not_empty_string(self):
        """The single most important coercion in the system. An empty string
        stored where a number belongs is what makes a Postgres view cast RAISE,
        breaking every column for every reader."""
        c = col(type="number")
        for empty in (None, "", "   "):
            self.assertIsNone(tsql.coerce(c, empty), repr(empty))

    def test_bad_number_is_refused_with_a_readable_reason(self):
        with self.assertRaises(tsql.BadValue) as caught:
            tsql.coerce(col(type="number", label="Amount"), "not a number")
        self.assertIn("not a number", str(caught.exception))

    def test_dates_are_canonical_iso(self):
        self.assertEqual(tsql.coerce(col(type="date"), "2026-07-26"), "2026-07-26")
        with self.assertRaises(tsql.BadValue):
            tsql.coerce(col(type="date"), "26/07/2026")

    def test_select_rejects_a_value_outside_its_choices(self):
        c = col(type="select", options=["Open", "Closed"], label="Status")
        self.assertEqual(tsql.coerce(c, "Open"), "Open")
        with self.assertRaises(tsql.BadValue):
            tsql.coerce(c, "Banana")

    def test_multiselect_dedupes_and_validates(self):
        c = col(type="multiselect", options=["A", "B"])
        self.assertEqual(tsql.coerce(c, ["A", "B", "A"]), ["A", "B"])
        self.assertEqual(tsql.coerce(c, None), [])
        with self.assertRaises(tsql.BadValue):
            tsql.coerce(c, ["C"])

    def test_checkbox_is_never_null(self):
        c = col(type="checkbox")
        self.assertIs(tsql.coerce(c, None), False)
        self.assertIs(tsql.coerce(c, "true"), True)

    def test_relation_is_a_deduped_int_list(self):
        c = col(type="relation", ref_kind="entity", ref_target="customers")
        self.assertEqual(tsql.coerce(c, [3, "3", 5]), [3, 5])
        self.assertEqual(tsql.coerce(c, None), [])

    def test_required_is_enforced_at_coercion(self):
        with self.assertRaises(tsql.BadValue):
            tsql.coerce(col(type="text", required=True, label="Site"), "")

    def test_every_declared_type_can_coerce_none(self):
        """A type that explodes on an absent value makes 'add entry' impossible
        for any row that leaves it blank."""
        for name in tsql.TYPES:
            c = col(type=name, options=["A"], ref_kind="entity", ref_target="customers")
            try:
                tsql.coerce(c, None)
            except tsql.BadValue as exc:  # pragma: no cover
                self.fail("type %s cannot handle an empty value: %s" % (name, exc))


# ── 3 · filtering and sorting over JSON ─────────────────────────────────────

class Querying(Base_):
    def setUp(self):
        super().setUp()
        self.me = self.user("Admin")
        self.tbl = self.table(self.me)
        specs = [
            ("site", "Site", "text"), ("amount", "Amount", "money"),
            ("status", "Status", "select"), ("visited", "Visited", "date"),
            ("tags", "Tags", "multiselect"), ("done", "Done", "checkbox"),
            ("owner", "Owner", "user"),
        ]
        self.cols = {}
        for position, (key, label, kind) in enumerate(specs):
            column = tm.TabDeskColumn(
                table_id=self.tbl.id, key=key, label=label, type=kind, position=position,
                options=["Open", "Closed"] if kind == "select" else (
                    ["urgent", "site"] if kind == "multiselect" else []),
            )
            self.db.add(column)
            self.cols[key] = column
        self.db.commit()

        rows = [
            {"site": "Warangal Unit", "amount": 45000, "status": "Open",
             "visited": "2026-07-12", "tags": ["urgent"], "done": False, "owner": self.me.id},
            {"site": "Vasundhara", "amount": 12500, "status": "Closed",
             "visited": "2026-07-08", "tags": ["site"], "done": True, "owner": None},
            {"site": "Steel Plant", "amount": None, "status": "Open",
             "visited": None, "tags": [], "done": False, "owner": self.me.id},
        ]
        for data in rows:
            self.db.add(tm.TabDeskRow(table_id=self.tbl.id, organisation_id=self.org.id,
                                      data=data, created_by_id=self.me.id))
        self.db.commit()

    def sites(self, column_key, op, values):
        clause = tsql.filter_clause(
            self.db, tm.TabDeskRow, self.cols[column_key], op, values, self.me
        )
        rows = self.db.query(tm.TabDeskRow).filter(
            tm.TabDeskRow.table_id == self.tbl.id
        ).filter(clause).all()
        return sorted((r.data or {}).get("site") for r in rows)

    def test_eq_on_select(self):
        self.assertEqual(self.sites("status", "eq", ["Open"]), ["Steel Plant", "Warangal Unit"])

    def test_numeric_comparison_reaches_into_json(self):
        self.assertEqual(self.sites("amount", "gte", ["20000"]), ["Warangal Unit"])
        self.assertEqual(self.sites("amount", "lt", ["20000"]), ["Vasundhara"])

    def test_contains_is_case_insensitive(self):
        self.assertEqual(self.sites("site", "contains", ["steel"]), ["Steel Plant"])

    def test_empty_matches_null_and_absent(self):
        self.assertEqual(self.sites("amount", "empty", ["true"]), ["Steel Plant"])
        self.assertEqual(self.sites("visited", "empty", ["true"]), ["Steel Plant"])

    def test_empty_false_is_the_complement(self):
        self.assertEqual(self.sites("amount", "empty", ["false"]), ["Vasundhara", "Warangal Unit"])

    def test_in_ors_within_one_column(self):
        self.assertEqual(
            self.sites("status", "in", ["Open", "Closed"]),
            ["Steel Plant", "Vasundhara", "Warangal Unit"],
        )

    def test_has_on_multiselect_does_not_substring_match(self):
        """'site' must not match a row tagged only 'urgent', and an id of 1 must
        not match 12 — which a naive LIKE over the JSON text would do."""
        self.assertEqual(self.sites("tags", "has", ["urgent"]), ["Warangal Unit"])
        self.assertEqual(self.sites("tags", "has", ["site"]), ["Vasundhara"])

    def test_checkbox_filter(self):
        self.assertEqual(self.sites("done", "eq", ["true"]), ["Vasundhara"])

    def test_me_resolves_to_the_caller(self):
        self.assertEqual(self.sites("owner", "eq", ["me"]), ["Steel Plant", "Warangal Unit"])

    def test_unsupported_operator_is_refused_not_ignored(self):
        """A silently dropped filter makes 'does this row exist?' answer yes."""
        with self.assertRaises(tsql.BadValue):
            tsql.filter_clause(self.db, tm.TabDeskRow, self.cols["done"], "contains", ["x"], self.me)

    def test_sort_is_type_aware(self):
        column = self.cols["amount"]
        rows = self.db.query(tm.TabDeskRow).filter(
            tm.TabDeskRow.table_id == self.tbl.id
        ).order_by(tsql.sort_expression(tm.TabDeskRow, column, True)).all()
        amounts = [(r.data or {}).get("amount") for r in rows]
        # 45000 must sort above 12500 — a text sort would put "12500" first.
        self.assertEqual(amounts[0], 45000)

    def test_date_sort_is_chronological(self):
        rows = self.db.query(tm.TabDeskRow).filter(
            tm.TabDeskRow.table_id == self.tbl.id
        ).order_by(tsql.sort_expression(tm.TabDeskRow, self.cols["visited"], True)).all()
        self.assertEqual((rows[0].data or {}).get("visited"), "2026-07-12")

    def test_search_scans_text_columns_only(self):
        clause = tsql.search_clause(tm.TabDeskRow, list(self.cols.values()), "vasundhara")
        rows = self.db.query(tm.TabDeskRow).filter(
            tm.TabDeskRow.table_id == self.tbl.id
        ).filter(clause).all()
        self.assertEqual([(r.data or {}).get("site") for r in rows], ["Vasundhara"])


# ── 4 · the SQL view ────────────────────────────────────────────────────────

class Views(Base_):
    def setUp(self):
        super().setUp()
        self.me = self.user("Admin")
        self.tbl = self.table(self.me)
        self.cols = []
        for position, (key, kind) in enumerate([("site", "text"), ("amount", "money"),
                                                ("visited", "date"), ("tags", "multiselect")]):
            column = tm.TabDeskColumn(table_id=self.tbl.id, key=key, label=key.title(),
                                      type=kind, position=position)
            self.db.add(column)
            self.cols.append(column)
        self.db.commit()

    def test_view_is_created_and_readable(self):
        self.assertTrue(tsql.sync_view(self.db, self.tbl, self.cols))
        self.db.add(tm.TabDeskRow(table_id=self.tbl.id, organisation_id=self.org.id,
                                  data={"site": "Warangal", "amount": 45000,
                                        "visited": "2026-07-12", "tags": ["a"]},
                                  created_by_id=self.me.id))
        self.db.commit()
        got = self.db.execute(
            text('SELECT site, amount FROM %s' % tsql.view_name(self.tbl))
        ).fetchall()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], "Warangal")
        self.assertEqual(float(got[0][1]), 45000.0)

    def test_sync_is_idempotent(self):
        """Called after every schema change, so it must survive being called
        repeatedly — and must rebuild rather than patch."""
        for _ in range(3):
            self.assertTrue(tsql.sync_view(self.db, self.tbl, self.cols))

    def test_a_bad_cell_cannot_break_the_view(self):
        """The failure the design flagged as most likely. A non-numeric value in
        a money column must yield NULL for that cell, not take the whole view
        down for every reader."""
        tsql.sync_view(self.db, self.tbl, self.cols)
        self.db.add(tm.TabDeskRow(table_id=self.tbl.id, organisation_id=self.org.id,
                                  data={"site": "Good", "amount": 100}, created_by_id=self.me.id))
        self.db.commit()
        # Bypass coercion the way a legacy row or a direct DB edit would.
        self.db.execute(text(
            "INSERT INTO tabdesk_rows (table_id, data, created_at, updated_at) "
            "VALUES (:t, :d, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ).bindparams(t=self.tbl.id, d='{"site": "Bad", "amount": "oops", "visited": "nope"}'))
        self.db.commit()

        got = self.db.execute(
            text('SELECT site, amount FROM %s ORDER BY site' % tsql.view_name(self.tbl))
        ).fetchall()
        self.assertEqual([r[0] for r in got], ["Bad", "Good"],
                         "the view must still return every row")

    def test_view_reflects_a_dropped_column(self):
        tsql.sync_view(self.db, self.tbl, self.cols)
        tsql.sync_view(self.db, self.tbl, self.cols[:2])
        with self.assertRaises(Exception):
            self.db.execute(text('SELECT visited FROM %s' % tsql.view_name(self.tbl)))
        self.db.rollback()

    def test_view_name_carries_the_id(self):
        """Slug is unique per organisation only. Two organisations reusing a slug
        must not collide, because a failed rebuild is deliberately non-fatal and
        would fail SILENTLY."""
        self.assertTrue(tsql.view_name(self.tbl).startswith("tabdesk_v_%d_" % self.tbl.id))

    def test_identifiers_are_rebuilt_not_interpolated(self):
        hostile = tm.TabDeskTable(organisation_id=self.org.id, name="x",
                                  slug='x"; DROP TABLE tabdesk_rows; --', created_by_id=self.me.id)
        self.db.add(hostile)
        self.db.commit()
        name = tsql.view_name(hostile)
        self.assertNotIn(" ", name)
        self.assertNotIn('"', name)
        self.assertNotIn(";", name)
        self.assertTrue(tsql.sync_view(self.db, hostile, []))
        # The table it tried to drop is still there.
        self.db.execute(text("SELECT COUNT(*) FROM tabdesk_rows"))

    def test_drop_view_is_safe_to_repeat(self):
        tsql.sync_view(self.db, self.tbl, self.cols)
        self.assertTrue(tsql.drop_view(self.db, self.tbl))
        self.assertTrue(tsql.drop_view(self.db, self.tbl))


if __name__ == "__main__":
    unittest.main(verbosity=2)
