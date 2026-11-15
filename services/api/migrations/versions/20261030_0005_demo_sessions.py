"""Immutable provenance for the isolated fictional clinic rehearsal."""
from alembic import op
import sqlalchemy as sa

revision = "20261030_0005"
down_revision = "20261026_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("demo_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("facility_id", sa.Uuid(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("version", sa.String(60), nullable=False),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_demo_sessions_facility_id", "demo_sessions", ["facility_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE TRIGGER demo_sessions_immutable BEFORE UPDATE OR DELETE ON demo_sessions FOR EACH ROW EXECUTE FUNCTION hutano_append_only()")


def downgrade():
    op.drop_table("demo_sessions")
