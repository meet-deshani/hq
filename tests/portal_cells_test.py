#!/usr/bin/env python3
"""Every table cell the portal builds must satisfy the row template.

The bug this exists to stop, which shipped and reached production: the row
template grew a pair of branches —

    <sc-if value="{{ cell.isLink }}">  …a link…
    <sc-if value="{{ cell.isPlain }}"> …text…

— and renderCell() was taught to set both. The LEGACY tables (Users, Roles,
Organisations, Products, Workspaces, Permissions, Feedback) build their cells in
a second place, which was not. With neither flag set, neither branch renders:
the Users table drew its header, its record count and four completely empty
rows. Nothing threw, nothing logged, and the API was returning the data
perfectly the whole time.

So the invariant is structural, not behavioural: whatever flags the row template
branches on, EVERY cell builder must set. This test reads both out of the file
and compares them, which also covers the next flag somebody adds.

Offline, no server, no browser.
"""

import os
import re
import sys

PORTAL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "static", "PortalPage.dc.html",
)

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (label, got, want))
        failures.append(label)


def cell_builders(src):
    """Every function that returns a table cell, by the shape of what it returns.

    A cell is the object with `cellStyle` in it — that is what the template
    consumes and nothing else in the file produces one, so this finds the
    builders without needing to be told their names.
    """
    out = {}
    # Top-level functions only — one chunk per `function name(` at column 0,
    # running up to the next one.
    starts = [(m.start(), m.group(1)) for m in re.finditer(r"^function (\w+)\s*\(", src, re.M)]
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(src)
        body = src[pos:end]
        if "return {" in body and "cellStyle:" in body:
            out[name] = body
    return out


def main():
    src = open(PORTAL, encoding="utf-8").read()

    # What the row template branches on: `<sc-if value="{{ cell.X }}">`.
    flags = set(re.findall(r'<sc-if value="\{\{ cell\.(\w+) \}\}"', src))
    check("the row template branches on flags", bool(flags), True)

    builders = cell_builders(src)
    check("both cell builders are found",
          set(builders) == {"renderCell", "legacyCell"}, True)

    for name, body in sorted(builders.items()):
        missing = sorted(f for f in flags if not re.search(r"\b%s\b" % f, body))
        check("%s sets every flag the template branches on (%s)"
              % (name, ", ".join(sorted(flags))), missing, [])

    # And the legacy tables must actually go through the legacy builder rather
    # than hand-rolling a cell object a third time.
    legacy_fetch = re.search(r"_fetchLegacy\(\)\{(.*?)\n  \}", src, re.S)
    check("the legacy list builds its cells with legacyCell",
          bool(legacy_fetch and "legacyCell" in legacy_fetch.group(1)), True)

    # The Users table shows what an account IS. Both were absent before.
    users_cfg = re.search(r"\n  Users: \{(.*?)\n  Roles: \{", src, re.S)
    body = users_cfg.group(1) if users_cfg else ""
    check("the Users table has a Type column", "'Type'" in body, True)
    check("the Type column reads the kind field", "u.kind === 'agent'" in body, True)

    print("\n%d checks failed" % len(failures) if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
