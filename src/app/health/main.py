"""
Health Check Endpoints
"""
from datetime import datetime
from fastapi import APIRouter
from ..store import store
from ..models import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health():
    """Health-Check mit Status-Infos"""
    plugins = await store.get_all_plugins()
    return HealthResponse(
        status="ok",
        version="1.0.0",
        plugins_registered=len(plugins),
        active_sessions=0  # Sessions werden jetzt in DB gezählt
    )


@router.get("/")
def root():
    """Root Endpoint"""
    return {"message": "Permission API", "version": "1.0.0"}
