#!/usr/bin/env python3
"""The permission model — resolution order, the lockout rail, and seed safety.

Authorisation is the one place where a bug is silent and total: nothing errors,
the wrong person simply can do something. So this is tested as a MATRIX rather
than by example, and every claim the UI makes about who can do what is checked
against the function the routes actually enforce with.

Four things that can each ruin a day:

1. **Resolution order.** Role grants, then that person's exceptions on top. Deny
   beats a role that allows, allow beats a role that does not.
2. **The cached set.** Routes call `permissions.require(user, ...)` with no
   database session, so the effective set is resolved once at authentication and
   cached on the user. If that cache is wrong or missing, an exception shows in
   the UI and is ignored by the route — a deny you can see but that does not
   apply, which is worse than no deny at all.
3. **Lockout.** Removing the permission that opens the Permissions screen cannot
   be undone from inside the app. A save that would leave nobody holding it must
   be refused while it is still refusable.
4. **Seed.** `seed()` re-applies the code patterns at every boot. Once the matrix
   is saved it must stop, or a deploy silently reverts the edits.

    python3 tests/permissions_matrix_test.py
"""

import os
import sys
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-only")
_DB = os.path.join(tempfile.mkdtemp(), "perm_matrix.db")
os.environ["DATABASE_URL"] = "sqlite:///" + _DB

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from backend import crm_models  # noqa: F401,E402  (registers tables)
from backend import permissions  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.models import (  # noqa: E402
    Organisation, Permission, PermissionPolicy, Role, User, UserPermissionOverride,
)


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
            r.name: r for r in self.db.query(Role).filter(
                Role.organisation_id == self.org.id
            ).all()
        }

    def tearDown(self):
        self.db.close()

    def user(self, role_name, email=None, status="Active"):
        u = User(
            email=email or ("%s@test.local" % role_name.lower()),
            password_hash="x", name=role_name,
            role_id=self.roles[role_name].id if role_name else None,
            organisation_id=self.org.id, status=status,
        )
        self.db.add(u)
        self.db.commit()
        return u

    def override(self, user, code, effect):
        self.db.add(UserPermissionOverride(user_id=user.id, code=code, effect=effect))
        self.db.commit()

    def go_custom(self):
        """Simulate the first save of the Permissions screen."""
        self.db.add(PermissionPolicy(organisation_id=self.org.id, custom=True))
        self.db.commit()


# ── 1 · resolution order ────────────────────────────────────────────────────

class Resolution(Base_):
    def test_role_alone_is_the_default(self):
        viewer = self.user("Viewer")
        held = permissions.permissions_for(viewer, self.db)
        self.assertIn("customers:read", held)
        self.assertNotIn("customers:delete", held)

    def test_deny_beats_a_role_that_allows(self):
        """The only reason to write a deny is to take something away from
        someone whose role hands it out. A deny that loses to the role is not a
        rule."""
        operator = self.user("Operator")
        self.assertIn("customers:update", permissions.permissions_for(operator, self.db))
        self.override(operator, "customers:update", "deny")
        self.assertNotIn("customers:update", permissions.permissions_for(operator, self.db))

    def test_allow_grants_beyond_the_role(self):
        viewer = self.user("Viewer")
        self.assertNotIn("customers:create", permissions.permissions_for(viewer, self.db))
        self.override(viewer, "customers:create", "allow")
        self.assertIn("customers:create", permissions.permissions_for(viewer, self.db))

    def test_inherit_is_the_absence_of_a_row(self):
        operator = self.user("Operator")
        before = permissions.permissions_for(operator, self.db)
        self.override(operator, "customers:update", "deny")
        self.db.query(UserPermissionOverride).delete()
        self.db.commit()
        self.assertEqual(permissions.permissions_for(operator, self.db), before)

    def test_an_exception_does_not_leak_to_anyone_else(self):
        a = self.user("Operator", "a@test.local")
        b = self.user("Operator", "b@test.local")
        self.override(a, "customers:update", "deny")
        self.assertNotIn("customers:update", permissions.permissions_for(a, self.db))
        self.assertIn("customers:update", permissions.permissions_for(b, self.db))

    def test_no_role_holds_nothing(self):
        orphan = User(email="orphan@test.local", password_hash="x", name="Orphan",
                      role_id=None, organisation_id=self.org.id)
        self.db.add(orphan)
        self.db.commit()
        self.assertEqual(permissions.permissions_for(orphan, self.db), set())

    def test_admin_keeps_the_floor_even_when_denied(self):
        """An exception must not be able to lock an Admin out of the screen that
        repairs permissions."""
        admin = self.user("Admin")
        for code in sorted(permissions.ADMIN_FLOOR):
            self.override(admin, code, "deny")
        held = permissions.permissions_for(admin, self.db)
        for code in permissions.ADMIN_FLOOR:
            self.assertIn(code, held, "Admin lost %s" % code)


