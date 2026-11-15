"""Frozen protocols, blinded labels, synthetic trials and supporting study runs."""
from alembic import op
import sqlalchemy as sa

revision = "20261026_0004"
down_revision = "20261025_0003"
branch_labels = None
depends_on = None


def ident(name, target, nullable=False):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target), nullable=nullable)


def moment(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def table(name, *columns, created=True):
    op.create_table(name, sa.Column("id", sa.Uuid(), primary_key=True),
                    ident("facility_id", "facilities.id"), *columns,
                    *([moment("created_at")] if created else []))
    op.create_index(f"ix_{name}_facility_id", name, ["facility_id"])


def label_check(column="label", nullable=False):
    return sa.CheckConstraint((f"{column} IS NULL OR " if nullable else "") + f"{column} IN ('P1','P2','P3','P4','P5')")


def upgrade():
    table("research_protocols", ident("dataset_id", "datasets.id"), ident("model_id", "model_versions.id", True),
          ident("actor_id", "users.id"), sa.Column("name", sa.String(120), nullable=False),
          sa.Column("question", sa.String(1000), nullable=False), sa.Column("design", sa.String(30), nullable=False),
          sa.Column("config_json", sa.JSON(), nullable=False), sa.Column("config_hash", sa.String(64), nullable=False),
          sa.CheckConstraint("design IN ('MANUAL_ONLY','COUNTERBALANCED','SHADOW')"))
    table("research_cases", ident("protocol_id", "research_protocols.id"), sa.Column("ordinal", sa.Integer(), nullable=False),
          sa.Column("features_json", sa.JSON(), nullable=False), sa.Column("synthetic_label", sa.String(2), nullable=False),
          sa.Column("source_row_hash", sa.String(64), nullable=False), sa.UniqueConstraint("protocol_id", "ordinal"), label_check("synthetic_label"))
    table("research_case_reviews", ident("case_id", "research_cases.id"), ident("reviewer_id", "users.id"),
          sa.Column("label", sa.String(2), nullable=False), sa.Column("reason", sa.String(500), nullable=False),
          sa.UniqueConstraint("case_id", "reviewer_id"), label_check())
    table("research_case_adjudications", ident("case_id", "research_cases.id"), ident("actor_id", "users.id"),
          sa.Column("label", sa.String(2), nullable=False), sa.Column("reason", sa.String(500), nullable=False),
          sa.UniqueConstraint("case_id"), label_check())
    table("research_trials", ident("protocol_id", "research_protocols.id"), ident("case_id", "research_cases.id"),
          ident("participant_id", "users.id"), sa.Column("arm", sa.String(20), nullable=False),
          sa.Column("status", sa.String(20), nullable=False), sa.Column("consent_ref", sa.String(160), nullable=False),
          sa.Column("inference_json", sa.JSON(), nullable=False), sa.Column("final_label", sa.String(2)),
          sa.Column("response_json", sa.JSON(), nullable=False), moment("started_at"), moment("completed_at", True),
          sa.UniqueConstraint("protocol_id", "case_id", "participant_id"),
          sa.CheckConstraint("arm IN ('MANUAL','ADVISORY','EXPLANATION','SHADOW')"),
          sa.CheckConstraint("status IN ('STARTED','COMPLETED')"), label_check("final_label", True),
          sa.CheckConstraint("(status = 'STARTED' AND completed_at IS NULL AND final_label IS NULL) OR (status = 'COMPLETED' AND completed_at IS NOT NULL AND final_label IS NOT NULL)"), created=False)
    op.create_index("uq_research_trial_active", "research_trials", ["protocol_id", "participant_id"], unique=True,
                    postgresql_where=sa.text("status = 'STARTED'"), sqlite_where=sa.text("status = 'STARTED'"))
    table("research_study_runs", ident("protocol_id", "research_protocols.id"), sa.Column("status", sa.String(20), nullable=False),
          sa.Column("results_json", sa.JSON(), nullable=False), sa.Column("error_summary", sa.String(240)), moment("updated_at"),
          sa.CheckConstraint("status IN ('PENDING','RUNNING','COMPLETED','FAILED')"))
    for name, columns in {"research_cases": ["protocol_id"], "research_case_reviews": ["case_id"],
                          "research_trials": ["protocol_id", "participant_id"], "research_study_runs": ["protocol_id"]}.items():
        for column in columns:
            op.create_index(f"ix_{name}_{column}", name, [column])
    if op.get_bind().dialect.name == "postgresql":
        for name in ["research_protocols", "research_cases", "research_case_reviews", "research_case_adjudications"]:
            op.execute(f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION hutano_append_only()")
        op.execute("""CREATE FUNCTION hutano_research_completed_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN
            IF OLD.status = 'COMPLETED' THEN RAISE EXCEPTION 'Completed research evidence is immutable'; END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
          END $$""")
        for name in ["research_trials", "research_study_runs"]:
            op.execute(f"CREATE TRIGGER {name}_completed_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION hutano_research_completed_immutable()")


def downgrade():
    for name in ["research_study_runs", "research_trials", "research_case_adjudications", "research_case_reviews", "research_cases", "research_protocols"]:
        op.drop_table(name)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION hutano_research_completed_immutable()")
