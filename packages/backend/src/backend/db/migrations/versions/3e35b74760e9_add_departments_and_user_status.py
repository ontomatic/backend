"""Add departments and user status.

Revision ID: 3e35b74760e9
Revises: 49484fc32658
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '3e35b74760e9'
down_revision: str | Sequence[str] | None = '49484fc32658'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Keep this snapshot independent of application models and future catalog changes.
DEPARTMENTS = (
  ('research_and_development', 'R&D / 연구개발', True),
  ('quality_assurance', '품질관리 / QA·인증', True),
  ('production_management', '생산관리', True),
  ('product_planning', '상품기획·상품운영', False),
  ('procurement', '구매·자재', False),
  ('sales', '영업·기술영업', False),
  ('customer_support', '기술지원·CS', False),
)


def upgrade() -> None:
  op.create_table(
    'departments',
    sa.Column('id', sa.Integer(), sa.Identity(), nullable=False),
    sa.Column('code', sa.String(50), nullable=False),
    sa.Column('name', sa.String(100), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    sa.UniqueConstraint('name'),
  )
  op.add_column('users', sa.Column('department_id', sa.Integer(), nullable=True))
  op.add_column('users', sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False))
  op.create_index('ix_users_department_id', 'users', ['department_id'])
  op.create_foreign_key('fk_users_department_id', 'users', 'departments', ['department_id'], ['id'])
  op.drop_column('users', 'department')

  departments = sa.table('departments', sa.column('code'), sa.column('name'), sa.column('is_active', sa.Boolean()))
  op.bulk_insert(
    departments,
    [{'code': code, 'name': name, 'is_active': is_active} for code, name, is_active in DEPARTMENTS],
  )


def downgrade() -> None:
  op.add_column('users', sa.Column('department', sa.String(100), nullable=True))
  users = sa.table('users', sa.column('department'), sa.column('department_id', sa.Integer()))
  departments = sa.table('departments', sa.column('id', sa.Integer()), sa.column('name'))
  department_name = sa.select(departments.c.name).where(departments.c.id == users.c.department_id).scalar_subquery()
  op.execute(users.update().values(department=department_name))

  op.drop_constraint('fk_users_department_id', 'users', type_='foreignkey')
  op.drop_index('ix_users_department_id', table_name='users')
  op.drop_column('users', 'is_active')
  op.drop_column('users', 'department_id')
  op.drop_table('departments')
