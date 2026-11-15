"""Operational hardening: account lockout, missed-call handling, day close,
retrospective downtime entry and waiting-room display credentials (ADR-027..031)."""
from alembic import op
import sqlalchemy as sa

revision = "20261115_0006"
down_revision = "20261030_0005"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("queue_entries") as batch:
        batch.add_column(sa.Column("recall_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("last_recalled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("missed_calls", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("deferred_until", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("visits") as batch:
        batch.add_column(sa.Column("entry_mode", sa.String(20), nullable=False, server_default="LIVE"))
        batch.add_column(sa.Column("paper_reference", sa.String(80), nullable=True))
    op.create_table(
        "day_closures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("facility_id", sa.Uuid(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("closed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("facility_id", "local_date", name="uq_day_closure_date"),
    )
    op.create_index("ix_day_closures_facility_id", "day_closures", ["facility_id"])
    op.create_table(
        "display_screens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("facility_id", sa.Uuid(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("secret_hash", sa.LargeBinary(32), nullable=False, unique=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_display_screens_facility_id", "display_screens", ["facility_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE TRIGGER day_closures_immutable BEFORE UPDATE OR DELETE ON day_closures "
                   "FOR EACH ROW EXECUTE FUNCTION hutano_append_only()")


def downgrade():
    op.drop_table("display_screens")
    op.drop_table("day_closures")
    with op.batch_alter_table("visits") as batch:
        batch.drop_column("paper_reference")
        batch.drop_column("entry_mode")
    with op.batch_alter_table("queue_entries") as batch:
        for column in ("deferred_until", "missed_calls", "last_recalled_at", "recall_count"):
            batch.drop_column(column)
    with op.batch_alter_table("users") as batch:
        for column in ("password_changed_at", "must_change_password", "locked_until", "failed_login_count"):
            batch.drop_column(column)
