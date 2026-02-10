import json
import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional
from src.app.database import get_db
from src.app.redis_client import get_redis, QUEUE_PENDING, KEY_REQUEST_PREFIX
from src.app.models import User, Generation, ModelType, RequestStatus, PublicGallery
from src.app.schemas import (
    GenerationRequest, GenerationResponse, GenerationQueueResponse, GenerationListResponse
)
from src.app.dependencies import get_current_user
from src.app.services.ai_generator import enhance_prompt_with_gpt
from src.app.config import UPLOAD_DIR

router = APIRouter(prefix="/v1/responses", tags=["Generations"])


class EnhancePromptRequest(BaseModel):
    prompt: str


class EnhancePromptResponse(BaseModel):
    original: str
    enhanced: str


class UpdateVisibilityRequest(BaseModel):
    is_public: bool


@router.post("/enhance-prompt", response_model=EnhancePromptResponse)
async def enhance_prompt(
    request: EnhancePromptRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Enhance a simple prompt using GPT-4o-mini.
    Returns the enhanced prompt optimized for pixel art generation.
    """
    enhanced = await enhance_prompt_with_gpt(request.prompt)
    return EnhancePromptResponse(
        original=request.prompt,
        enhanced=enhanced
    )


@router.post("/upload-reference")
async def upload_reference_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a reference image for image-to-image generation.
    Returns the URL of the uploaded image.
    """
    # Validate file type
    allowed_types = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type: {file.content_type}. Allowed: PNG, JPG, WEBP"
        )
    
    # Read and validate file size (max 10MB)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 10MB."
        )
    
    # Save to uploads directory
    ref_dir = os.path.join(UPLOAD_DIR, "references")
    os.makedirs(ref_dir, exist_ok=True)
    
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "png"
    filename = f"ref_{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(ref_dir, filename)
    
    with open(filepath, "wb") as f:
        f.write(content)
    
    reference_url = f"/uploads/references/{filename}"
    return {"reference_image_url": reference_url}


