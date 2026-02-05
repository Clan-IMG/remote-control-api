from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from src.app.database import get_db
from src.app.models import User, Generation, RequestStatus, ModelType

router = APIRouter(prefix="/v1/stats", tags=["Stats"])

@router.get("/public")
async def get_public_stats(db: AsyncSession = Depends(get_db)):
    """Get public statistics"""
    # Count generated images (completed)
    gen_query = select(func.count(Generation.id)).where(Generation.status == RequestStatus.COMPLETED)
    gen_result = await db.execute(gen_query)
    total_images = gen_result.scalar_one()

    # Count active users
    user_query = select(func.count(User.id)).where(User.is_active == True)
    user_result = await db.execute(user_query)
    total_users = user_result.scalar_one()

    # Get available models
    models = [model.value for model in ModelType]

    return {
        "images_generated": total_images,
        "active_users": total_users,
        "pixel_resolution": "16x16",
        "models": models
    }
