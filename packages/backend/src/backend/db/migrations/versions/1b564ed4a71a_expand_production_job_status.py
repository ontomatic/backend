"""Allow the completed_with_defects production job status."""

import sqlalchemy as sa
from alembic import op

revision = '1b564ed4a71a'
down_revision = 'a13f72c9e001'
branch_labels = None
depends_on = None


def upgrade() -> None:
  op.alter_column(
    'production_jobs', 'status', existing_type=sa.String(20), type_=sa.String(32), existing_nullable=False
  )


def downgrade() -> None:
  op.alter_column(
    'production_jobs', 'status', existing_type=sa.String(32), type_=sa.String(20), existing_nullable=False
  )
