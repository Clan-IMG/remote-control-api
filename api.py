import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi import HTTPException
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from app.health.main import router as health_router
from app.auth import verify_bearer_token
from app.database import engine, Base
import app.pay.models  # register ORM models
from app.pay.router import router as pay_router
from app.ping.router import router as ping_router
from sqlalchemy import text

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Docker depends_on does not wait for DB readiness. Retry startup DB connect
    # to avoid crash loops when MariaDB is still booting.
    last_error: Exception | None = None
    for attempt in range(1, 31):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(text(
                    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS claimed_at DATETIME NULL"
                ))
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            logger.warning("Database not ready on startup (attempt %s/30): %r", attempt, exc)
            if attempt < 30:
                await asyncio.sleep(2)
    if last_error is not None:
        raise last_error

    logger.info("Starting API...")
    yield

    await engine.dispose()
    logger.info("Shutting down...")

app = FastAPI(
    title="API",
    description="API-Template",
    version="1.0.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def token_checker(request: Request, call_next):
    # Pfade ohne Token-Check
    public_paths = ["/health"]
    if any(request.url.path.startswith(p) for p in public_paths):
        return await call_next(request)
    try:
        verify_bearer_token(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)

# /health
app.include_router(health_router, tags=["health"])

# /v1/pay
app.include_router(pay_router, tags=["pay"])

# /v1/ping
app.include_router(ping_router, tags=["ping"])

@app.get("/")
def root():
    return {"msg": "Hellow World!"}
