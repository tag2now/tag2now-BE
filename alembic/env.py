from logging.config import fileConfig
import os
from alembic import context
from sqlalchemy import engine_from_config, pool

from shared.database import Base, build_dsn
import community.entities  # noqa
import history.entities  # noqa
import reservation.entities  # noqa

config = context.config
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL") or build_dsn(driver="psycopg"))
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction(): context.run_migrations()

def run_migrations_online():
    section = config.get_section(config.config_ini_section)
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction(): context.run_migrations()

if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