# ── 2 · the cached set the routes actually use ──────────────────────────────

class CachedResolution(Base_):
    def test_cache_is_what_require_reads(self):
        """auth.get_current_user resolves once and caches. If require() ignored
        that, every exception would be cosmetic."""
        operator = self.user("Operator")
        self.override(operator, "customers:update", "deny")

        operator._effective_permissions = permissions.permissions_for(operator, self.db)
        # No db passed — exactly how every route calls it.
        self.assertFalse(permissions.has(operator, "customers", "update"))
        with self.assertRaises(HTTPException) as caught:
            permissions.require(operator, "customers", "update")
        self.assertEqual(caught.exception.status_code, 403)

    def test_without_the_cache_it_falls_back_to_the_role(self):
        """Documents the fallback rather than pretending it cannot happen: with
        no session and no cache, the answer is the role's grants."""
        operator = self.user("Operator")
        self.override(operator, "customers:update", "deny")
        self.assertTrue(permissions.has(operator, "customers", "update"))

    def test_can_map_agrees_with_require(self):
        """The UI hides affordances from can_map; if it disagreed with require,
        buttons would appear that 403 on click."""
        viewer = self.user("Viewer")
        self.override(viewer, "customers:create", "allow")
        viewer._effective_permissions = permissions.permissions_for(viewer, self.db)
        can = permissions.can_map(viewer)
        for key in ("customers", "tasks", "users"):
            for action in permissions.ACTIONS:
                self.assertEqual(
                    can[key][action], permissions.has(viewer, key, action),
                    "can_map disagrees with require on %s:%s" % (key, action),
                )


# ── 3 · custom policy ───────────────────────────────────────────────────────

class CustomPolicy(Base_):
    def test_code_patterns_win_until_someone_saves(self):
        operator = self.user("Operator")
        role = self.roles["Operator"]
        role.permissions = []          # rows say nothing...
        self.db.commit()
        # ...but no save has happened, so the code patterns still answer.
        self.assertIn("customers:update", permissions.permissions_for(operator, self.db))

    def test_rows_win_after_a_save(self):
        operator = self.user("Operator")
        self.roles["Operator"].permissions = []
        self.go_custom()
        self.assertNotIn("customers:update", permissions.permissions_for(operator, self.db))

    def test_seed_does_not_revert_a_saved_matrix(self):
        """The deploy-day bug this whole mechanism exists to prevent."""
        self.go_custom()
        catalogue = {p.code: p for p in self.db.query(Permission).all()}
        role = self.roles["Operator"]
        role.permissions = [catalogue["customers:read"]]
        self.db.commit()

        permissions.seed(self.db, self.org.id)   # a deploy

        role = self.db.query(Role).filter(
            Role.organisation_id == self.org.id, Role.name == "Operator"
        ).first()
        self.assertEqual({p.code for p in role.permissions}, {"customers:read"})

    def test_seed_still_syncs_when_not_custom(self):
        role = self.roles["Operator"]
        role.permissions = []
        self.db.commit()
        permissions.seed(self.db, self.org.id)
        role = self.db.query(Role).filter(
            Role.organisation_id == self.org.id, Role.name == "Operator"
        ).first()
        self.assertIn("customers:update", {p.code for p in role.permissions})

    def test_admin_keeps_the_floor_under_a_custom_policy(self):
        self.go_custom()
        self.roles["Admin"].permissions = []
        self.db.commit()
        admin = self.user("Admin")
        held = permissions.permissions_for(admin, self.db)
        for code in permissions.ADMIN_FLOOR:
            self.assertIn(code, held)

    def test_seed_is_idempotent_under_a_custom_policy(self):
        self.go_custom()
        catalogue = {p.code: p for p in self.db.query(Permission).all()}
        self.roles["Operator"].permissions = [catalogue["customers:read"]]
        self.db.commit()
        for _ in range(3):
            permissions.seed(self.db, self.org.id)
        role = self.db.query(Role).filter(
            Role.organisation_id == self.org.id, Role.name == "Operator"
        ).first()
        self.assertEqual({p.code for p in role.permissions}, {"customers:read"})


