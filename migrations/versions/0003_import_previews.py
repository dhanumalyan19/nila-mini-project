"""Private, expiring import previews with one-time commit state."""
from alembic import op
import sqlalchemy as sa

revision = "0003_import_previews"
down_revision = "0002_officer_access"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.ForeignKeyConstraint(["officer_id"], ["officers.id"], name=op.f("fk_import_batches_officer_id_officers")),
        sa.CheckConstraint("kind IN ('measurements', 'locations', 'areas')", name=op.f("ck_import_batches_kind_values")),
        sa.CheckConstraint("status IN ('preview', 'committed')", name=op.f("ck_import_batches_status_values")))
    op.create_index("ix_import_batches_officer_id", "import_batches", ["officer_id"])


def downgrade():
    op.drop_table("import_batches")
