"""Initial schema: farms, horses, riders, shows, events, classes, entries, locations, horse_location_history.

Revision ID: 20250213000000
Revises:
Create Date: 2025-02-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20250213000000"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # CORE ENTITIES
    op.create_table(
        "farms",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="Multi-tenant farm support. customer_id links to API.",
    )

    op.create_table(
        "horses",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), server_default=sa.text("'active'"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Horses belonging to a farm. Matched by NAME when syncing.",
    )

    op.create_table(
        "riders",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Riders belonging to a farm. Matched by NAME when syncing.",
    )

    op.create_table(
        "shows",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_show_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("venue", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Shows/competitions. ONLY table with api_show_id (unique per show).",
    )

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("ring_number", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Ring names (International Ring, etc.). Matched by NAME.",
    )

    op.create_table(
        "classes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("class_number", sa.String(50), nullable=True),
        sa.Column("sponsor", sa.String(255), nullable=True),
        sa.Column("prize_money", sa.Numeric(10, 2), nullable=True),
        sa.Column("class_type", sa.String(100), nullable=True),
        sa.Column("jumper_table", sa.String(100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Class names ($15,000 Junior Jumper). Matched by NAME.",
    )

    op.create_table(
        "entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("horse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("show_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("api_entry_id", sa.Integer(), nullable=True),
        sa.Column("api_horse_id", sa.Integer(), nullable=True),
        sa.Column("api_rider_id", sa.Integer(), nullable=True),
        sa.Column("api_class_id", sa.Integer(), nullable=True),
        sa.Column("api_ring_id", sa.Integer(), nullable=True),
        sa.Column("api_trip_id", sa.Integer(), nullable=True),
        sa.Column("api_trainer_id", sa.Integer(), nullable=True),
        sa.Column("back_number", sa.String(50), nullable=True),
        sa.Column("order_of_go", sa.Integer(), nullable=True),
        sa.Column("order_total", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(50), server_default=sa.text("'active'"), nullable=False),
        sa.Column("scratch_trip", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("gone_in", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("estimated_start", sa.String(50), nullable=True),
        sa.Column("actual_start", sa.String(50), nullable=True),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("class_status", sa.String(50), nullable=True),
        sa.Column("total_trips", sa.Integer(), nullable=True),
        sa.Column("completed_trips", sa.Integer(), nullable=True),
        sa.Column("remaining_trips", sa.Integer(), nullable=True),
        sa.Column("ring_status", sa.String(100), nullable=True),
        sa.Column("placing", sa.Integer(), nullable=True),
        sa.Column("points_earned", sa.Numeric(5, 2), nullable=True),
        sa.Column("total_prize_money", sa.Numeric(10, 2), nullable=True),
        sa.Column("faults_one", sa.Numeric(5, 2), nullable=True),
        sa.Column("time_one", sa.Numeric(8, 3), nullable=True),
        sa.Column("time_fault_one", sa.Numeric(5, 2), nullable=True),
        sa.Column("disqualify_status_one", sa.String(50), nullable=True),
        sa.Column("faults_two", sa.Numeric(5, 2), nullable=True),
        sa.Column("time_two", sa.Numeric(8, 3), nullable=True),
        sa.Column("time_fault_two", sa.Numeric(5, 2), nullable=True),
        sa.Column("disqualify_status_two", sa.String(50), nullable=True),
        sa.Column("score1", sa.Numeric(5, 2), nullable=True),
        sa.Column("score2", sa.Numeric(5, 2), nullable=True),
        sa.Column("score3", sa.Numeric(5, 2), nullable=True),
        sa.Column("score4", sa.Numeric(5, 2), nullable=True),
        sa.Column("score5", sa.Numeric(5, 2), nullable=True),
        sa.Column("score6", sa.Numeric(5, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["horse_id"], ["horses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rider_id"], ["riders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["show_id"], ["shows.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        comment="Horse participation in class. ALL api_* IDs stored here (show-specific).",
    )

    op.create_table(
        "locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Physical locations (Farm, Vet, Event Venue).",
    )

    op.create_table(
        "horse_location_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("horse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("show_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["horse_id"], ["horses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["show_id"], ["shows.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entry_id"], ["entries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        comment="Tracks horse movements with context.",
    )

    # INDEXES
    op.create_index("idx_horses_farm_id", "horses", ["farm_id"], unique=False)
    op.create_index("idx_horses_name", "horses", ["name"], unique=False)
    op.create_index("idx_horses_status", "horses", ["status"], unique=False)
    op.create_index("idx_horses_farm_name", "horses", ["farm_id", "name"], unique=True)

    op.create_index("idx_riders_farm_id", "riders", ["farm_id"], unique=False)
    op.create_index("idx_riders_name", "riders", ["name"], unique=False)
    op.create_index("idx_riders_farm_name", "riders", ["farm_id", "name"], unique=True)

    op.create_index("idx_shows_farm_id", "shows", ["farm_id"], unique=False)
    op.create_index("idx_shows_api_show_id", "shows", ["api_show_id"], unique=False)
    op.create_index("idx_shows_start_date", "shows", ["start_date"], unique=False)
    op.create_index(
        "idx_shows_farm_api",
        "shows",
        ["farm_id", "api_show_id"],
        unique=True,
        postgresql_where=sa.text("api_show_id IS NOT NULL"),
    )

    op.create_index("idx_events_farm_id", "events", ["farm_id"], unique=False)
    op.create_index("idx_events_name", "events", ["name"], unique=False)
    op.create_index("idx_events_farm_name", "events", ["farm_id", "name"], unique=True)

    op.create_index("idx_classes_farm_id", "classes", ["farm_id"], unique=False)
    op.create_index("idx_classes_name", "classes", ["name"], unique=False)
    op.create_index("idx_classes_farm_name", "classes", ["farm_id", "name", "class_number"], unique=True)

    op.create_index("idx_entries_horse_id", "entries", ["horse_id"], unique=False)
    op.create_index("idx_entries_rider_id", "entries", ["rider_id"], unique=False)
    op.create_index("idx_entries_show_id", "entries", ["show_id"], unique=False)
    op.create_index("idx_entries_event_id", "entries", ["event_id"], unique=False)
    op.create_index("idx_entries_class_id", "entries", ["class_id"], unique=False)
    op.create_index("idx_entries_status", "entries", ["status"], unique=False)
    op.create_index("idx_entries_class_status", "entries", ["class_status"], unique=False)
    op.create_index("idx_entries_scheduled_date", "entries", ["scheduled_date"], unique=False)
    op.create_index("idx_entries_api_entry_id", "entries", ["api_entry_id"], unique=False)
    op.create_index("idx_entries_api_class_id", "entries", ["api_class_id"], unique=False)
    op.create_index("idx_entries_back_number", "entries", ["back_number"], unique=False)
    op.create_index(
        "idx_entries_unique",
        "entries",
        ["horse_id", "show_id", "api_class_id"],
        unique=True,
        postgresql_where=sa.text("api_class_id IS NOT NULL"),
    )

    op.create_index("idx_locations_farm_id", "locations", ["farm_id"], unique=False)
    op.create_index("idx_locations_type", "locations", ["type"], unique=False)

    op.create_index("idx_horse_location_history_horse_id", "horse_location_history", ["horse_id"], unique=False)
    op.create_index("idx_horse_location_history_timestamp", "horse_location_history", ["timestamp"], unique=False)
    op.create_index(
        "idx_horse_location_history_horse_timestamp",
        "horse_location_history",
        ["horse_id", "timestamp"],
        unique=False,
        postgresql_ops={"timestamp": "DESC"},
    )

    # Table and column comments (documentation)
    op.execute("COMMENT ON COLUMN entries.api_horse_id IS 'API horse_id - changes per show, stored for re-syncing'")
    op.execute("COMMENT ON COLUMN entries.api_rider_id IS 'API rider_id - changes per show, stored for re-syncing'")
    op.execute("COMMENT ON COLUMN entries.api_class_id IS 'API class_id - changes per show, stored for re-syncing'")
    op.execute("COMMENT ON COLUMN entries.api_ring_id IS 'API ring_id - changes per show, stored for re-syncing'")
    op.execute("COMMENT ON COLUMN entries.class_status IS 'Not Started, In Progress, Completed'")
    op.execute("COMMENT ON COLUMN entries.status IS 'active, scratched, completed'")


def downgrade() -> None:
    op.drop_index("idx_horse_location_history_horse_timestamp", table_name="horse_location_history")
    op.drop_index("idx_horse_location_history_timestamp", table_name="horse_location_history")
    op.drop_index("idx_horse_location_history_horse_id", table_name="horse_location_history")
    op.drop_index("idx_locations_type", table_name="locations")
    op.drop_index("idx_locations_farm_id", table_name="locations")
    op.drop_index("idx_entries_unique", table_name="entries")
    op.drop_index("idx_entries_back_number", table_name="entries")
    op.drop_index("idx_entries_api_class_id", table_name="entries")
    op.drop_index("idx_entries_api_entry_id", table_name="entries")
    op.drop_index("idx_entries_scheduled_date", table_name="entries")
    op.drop_index("idx_entries_class_status", table_name="entries")
    op.drop_index("idx_entries_status", table_name="entries")
    op.drop_index("idx_entries_class_id", table_name="entries")
    op.drop_index("idx_entries_event_id", table_name="entries")
    op.drop_index("idx_entries_show_id", table_name="entries")
    op.drop_index("idx_entries_rider_id", table_name="entries")
    op.drop_index("idx_entries_horse_id", table_name="entries")
    op.drop_index("idx_classes_farm_name", table_name="classes")
    op.drop_index("idx_classes_name", table_name="classes")
    op.drop_index("idx_classes_farm_id", table_name="classes")
    op.drop_index("idx_events_farm_name", table_name="events")
    op.drop_index("idx_events_name", table_name="events")
    op.drop_index("idx_events_farm_id", table_name="events")
    op.drop_index("idx_shows_farm_api", table_name="shows")
    op.drop_index("idx_shows_start_date", table_name="shows")
    op.drop_index("idx_shows_api_show_id", table_name="shows")
    op.drop_index("idx_shows_farm_id", table_name="shows")
    op.drop_index("idx_riders_farm_name", table_name="riders")
    op.drop_index("idx_riders_name", table_name="riders")
    op.drop_index("idx_riders_farm_id", table_name="riders")
    op.drop_index("idx_horses_farm_name", table_name="horses")
    op.drop_index("idx_horses_status", table_name="horses")
    op.drop_index("idx_horses_name", table_name="horses")
    op.drop_index("idx_horses_farm_id", table_name="horses")

    op.drop_table("horse_location_history")
    op.drop_table("locations")
    op.drop_table("entries")
    op.drop_table("classes")
    op.drop_table("events")
    op.drop_table("shows")
    op.drop_table("riders")
    op.drop_table("horses")
    op.drop_table("farms")

    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
