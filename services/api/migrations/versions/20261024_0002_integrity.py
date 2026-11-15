"""Append-only evidence and completed-episode database guards.

Revision ID: 20261024_0002
Revises: 20261024_0001
"""
from alembic import op
import sqlalchemy as sa

revision = '20261024_0002'
down_revision = '20261024_0001'
branch_labels = None
depends_on = None

APPEND_ONLY = ['audit_events','queue_state_events','episode_corrections','triage_assessments','clinician_decisions','priority_recommendations']


def upgrade():
    op.create_index('ix_audit_facility_occurred','audit_events',['facility_id','occurred_at'])
    op.create_index('ix_outbox_facility_created','event_outbox',['facility_id','created_at'])
    op.create_index('ix_jobs_pending_created','jobs',['status','created_at'])
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("""CREATE FUNCTION hutano_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Research evidence is append-only'; END; $$""")
        for table in APPEND_ONLY:
            op.execute(f'CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hutano_append_only()')
        op.execute("""CREATE FUNCTION hutano_completed_episode() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF OLD.status = 'COMPLETED' THEN
                RAISE EXCEPTION 'Completed episode is immutable; use episode_corrections';
              END IF;
              IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
              RETURN NEW;
            END; $$""")
        op.execute('CREATE TRIGGER completed_episode_immutable BEFORE UPDATE OR DELETE ON service_episodes FOR EACH ROW EXECUTE FUNCTION hutano_completed_episode()')


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP TRIGGER completed_episode_immutable ON service_episodes')
        op.execute('DROP FUNCTION hutano_completed_episode()')
        for table in APPEND_ONLY:
            op.execute(f'DROP TRIGGER {table}_immutable ON {table}')
        op.execute('DROP FUNCTION hutano_append_only()')
    op.drop_index('ix_jobs_pending_created',table_name='jobs')
    op.drop_index('ix_outbox_facility_created',table_name='event_outbox')
    op.drop_index('ix_audit_facility_occurred',table_name='audit_events')
