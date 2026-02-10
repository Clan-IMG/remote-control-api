from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from src.app.config import DATABASE_URL

# Create async engine with connection pool options to avoid using stale/closed MySQL connections
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,    # ping connections before use
    pool_recycle=3600,    # recycle connections older than 1h
    pool_timeout=30       # wait up to 30s for a connection from the pool
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