@router.post("", response_model=GenerationQueueResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_generation(
    request: GenerationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new image generation request.
    The request will be queued and processed by worker containers.
    """
    redis = await get_redis()
    
    # Create generation record
    generation = Generation(
        user_id=current_user.id,
        model=ModelType(request.model.value),
        prompt=request.input,
        size=request.size,
        is_public=request.is_public,
        reference_image_url=request.reference_image_url,
        reference_strength=request.reference_strength if request.reference_image_url else None,
        logo_text=request.logo_text,
        status=RequestStatus.PENDING
    )
    db.add(generation)
    await db.commit()
    await db.refresh(generation)
    
    # Add to Redis queue
    queue_data = {
        "id": generation.id,
        "user_id": current_user.id,
        "model": request.model.value,
        "prompt": request.input,
        "size": request.size,
        "is_public": request.is_public,
        "provider": request.provider.value,
        "reference_image_url": request.reference_image_url,
        "reference_strength": request.reference_strength if request.reference_image_url else None,
        "remove_bg": request.remove_bg,
        "logo_text": request.logo_text,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Store request data
    await redis.set(
        f"{KEY_REQUEST_PREFIX}{generation.id}",
        json.dumps(queue_data),
        ex=3600  # 1 hour TTL
    )
    
    # Add to pending queue
    await redis.lpush(QUEUE_PENDING, generation.id)
    
    # Get queue position
    queue_length = await redis.llen(QUEUE_PENDING)
    
    # Estimate wait time (rough: 10 seconds per request)
    estimated_wait = queue_length * 10
    
    return GenerationQueueResponse(
        id=generation.id,
        status=RequestStatus.PENDING,
        position_in_queue=queue_length,
        estimated_wait_seconds=estimated_wait
    )


@router.get("/{generation_id}", response_model=GenerationResponse)
async def get_generation(
    generation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific generation by ID"""
    result = await db.execute(
        select(Generation)
        .where(Generation.id == generation_id)
        .where(Generation.user_id == current_user.id)
    )
    generation = result.scalar_one_or_none()
    
    if not generation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generation not found"
        )
    
    return GenerationResponse(
        id=generation.id,
        model=generation.model.value,
        prompt=generation.prompt,
        size=generation.size,
        status=generation.status,
        is_public=generation.is_public,
        image_url=generation.image_url,
        reference_image_url=generation.reference_image_url,
        reference_strength=generation.reference_strength,
        logo_text=generation.logo_text,
        error_message=generation.error_message,
        processing_time_ms=generation.processing_time_ms,
        created_at=generation.created_at,
        completed_at=generation.completed_at
    )


@router.get("/{generation_id}/status", response_model=GenerationQueueResponse)
async def get_generation_status(
    generation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the current status and queue position of a generation"""
    redis = await get_redis()
    
    result = await db.execute(
        select(Generation)
        .where(Generation.id == generation_id)
        .where(Generation.user_id == current_user.id)
    )
    generation = result.scalar_one_or_none()
    
    if not generation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generation not found"
        )
    
    position = None
    estimated_wait = None
    
    if generation.status == RequestStatus.PENDING:
        # Get position in queue
        queue = await redis.lrange(QUEUE_PENDING, 0, -1)
        try:
            position = queue.index(generation_id) + 1
            estimated_wait = position * 10
        except ValueError:
            position = None
    
    return GenerationQueueResponse(
        id=generation.id,
        status=generation.status,
        position_in_queue=position,
        estimated_wait_seconds=estimated_wait
    )


@router.get("", response_model=GenerationListResponse)
async def list_generations(
    page: int = 1,
    per_page: int = 20,
    status_filter: RequestStatus = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all generations for the current user"""
    query = select(Generation).where(Generation.user_id == current_user.id)
    
    if status_filter:
        query = query.where(Generation.status == status_filter)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()
    
    # Get paginated results
    query = query.order_by(Generation.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    
    result = await db.execute(query)
    generations = result.scalars().all()
    
    items = [
        GenerationResponse(
            id=g.id,
            model=g.model.value,
            prompt=g.prompt,
            size=g.size,
            status=g.status,
            is_public=g.is_public,
            image_url=g.image_url,
            reference_image_url=g.reference_image_url,
            reference_strength=g.reference_strength,
            logo_text=g.logo_text,
            error_message=g.error_message,
            processing_time_ms=g.processing_time_ms,
            created_at=g.created_at,
            completed_at=g.completed_at
        )
        for g in generations
    ]
    
    return GenerationListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page
    )


@router.patch("/{generation_id}/visibility")
async def update_visibility(
    generation_id: str,
    request: UpdateVisibilityRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update the public/private visibility of a generation"""
    result = await db.execute(
        select(Generation)
        .where(Generation.id == generation_id)
        .where(Generation.user_id == current_user.id)
    )
    generation = result.scalar_one_or_none()
    
    if not generation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generation not found"
        )
    
    generation.is_public = request.is_public

    # Manage PublicGallery entry
    if request.is_public:
        # Check if exists
        gallery_entry = await db.execute(
            select(PublicGallery).where(PublicGallery.generation_id == generation.id)
        )
        if not gallery_entry.scalar_one_or_none():
            # Create entry
            new_gallery_item = PublicGallery(
                generation_id=generation.id,
                title=generation.prompt[:100] if generation.prompt else "Untitled",
                likes=0,
                downloads=0
            )
            db.add(new_gallery_item)

    await db.commit()
    
    return {"success": True, "is_public": request.is_public}


@router.delete("/{generation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generation(
    generation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a generation"""
    result = await db.execute(
        select(Generation)
        .where(Generation.id == generation_id)
        .where(Generation.user_id == current_user.id)
    )
    generation = result.scalar_one_or_none()
    
    if not generation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generation not found"
        )
    
    await db.delete(generation)
    await db.commit()
