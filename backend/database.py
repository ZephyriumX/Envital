# backend/database.py
import os
from typing import Generator, AsyncGenerator, Optional

from dotenv import load_dotenv

# SQLAlchemy imports
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError

# Async SQLAlchemy
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker as async_sessionmaker

# Load environment variables from project .env
load_dotenv()

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
# You can either set DATABASE_URL explicitly in .env or assemble from parts.
# Example .env:
# DB_USER=geouser
# DB_PASS=geopass
# DB_HOST=localhost
# DB_PORT=5432
# DB_NAME=geoa
# DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv(
    "SQLALCHEMY_DATABASE_URL",
    None,
)

# If DATABASE_URL is not provided, fallback to sqlite local DB for quick dev.
if not DATABASE_URL:
    SQLITE_PATH = os.getenv("SQLITE_PATH", "./envital.db")
    DATABASE_URL = f"sqlite:///{SQLITE_PATH}"

# -----------------------------------------------------------------------------
# Engine creation: create sync and async engines depending on scheme
# -----------------------------------------------------------------------------
# Detect whether async driver is used (asyncpg)
IS_ASYNC = "asyncpg" in DATABASE_URL or DATABASE_URL.startswith("postgresql+asyncpg")

# --- Sync engine / Session (for legacy sync code or simple scripts) ---
# Provide connect_args for sqlite (avoid thread issues)
sync_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
SyncEngine = create_engine(
    DATABASE_URL.replace("+asyncpg", "") if IS_ASYNC else DATABASE_URL,
    pool_pre_ping=True,
    connect_args=sync_connect_args,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=SyncEngine)

# --- Async engine / Session (for FastAPI async endpoints) ---
AsyncEngine = None
AsyncSessionLocal = None
if IS_ASYNC:
    # create_async_engine expects an async URL like postgresql+asyncpg://...
    AsyncEngine = create_async_engine(DATABASE_URL, future=True, echo=False, pool_pre_ping=True)
    AsyncSessionLocal = async_sessionmaker(bind=AsyncEngine, class_=AsyncSession, expire_on_commit=False) # type: ignore

# Declarative base (single Base used by models)
Base = declarative_base()

# -----------------------------------------------------------------------------
# FastAPI dependencies
# -----------------------------------------------------------------------------
def get_db() -> Generator:
    """
    Sync DB session dependency for FastAPI endpoints that use sync SQLAlchemy Session.
    Usage:
        def endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except SQLAlchemyError:
            pass


async def get_async_session() -> AsyncGenerator:
    """
    Async DB session dependency for FastAPI endpoints that use AsyncSession.
    Usage:
        async def endpoint(db: AsyncSession = Depends(get_async_session)):
            ...
    """
    if AsyncSessionLocal is None:
        raise RuntimeError("Async engine/session not configured. Ensure DATABASE_URL uses asyncpg.")
    async with AsyncSessionLocal() as session: # type: ignore # type: ignore
        yield session


# -----------------------------------------------------------------------------
# Helpers to create tables (sync + async)
# -----------------------------------------------------------------------------
def create_tables() -> None:
    """
    Create all tables (synchronous). Use for quick local dev when using sync engine.
    """
    Base.metadata.create_all(bind=SyncEngine)


async def create_tables_async() -> None:
    """
    Create all tables using the async engine. Useful in async test setup or startup scripts.
    """
    if AsyncEngine is None:
        raise RuntimeError("Async engine not configured. Set DATABASE_URL to use asyncpg.")
    # Use run_sync to execute sync metadata.create_all in the async engine's connection
    async with AsyncEngine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# -----------------------------------------------------------------------------
# Quick CLI test (execute with: python -m backend.database)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio
    print("DATABASE_URL =", DATABASE_URL)
    print("IS_ASYNC =", IS_ASYNC)

    # Quick smoke test: try to create tables
    if IS_ASYNC:
        print("Creating tables (async)...")
        asyncio.run(create_tables_async())
    else:
        print("Creating tables (sync)...")
        create_tables()
    print("Done.")
