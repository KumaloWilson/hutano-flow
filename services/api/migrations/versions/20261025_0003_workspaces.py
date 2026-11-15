"""Frozen patient-workspace, resource and experiment extension."""
from alembic import op
import sqlalchemy as sa

revision = '20261025_0003'
down_revision = '20261024_0002'
branch_labels = None
depends_on = None


def ident(name, target, nullable=False):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target), nullable=nullable)


def moment(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def table(name, *fields, updated=False):
    op.create_table(name, sa.Column('id', sa.Uuid(), primary_key=True), ident('facility_id', 'facilities.id'),
        *fields, moment('created_at'), *([moment('updated_at')] if updated else []))
    op.create_index('ix_'+name+'_facility_id', name, ['facility_id'])


def upgrade():
    table('encounter_notes', ident('episode_id','service_episodes.id'), ident('actor_id','users.id'), sa.Column('text',sa.String(1000),nullable=False))
    table('handovers', ident('visit_id','visits.id'), ident('source_episode_id','service_episodes.id'), ident('target_point_id','service_points.id'),
        ident('actor_id','users.id'), sa.Column('message',sa.String(1000),nullable=False), ident('acknowledged_by','users.id',True),
        moment('acknowledged_at',True), sa.Column('version',sa.Integer(),nullable=False), updated=True)
    table('rooms',ident('service_point_id','service_points.id'),sa.Column('name',sa.String(80),nullable=False),
        sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('version',sa.Integer(),nullable=False),sa.UniqueConstraint('facility_id','name'),updated=True)
    table('staff_shifts',ident('staff_id','users.id'),ident('room_id','rooms.id'),moment('starts_at'),moment('ends_at'),
        sa.Column('cancelled',sa.Boolean(),nullable=False),sa.Column('version',sa.Integer(),nullable=False),sa.CheckConstraint('ends_at > starts_at'),updated=True)
    table('resource_blocks',ident('room_id','rooms.id',True),ident('staff_id','users.id',True),moment('starts_at'),moment('ends_at'),
        sa.Column('reason',sa.String(240),nullable=False),sa.Column('cancelled',sa.Boolean(),nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.CheckConstraint('ends_at > starts_at'),sa.CheckConstraint('(room_id IS NULL) <> (staff_id IS NULL)'),updated=True)
    # Reservations have their own immutable approval clock; no TimestampMixin.
    op.create_table('resource_assignments',sa.Column('id',sa.Uuid(),primary_key=True),ident('facility_id','facilities.id'),
        ident('episode_id','service_episodes.id'),ident('room_id','rooms.id'),ident('staff_id','users.id'),ident('approved_by','users.id'),
        moment('approved_at'),moment('started_at',True),moment('released_at',True),sa.Column('prediction_json',sa.JSON(),nullable=False))
    op.create_index('ix_resource_assignments_facility_id','resource_assignments',['facility_id'])
    for column in ['episode_id','room_id','staff_id']:
        op.create_index('uq_assignment_active_'+column,'resource_assignments',[column],unique=True,
            postgresql_where=sa.text('released_at IS NULL'),sqlite_where=sa.text('released_at IS NULL'))
    table('routing_proposals',ident('episode_id','service_episodes.id'),ident('actor_id','users.id'),sa.Column('queue_version',sa.Integer(),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),sa.Column('options_json',sa.JSON(),nullable=False),sa.Column('status',sa.String(20),nullable=False),
        ident('chosen_room_id','rooms.id',True),sa.Column('reason',sa.String(240)),updated=True)
    table('operational_models',sa.Column('version',sa.String(80),nullable=False),sa.Column('dataset_hash',sa.String(64),nullable=False),
        sa.Column('artifact_path',sa.String(500),nullable=False),sa.Column('metrics_json',sa.JSON(),nullable=False),sa.UniqueConstraint('facility_id','version'))
    table('experiment_scenario_versions',sa.Column('series_id',sa.Uuid(),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('name',sa.String(120),nullable=False),sa.Column('config_json',sa.JSON(),nullable=False),sa.Column('config_hash',sa.String(64),nullable=False),
        sa.Column('rationale',sa.String(500),nullable=False),ident('actor_id','users.id'),sa.UniqueConstraint('facility_id','series_id','revision'))
    table('experiment_runs',ident('scenario_version_id','experiment_scenario_versions.id'),sa.Column('status',sa.String(20),nullable=False),
        sa.Column('results_json',sa.JSON(),nullable=False),updated=True)
    for name, columns in {
        'encounter_notes':['episode_id'],'handovers':['visit_id'],'rooms':['service_point_id'],'staff_shifts':['staff_id','room_id'],
        'resource_blocks':['room_id','staff_id'],'resource_assignments':['episode_id','room_id','staff_id'],
        'routing_proposals':['episode_id'],'experiment_scenario_versions':['series_id'],'experiment_runs':['scenario_version_id']}.items():
        for column in columns: op.create_index(f'ix_{name}_{column}',name,[column])
    if op.get_bind().dialect.name == 'postgresql':
        for name in ['encounter_notes','observations','experiment_scenario_versions']:
            op.execute(f'CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION hutano_append_only()')


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP TRIGGER observations_immutable ON observations')
    for name in ['experiment_runs','experiment_scenario_versions','operational_models','routing_proposals','resource_assignments',
                 'resource_blocks','staff_shifts','rooms','handovers','encounter_notes']:
        op.drop_table(name)
