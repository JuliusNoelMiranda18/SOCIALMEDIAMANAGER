from alembic import context
from sqlalchemy import create_engine

from app.config import settings
from app.models import Base

with create_engine(settings.database_url).connect() as conn:
    context.configure(connection=conn, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
