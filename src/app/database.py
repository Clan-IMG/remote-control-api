from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from src.app.config import DATABASE_URL

# Create async engine with connection pool tuned for multiple uvicorn workers.
# Each uvicorn worker process forks and creates its OWN pool, so keep
# pool_size moderate per process.  With 8 workers × pool_size=5 = 40 conns.
# MySQL default max_connections=151, so this fits comfortably.
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,       # test connections before checkout (heals stale conns)
    pool_recycle=300,          # recycle connections every 5 min (shorter than MySQL wait_timeout)
    pool_timeout=10,           # don't block long waiting for a pool slot
    pool_size=5,               # connections kept open per worker process
    max_overflow=5,            # extra connections allowed when pool is full
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
