from alembic import context
from sqlalchemy import create_engine

from app.config import settings

# No models yet (Stage 2), so no target_metadata.
with create_engine(settings.database_url).connect() as conn:
    context.configure(connection=conn, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
