"""Fix users.role column type: convert from PostgreSQL enum to VARCHAR

Revision ID: 003
Revises: 002
Create Date: 2026-03-26 00:00:00.000000

Problem
-------
On the first Render deployment the User model declared:

    role = mapped_column(sa.Enum('user', 'admin', name='user_role'), ...)

SQLAlchemy created a custom PostgreSQL enum type 'user_role' and a column
'role' of that type.  When the model was later changed to String(10)/VARCHAR
the database column was NOT updated (init_db uses create_all which never
alters existing columns).

At startup, main.py runs:
    select(User).where(User.role == role)

SQLAlchemy binds the Python str as character varying.  PostgreSQL rejects:
    ERROR: operator does not exist: user_role = character varying

Fix
---
1. ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(10) — safe, no data loss.
   The USING clause casts the existing enum values to text.
2. DROP TYPE IF EXISTS user_role — removes the now-unused enum type.
   IF EXISTS makes this idempotent: if the column was already VARCHAR the
   enum type may not exist, and the migration still succeeds.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert role column from enum type 'user_role' to plain VARCHAR(10).
    # USING role::text casts existing enum values to text — no data loss.
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(10) USING role::text"
    )
    # Drop the obsolete enum type. IF EXISTS keeps the migration idempotent
    # for databases where the column was already VARCHAR.
    op.execute("DROP TYPE IF EXISTS user_role")


def downgrade() -> None:
    # Recreate the enum type and restore the column type.
    op.execute("CREATE TYPE user_role AS ENUM ('user', 'admin')")
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE user_role "
        "USING role::user_role"
    )
