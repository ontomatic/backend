"""Persist versioned specifications, production jobs, document evidence and immutable workflow history."""

from alembic import op
import sqlalchemy as sa

revision = 'a13f72c9e001'
down_revision = '3e35b74760e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
  op.create_table(
    'specifications',
    sa.Column('id', sa.String(36), primary_key=True),
    sa.Column('code', sa.String(80), nullable=False, index=True),
    sa.Column('name', sa.String(150), nullable=False),
    sa.Column('product_type', sa.String(30), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(20), nullable=False),
    sa.Column('previous_id', sa.String(36), sa.ForeignKey('specifications.id')),
    sa.Column('graph', sa.JSON(), nullable=False),
    sa.Column('reason', sa.String(2000), nullable=False),
    sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True)),
    sa.Column('index_status', sa.String(20), nullable=False),
    sa.Column('index_error', sa.String(500)),
    sa.UniqueConstraint('code', 'version', name='uq_specification_version'),
  )
  op.create_table(
    'production_jobs',
    sa.Column('id', sa.String(36), primary_key=True),
    sa.Column('name', sa.String(150), nullable=False),
    sa.Column('specification_id', sa.String(36), sa.ForeignKey('specifications.id'), nullable=False, index=True),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('plan_version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(20), nullable=False),
    sa.Column('targets', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
  )
  op.create_table(
    'work_documents',
    sa.Column('id', sa.String(36), primary_key=True),
    sa.Column('file_id', sa.Integer(), sa.ForeignKey('files.id'), nullable=False, index=True),
    sa.Column('kind', sa.String(40), nullable=False),
    sa.Column('department', sa.String(50), nullable=False),
    sa.Column('specification_id', sa.String(36), sa.ForeignKey('specifications.id'), index=True),
    sa.Column('job_id', sa.String(36), sa.ForeignKey('production_jobs.id'), index=True),
    sa.Column('scope', sa.JSON(), nullable=False),
    sa.Column('blocks', sa.JSON(), nullable=False),
    sa.Column('candidates', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(20), nullable=False),
    sa.Column('error', sa.String(500)),
    sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
  )
  op.create_table(
    'production_plans',
    sa.Column('id', sa.String(36), primary_key=True),
    sa.Column('job_id', sa.String(36), sa.ForeignKey('production_jobs.id'), nullable=False, index=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint('job_id', 'version', name='uq_job_plan_version'),
  )
  op.create_table(
    'workflow_events',
    sa.Column('id', sa.String(36), primary_key=True),
    sa.Column('specification_id', sa.String(36), sa.ForeignKey('specifications.id'), index=True),
    sa.Column('job_id', sa.String(36), sa.ForeignKey('production_jobs.id'), index=True),
    sa.Column('target_id', sa.String(200)),
    sa.Column('action', sa.String(50), nullable=False),
    sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
    sa.Column('actor_name', sa.String(100), nullable=False),
    sa.Column('department', sa.String(50), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
  )


def downgrade() -> None:
  for table in ('workflow_events', 'production_plans', 'work_documents', 'production_jobs', 'specifications'):
    op.drop_table(table)
