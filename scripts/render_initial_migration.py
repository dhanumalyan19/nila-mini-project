"""Developer helper: print a proposed initial migration; never write or apply it.

Used only to bootstrap revision 0001. Later changes use flask db migrate.
Review the output before committing a migration file.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic.autogenerate import render_python_code
from alembic.operations import ops
from app import create_app
from app.extensions import db

app = create_app(environ={"NILA_SECRET_KEY": "migration-renderer-only-" + "x" * 40})
operations = []
for table in db.metadata.sorted_tables:
    operations.append(ops.CreateTableOp.from_table(table))
    for index in sorted(table.indexes, key=lambda item: item.name):
        operations.append(ops.CreateIndexOp.from_index(index))

print('"""Initial Nila schema. MySQL 8.0.16+; reviewed snapshot, independent of live models."""')
print("from alembic import op\nimport sqlalchemy as sa\n")
print("revision = '0001_nila_schema'\ndown_revision = None\nbranch_labels = None\ndepends_on = None\n")
print("def upgrade():")
print(render_python_code(ops.UpgradeOps(operations)))
print("""
    kinds = sa.table('measurement_kinds', sa.column('track', sa.String),
                     sa.column('measurement_type', sa.String), sa.column('unit', sa.String),
                     sa.column('description', sa.String))
    op.bulk_insert(kinds, [
        {'track': 'indoor_radon', 'measurement_type': 'indoor_radon_concentration',
         'unit': 'Bq/m3', 'description': 'Indoor radon activity concentration; duration and protocol remain explicit.'},
        {'track': 'regional_radiation', 'measurement_type': 'ambient_gamma_dose_rate',
         'unit': 'uSv/h', 'description': 'Ambient gamma dose-rate observation; never an indoor radon estimate.'},
    ])
""")
print("def downgrade():")
for table in reversed(db.metadata.sorted_tables):
    print(f"    op.drop_table({table.name!r})")

