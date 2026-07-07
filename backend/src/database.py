from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from src.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session


async def init_db():
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight migrations: add columns that may not exist yet
        migrations = [
            "ALTER TABLE channel_tasks ADD COLUMN session_mode TEXT NOT NULL DEFAULT 'always'",
            "ALTER TABLE channel_tasks ADD COLUMN offline_until DATETIME",
            # Account warmup & monitoring columns
            "ALTER TABLE accounts ADD COLUMN last_name TEXT",
            "ALTER TABLE accounts ADD COLUMN warmup_status TEXT NOT NULL DEFAULT 'none'",
            "ALTER TABLE accounts ADD COLUMN warmup_started_at DATETIME",
            "ALTER TABLE accounts ADD COLUMN total_actions INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE accounts ADD COLUMN restrictions_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE accounts ADD COLUMN bans_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE boost_tasks ADD COLUMN channel_peer TEXT",
        ]
        for stmt in migrations:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # Column already exists
