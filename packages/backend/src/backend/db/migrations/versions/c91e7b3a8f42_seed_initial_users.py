"""Create the administrator and active department users on an empty user database."""

import os

import sqlalchemy as sa
from alembic import op
from backend.core.config import BACKEND_ROOT
from backend.core.password import hash_password
from backend.core.utils import utc_now
from dotenv import dotenv_values

revision = 'c91e7b3a8f42'
down_revision = '1b564ed4a71a'
branch_labels = None
depends_on = None

DEPARTMENT_EMP_IDS = {
  'research_and_development': 'RD001',
  'quality_assurance': 'QA001',
  'production_management': 'PM001',
}
PASSWORD_ENV_VARS = {
  'SYS001': 'INITIAL_ADMIN_PASSWORD',
  'RD001': 'INITIAL_RD_PASSWORD',
  'QA001': 'INITIAL_QA_PASSWORD',
  'PM001': 'INITIAL_PM_PASSWORD',
}


def upgrade() -> None:
  if op.get_context().as_sql:
    raise RuntimeError('Initial users require an online migration.')

  connection = op.get_bind()
  metadata = sa.MetaData()
  users = sa.Table('users', metadata, autoload_with=connection)
  if connection.scalar(sa.select(users.c.id).limit(1)) is not None:
    return

  departments = sa.Table('departments', metadata, autoload_with=connection)
  active = connection.execute(
    sa.select(departments)
    .where(departments.c.is_active.is_(True), departments.c.code.in_(DEPARTMENT_EMP_IDS))
    .order_by(departments.c.id)
  ).mappings()
  accounts = [
    {'emp_id': 'SYS001', 'name': '시스템 관리자', 'department_id': None, 'role': 'system_admin'},
    *[
      {
        'emp_id': DEPARTMENT_EMP_IDS[department['code']],
        'name': department['name'],
        'department_id': department['id'],
        'role': 'user',
      }
      for department in active
    ],
  ]
  passwords = {**dotenv_values(BACKEND_ROOT / '.env'), **os.environ}
  now = utc_now()
  for account in accounts:
    variable = PASSWORD_ENV_VARS[account['emp_id']]
    password = passwords.get(variable)
    if password is None or not 12 <= len(password) <= 30:
      raise ValueError(f'Set {variable} to 12–30 characters before initializing an empty user database.')
    account.update(password_hash=hash_password(password), is_active=True, created_at=now, updated_at=now)
  connection.execute(users.insert(), accounts)


def downgrade() -> None:
  # These accounts are operational data and must survive a schema rollback.
  pass
