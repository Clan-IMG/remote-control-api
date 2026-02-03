from fastapi import APIRouter
from src.app.redis_client import get_redis
from src.app.database import engine
from src.app.schemas import HealthResponse
from sqlalchemy import text
import logging

router = APIRouter(tags=["Health"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    redis_ok = False
    db_ok = False
    active_containers = 0
    
    # Check Redis
    try:
        redis = await get_redis()
        await redis.ping()
        redis_ok = True
        
        # Get active container count from Redis
        container_status = await redis.hgetall("pixelkid:containers:status")
        active_containers = len([k for k, v in container_status.items() if v == "running"])
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
    
    # Check Database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            db_ok = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
    
    status = "healthy" if (redis_ok and db_ok) else "degraded"
    
    return HealthResponse(
        status=status,
        version="1.0.0",
        redis_connected=redis_ok,
        database_connected=db_ok,
        active_containers=active_containers
    )


@router.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "PixelKid API",
        "version": "1.0.0",
        "docs": "/docs"
    }
