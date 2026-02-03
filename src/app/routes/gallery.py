from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from src.app.database import get_db
from src.app.models import Generation, PublicGallery, User, RequestStatus
from src.app.schemas import GalleryItemResponse, GalleryListResponse

router = APIRouter(prefix="/v1/gallery", tags=["Gallery"])


@router.get("", response_model=GalleryListResponse)
async def list_public_gallery(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    model: str = None,
    sort_by: str = Query("recent", regex="^(recent|likes|downloads)$"),
    db: AsyncSession = Depends(get_db)
):
    """
    Browse public gallery of generated pixel art.
    Anyone can view public images.
    """
    # Base query for public generations
    query = (
        select(Generation, PublicGallery, User)
        .join(PublicGallery, PublicGallery.generation_id == Generation.id)
        .join(User, User.id == Generation.user_id)
        .where(Generation.is_public == True)
        .where(Generation.status == RequestStatus.COMPLETED)
        .where(Generation.image_url.isnot(None))
    )
    
    if model:
        query = query.where(Generation.model == model)
    
    # Sorting
    if sort_by == "likes":
        query = query.order_by(PublicGallery.likes.desc())
    elif sort_by == "downloads":
        query = query.order_by(PublicGallery.downloads.desc())
    else:  # recent
        query = query.order_by(Generation.created_at.desc())
    
    # Get total count
    count_query = (
        select(func.count())
        .select_from(Generation)
        .join(PublicGallery, PublicGallery.generation_id == Generation.id)
        .where(Generation.is_public == True)
        .where(Generation.status == RequestStatus.COMPLETED)
    )
    if model:
        count_query = count_query.where(Generation.model == model)
    total = (await db.execute(count_query)).scalar()
    
    # Paginate
    query = query.offset((page - 1) * per_page).limit(per_page)
    
    result = await db.execute(query)
    rows = result.all()
    
    items = [
        GalleryItemResponse(
            id=gallery.id,
            image_url=generation.image_url,
            thumbnail_url=generation.thumbnail_url,
            title=gallery.title,
            model=generation.model.value,
            prompt=generation.prompt,
            size=generation.size,
            likes=gallery.likes,
            downloads=gallery.downloads,
            created_at=generation.created_at,
            username=user.username
        )
        for generation, gallery, user in rows
    ]
    
    return GalleryListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page
    )


@router.post("/{gallery_id}/like")
async def like_gallery_item(
    gallery_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Like a gallery item"""
    result = await db.execute(
        select(PublicGallery).where(PublicGallery.id == gallery_id)
    )
    gallery = result.scalar_one_or_none()
    
    if not gallery:
        return {"error": "Not found"}, 404
    
    gallery.likes += 1
    await db.commit()
    
    return {"likes": gallery.likes}


@router.post("/{gallery_id}/download")
async def track_download(
    gallery_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Track a download of a gallery item"""
    result = await db.execute(
        select(PublicGallery).where(PublicGallery.id == gallery_id)
    )
    gallery = result.scalar_one_or_none()
    
    if not gallery:
        return {"error": "Not found"}, 404
    
    gallery.downloads += 1
    await db.commit()
    
    return {"downloads": gallery.downloads}
