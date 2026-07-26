#!/usr/bin/env python3
"""Permission seeding against a database that already has rows.

Every test elsewhere starts from an empty database, which is exactly why this
bug shipped: seeding crashed only when a PRIOR catalogue existed — i.e. on every
deployed database and none of the test ones. The caller swallowed the exception,
so the app booted with no roles and every request was refused.

    python3 tests/permissions_seed_test.py
"""

import os
import sys
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-only")
_DB = os.path.join(tempfile.mkdtemp(), "seed_test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + _DB

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import crm_models  # noqa: F401,E402  (registers tables)
from backend import permissions  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.models import Organisation, Permission, Role  # noqa: E402

# The catalogue HQ shipped before the registry-derived one. `users:write` is the
# dangerous row: it is named "Create Users", which is what `users:create` is
# called now, and `permissions.name` is unique.
LEGACY = [
    ("Read Users", "users:read"),
    ("Create Users", "users:write"),
    ("Delete Users", "users:delete"),
    ("Read Roles", "roles:read"),
    ("Write Roles", "roles:write"),
    ("Read Permissions", "permissions:read"),
    ("Grant Permissions", "permissions:grant"),
    ("Read Dashboard", "dashboard:read"),
    ("Write Organisations", "organisations:write"),
]


class SeedTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()
        self.org = Organisation(name="Z9S-AI", slug="z9s-ai")
        self.db.add(self.org)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _seed_legacy(self):
        for name, code in LEGACY:
            self.db.add(Permission(name=name, code=code, description=name))
        self.db.commit()

    def _roles(self):
        return sorted(r.name for r in self.db.query(Role).all())

    def test_seeds_cleanly_on_an_empty_database(self):
        permissions.seed(self.db, self.org.id)
        self.assertEqual(self._roles(), sorted(permissions.ROLES))

    def test_seeds_over_the_legacy_catalogue(self):
        """The regression. This raised UNIQUE on permissions.name."""
        self._seed_legacy()
        permissions.seed(self.db, self.org.id)

        self.assertEqual(self._roles(), sorted(permissions.ROLES),
                         "every role must exist after seeding over old rows")
        # Retired codes are gone, so the Permissions screen shows no dead policy.
        codes = {p.code for p in self.db.query(Permission).all()}
        for _, retired in LEGACY:
            if retired not in set(permissions.all_codes()):
                self.assertNotIn(retired, codes, "retired code %s survived" % retired)
        self.assertEqual(codes, set(permissions.all_codes()))

    def test_is_idempotent(self):
        self._seed_legacy()
        permissions.seed(self.db, self.org.id)
        first = self.db.query(Permission).count()
        permissions.seed(self.db, self.org.id)
        permissions.seed(self.db, self.org.id)
        self.assertEqual(self.db.query(Permission).count(), first)
        self.assertEqual(self._roles(), sorted(permissions.ROLES))

    def test_display_names_are_unique(self):
        """The unique constraint is on `name`, so the catalogue must not collide."""
        names = [permissions.describe(c) for c in permissions.all_codes()]
        dupes = {n for n in names if names.count(n) > 1}
        self.assertFalse(dupes, "duplicate permission names: %s" % sorted(dupes))

    def test_roles_keep_their_grants_after_reseeding(self):
        self._seed_legacy()
        permissions.seed(self.db, self.org.id)
        advisor = self.db.query(Role).filter(Role.name == "Advisor").first()
        self.assertTrue(advisor.permissions, "Advisor ended up with no grants")

        held = {p.code for p in advisor.permissions}
        self.assertIn("customers:read", held)
        self.assertIn("customers:remark", held)
        # The hole this whole model exists to close.
        self.assertNotIn("customers:delete", held)
        self.assertNotIn("customers:create", held)

    def test_a_user_with_no_role_holds_nothing(self):
        permissions.seed(self.db, self.org.id)

        class Anon(object):
            role = None

        self.assertEqual(permissions.permissions_for(Anon()), set())
        self.assertFalse(permissions.has(Anon(), "customers", "read"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
