import logging
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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

@app.get("/")
def root():
    return {"msg": "Hellow World!"}
