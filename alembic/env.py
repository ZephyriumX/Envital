# alembic/env.py
import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool, engine_from_config, create_engine
from sqlalchemy.engine import Connection
from sqlalchemy import text

from alembic import context

# allow loading .env for DATABASE_URL
from dotenv import load_dotenv
load_dotenv()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# override sqlalchemy.url from environment if present (read .env)
env_db_url = os.getenv("DATABASE_URL")
if env_db_url:
    config.set_main_option("sqlalchemy.url", env_db_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# import your model's MetaData object here for 'autogenerate' support
# make sure the import path matches your project layout
# it should import the Base (declarative_base) where models are defined
from backend.database import Base  # adjust if your package name differs

target_metadata = Base.metadata

# ----------------------------------------------------------------------
# Helper to run migrations in "online" mode using async engine if needed
# ----------------------------------------------------------------------
def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True, compare_server_default=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async():
    """Run migrations with an async engine (when using asyncpg)."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

    url = config.get_main_option("sqlalchemy.url")
    async_engine: AsyncEngine = create_async_engine(url, future=True) # type: ignore

    async with async_engine.begin() as conn:
        # run the migrations using the connection's synchronous driver
        await conn.run_sync(do_run_migrations)

    await async_engine.dispose()


def run_migrations_online_sync():
    """Run migrations with a sync engine (normal path)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section), # type: ignore
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)


def run_migrations_online():
    url = config.get_main_option("sqlalchemy.url") or ""
    # If using asyncpg in URL, run the async path
    if url.startswith("postgresql+asyncpg") or "+asyncpg" in url:
        # run asyncio loop for async migration
        asyncio.run(run_migrations_online_async())
    else:
        run_migrations_online_sync()


# ----------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