# ── 4 · the lockout rail ────────────────────────────────────────────────────

class Lockout(Base_):
    def test_someone_always_holds_the_gate_to_begin_with(self):
        self.user("Admin")
        survivors = permissions.who_can_open_the_gate(self.db, self.org.id)
        self.assertTrue(survivors)

    def test_an_active_admin_makes_the_screen_unorphanable(self):
        """Stripping every role bare is SAFE while an Admin is active, because
        Admin keeps ADMIN_FLOOR unconditionally. That is the point of the floor:
        the role that repairs permissions cannot be edited out of the ability to
        repair them."""
        admin = self.user("Admin")
        self.user("Viewer")
        stripped = {name: set() for name in self.roles}
        survivors = permissions.refuse_if_locking_everyone_out(
            self.db, self.org.id, proposed_role_codes=stripped
        )
        self.assertEqual([u.id for u in survivors], [admin.id])

    def test_a_save_that_orphans_the_screen_is_refused(self):
        """With no active Admin there is no floor to fall back on, so stripping
        the roles really would lock the organisation out — and that is refused."""
        self.user("Partner")
        self.user("Viewer")
        stripped = {name: set() for name in self.roles}
        with self.assertRaises(HTTPException) as caught:
            permissions.refuse_if_locking_everyone_out(
                self.db, self.org.id, proposed_role_codes=stripped
            )
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn(permissions.GATE, str(caught.exception.detail))

    def test_a_disabled_admin_does_not_save_you(self):
        """The floor only helps if somebody can actually sign in and use it."""
        self.user("Admin", "sleeping@test.local", status="Disabled")
        self.user("Viewer")
        stripped = {name: set() for name in self.roles}
        with self.assertRaises(HTTPException):
            permissions.refuse_if_locking_everyone_out(
                self.db, self.org.id, proposed_role_codes=stripped
            )

    def test_a_save_that_leaves_one_holder_is_allowed(self):
        self.user("Admin")
        self.user("Operator")
        proposed = {name: set() for name in self.roles}
        proposed["Partner"] = {permissions.GATE}
        self.user("Partner")
        permissions.refuse_if_locking_everyone_out(
            self.db, self.org.id, proposed_role_codes=proposed
        )

    def test_denying_the_last_holder_by_exception_is_refused(self):
        """The subtler lockout: grants look fine, but the only person who has
        the permission is denied it personally."""
        admin = self.user("Admin")
        # Admin holds the floor unconditionally, so use a role that does not.
        self.roles["Partner"].permissions = []
        partner = self.user("Partner")
        self.db.delete(admin)
        self.db.commit()

        self.go_custom()
        catalogue = {p.code: p for p in self.db.query(Permission).all()}
        self.roles["Partner"].permissions = [catalogue[permissions.GATE]]
        self.db.commit()
        self.assertTrue(permissions.who_can_open_the_gate(self.db, self.org.id))

        with self.assertRaises(HTTPException):
            permissions.refuse_if_locking_everyone_out(
                self.db, self.org.id,
                proposed_overrides={partner.id: {permissions.GATE: "deny"}},
            )

    def test_a_disabled_user_does_not_count_as_a_holder(self):
        """Someone who cannot sign in cannot rescue anybody."""
        self.user("Admin", "disabled@test.local", status="Disabled")
        survivors = permissions.who_can_open_the_gate(self.db, self.org.id)
        self.assertEqual(survivors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
