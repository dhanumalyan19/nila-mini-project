"""Officer sessions, database-backed login throttling and building edit versions."""

from alembic import op
import sqlalchemy as sa

revision = "0002_officer_access"
down_revision = "0001_nila_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("buildings", sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"))
    op.alter_column("buildings", "version_id", existing_type=sa.Integer(), server_default=None)
    op.create_table("officer_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["officer_id"], ["officers.id"], name=op.f("fk_officer_sessions_officer_id_officers")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_officer_sessions_token_hash")))
    op.create_index("ix_officer_sessions_officer_id", "officer_sessions", ["officer_id"])
    op.create_table("login_throttles",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False))


def downgrade():
    op.drop_table("login_throttles")
    op.drop_table("officer_sessions")
    op.drop_column("buildings", "version_id")

