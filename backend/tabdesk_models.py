"""TabDesk — user-defined tables.

Five tables that together let a user define a table at runtime and enter rows
into it, with none of it reaching Python. Read ``docs/TABDESK.md`` for the design
and the reasoning; this module is the schema.

The shape to keep in mind:

    tabdesk_tables ─┬─< tabdesk_columns      the schema
                    ├─< tabdesk_rows         the data, as JSON
                    ├─< tabdesk_members      per-table access
                    └─< tabdesk_saved_views  named filter+sort

The one decision worth restating here, because breaking it corrupts data rather
than raising: ``TabDeskColumn.key`` is generated once from the label and then
never changes, because every row's JSON is already keyed under it. A rename
touches ``label`` only. Keying rows on a mutable label would mean renaming a
column silently orphaned every value in it.

Provenance columns match the CRM tables (``created_at``, ``updated_at``,
``created_by_id``, ``updated_by_id``) so a TabDesk row is no more anonymous than
a Customer is — and because ``created_by_id`` is what "a contributor may edit
their own rows" is enforced against.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.database import Base


def _org_fk():
    return Column(
        Integer,
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )


def _actor_fk():
    return Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)


# Ordered weakest to strongest. Index in this list IS the comparison, so
# `ACCESS_LEVELS.index(mine) >= ACCESS_LEVELS.index(needed)` is the whole check.
ACCESS_LEVELS = ["viewer", "contributor", "editor", "manager"]

VISIBILITIES = ["workspace", "private"]


class TabDeskTable(Base):
    """One user-defined table — a page in the TabDesk sidebar."""

    __tablename__ = "tabdesk_tables"
    __table_args__ = (
        UniqueConstraint("organisation_id", "slug", name="uq_tabdesk_tables_org_slug"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = _org_fk()

    name = Column(String(150), nullable=False)
    # Carried in the URL and used to name the SQL view. Filtered to [a-z0-9_-]
    # on the way in, so it can be interpolated into DDL safely.
    slug = Column(String(150), nullable=False, index=True)
    description = Column(Text)
    icon = Column(String(60), default="grid")
    accent = Column(String(20), default="#C8B6FF")
    # Sidebar section. Twelve tables in a flat list is unusable; this groups them.
    group_name = Column(String(100), default="Tables")

    # "workspace" — readable by anyone with tabdesk:read, no membership needed.
    # "private"   — only the creator and explicit members see it at all.
    visibility = Column(String(20), default="workspace", nullable=False)

    position = Column(Integer, default=0)
    status = Column(String(30), default="Active")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    columns = relationship(
        "TabDeskColumn",
        back_populates="table",
        cascade="all, delete-orphan",
        order_by="TabDeskColumn.position",
    )
    rows = relationship("TabDeskRow", back_populates="table", cascade="all, delete-orphan")
    members = relationship("TabDeskMember", back_populates="table", cascade="all, delete-orphan")
    saved_views = relationship(
        "TabDeskSavedView",
        back_populates="table",
        cascade="all, delete-orphan",
        order_by="TabDeskSavedView.position",
    )


class TabDeskColumn(Base):
    """One column definition. This is what the grid, the modal and the API render from."""

    __tablename__ = "tabdesk_columns"
    __table_args__ = (
        UniqueConstraint("table_id", "key", name="uq_tabdesk_columns_table_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(
        Integer, ForeignKey("tabdesk_tables.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Immutable. Every row's JSON is keyed under this; see the module docstring.
    key = Column(String(80), nullable=False)
    label = Column(String(150), nullable=False)
    type = Column(String(30), nullable=False, default="text")

    position = Column(Integer, default=0, nullable=False)
    required = Column(Boolean, default=False, nullable=False)
    # The column shown as the row's title, in the grid's first cell and as the
    # modal heading. Exactly one per table, enforced by the router.
    is_primary = Column(Boolean, default=False, nullable=False)

    # Choice list for select / multiselect: ["Open", "Closed"].
    options = Column(JSON, default=list)
    default_value = Column(JSON, nullable=True)
    help = Column(String(400))
    # Grid width as a CSS grid fraction, matching the registry's `width`.
    width = Column(String(20), default="1fr")

    # relation only. ref_kind: "tabdesk" (ref_target = a tabdesk_tables.id) or
    # "entity" (ref_target = a registry key such as "customers").
    ref_kind = Column(String(20))
    ref_target = Column(String(80))

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    table = relationship("TabDeskTable", back_populates="columns")


class TabDeskRow(Base):
    """One entry. Every value lives in `data`, keyed by column.key."""

    __tablename__ = "tabdesk_rows"

    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(
        Integer, ForeignKey("tabdesk_tables.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id = _org_fk()

    data = Column(JSON, default=dict, nullable=False)

    position = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    # Load-bearing, not decorative: "a contributor may edit their own rows" is
    # enforced against this column.
    created_by_id = _actor_fk()
    updated_by_id = _actor_fk()

    table = relationship("TabDeskTable", back_populates="rows")


class TabDeskMember(Base):
    """A grant of access to one table for one user.

    Absence of a row is NOT denial — a table with visibility="workspace" is
    readable by anyone holding tabdesk:read. A membership row only ever raises a
    user above that floor. See backend/tabdesk_access.py.
    """

    __tablename__ = "tabdesk_members"
    __table_args__ = (
        UniqueConstraint("table_id", "user_id", name="uq_tabdesk_members_table_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(
        Integer, ForeignKey("tabdesk_tables.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    access = Column(String(20), nullable=False, default="viewer")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()

    table = relationship("TabDeskTable", back_populates="members")
    # foreign_keys is required, not optional: this table has TWO paths to users
    # (the member, and whoever granted the access), so SQLAlchemy cannot infer
    # which one this relationship follows and refuses to configure any mapper.
    user = relationship("User", foreign_keys=[user_id])


class TabDeskSavedView(Base):
    """A named filter + sort + grouping over one table.

    Mirrors the registry's `saved_views`, except a user creates these. Stored as
    the same filter dicts the API accepts, so a saved view is replayable as a URL.
    """

    __tablename__ = "tabdesk_saved_views"

    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(
        Integer, ForeignKey("tabdesk_tables.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name = Column(String(150), nullable=False)
    filters = Column(JSON, default=dict)
    sort = Column(String(100))
    group_by = Column(String(80))
    # null means "every column"; otherwise a list of column keys, in order.
    visible_columns = Column(JSON, nullable=True)

    # A private view belongs to its creator alone; a shared one shows for everyone
    # who can see the table.
    is_shared = Column(Boolean, default=True, nullable=False)
    position = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by_id = _actor_fk()

    table = relationship("TabDeskTable", back_populates="saved_views")
