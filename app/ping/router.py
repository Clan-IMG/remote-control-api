import os
import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

router = APIRouter(prefix="/v1")


@router.get("/ping")
async def ping_check(db: AsyncSession = Depends(get_db)):
    """Checks RC-API health, DB connectivity, and optionally the clanimg main API."""
    result: dict[str, str] = {"rc_api": "ok"}

    try:
        await db.execute(text("SELECT 1"))
        result["db"] = "ok"
    except Exception as exc:
        result["db"] = f"error: {exc}"

    clanimg_url = os.getenv("CLANIMG_API_URL", "").rstrip("/")
    if clanimg_url:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{clanimg_url}/health")
            result["main_api"] = "ok" if resp.status_code == 200 else f"error: HTTP {resp.status_code}"
        except Exception as exc:
            result["main_api"] = f"error: {exc}"

    return result
