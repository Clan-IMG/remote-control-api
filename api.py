import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from src.app.health.main import router as health_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting API...")
    yield
    
    logger.info("Shutting down...")
    await redis_client.close()

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
    token = request.headers.get("Authorization", "")
    if not token.startswith("Bearer ") or token.replace("Bearer ", "") != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    return await call_next(request)

# /health
app.include_router(health_router, tags=["health"])

@app.get("/")
def root():
    return {"msg": "Hellow World!"}
