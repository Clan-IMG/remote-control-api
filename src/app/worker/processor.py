"""
Worker for processing generation requests from the Redis queue.
This runs in separate containers that can be scaled up/down.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from src.app.config import (
    MAX_CONCURRENT_WORKERS, MAXIMUM_REQUESTS, UPLOAD_DIR,
    S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT
)
from src.app.redis_client import (
    get_redis, QUEUE_PENDING, QUEUE_PROCESSING, 
    QUEUE_COMPLETED, QUEUE_FAILED, KEY_REQUEST_PREFIX,
    KEY_CONTAINER_STATUS, KEY_CONTAINER_LOAD
)
from src.app.database import async_session
from src.app.models import Generation, PublicGallery, RequestStatus, ModelType
from src.app.services.ai_generator import generate_pixel_art

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Container ID for this worker instance
CONTAINER_ID = os.getenv("CONTAINER_ID", f"worker-{uuid.uuid4().hex[:8]}")


async def save_image(image_data: bytes, generation_id: str) -> tuple[str, str]:
    """
    Save image to storage and return URLs.
    Returns (image_url, thumbnail_url)
    """
    filename = f"{generation_id}.png"
    
    # If S3 is configured, upload there
    if S3_BUCKET and S3_ACCESS_KEY:
        try:
            import aioboto3
            
            session = aioboto3.Session()
            async with session.client(
                's3',
                endpoint_url=S3_ENDPOINT,
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY
            ) as s3:
                await s3.put_object(
                    Bucket=S3_BUCKET,
                    Key=f"generations/{filename}",
                    Body=image_data,
                    ContentType="image/png"
                )
            
            base_url = S3_ENDPOINT or f"https://{S3_BUCKET}.s3.amazonaws.com"
            image_url = f"{base_url}/{S3_BUCKET}/generations/{filename}"
            return image_url, image_url
            
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
    
    # Fall back to local storage
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filepath = os.path.join(UPLOAD_DIR, filename)
    
    with open(filepath, "wb") as f:
        f.write(image_data)
    
    # Return local URL (would be served by nginx or similar)
    image_url = f"/uploads/{filename}"
    return image_url, image_url


async def process_generation(request_data: dict) -> bool:
    """Process a single generation request"""
    generation_id = request_data["id"]
    
    logger.info(f"Processing generation {generation_id}")
    
    async with async_session() as db:
        try:
            # Get generation from database
            generation = await db.get(Generation, generation_id)
            if not generation:
                logger.error(f"Generation {generation_id} not found in database")
                return False
            
            # Update status to processing
            generation.status = RequestStatus.PROCESSING
            generation.container_id = CONTAINER_ID
            await db.commit()
            
            # Generate the image
            result = await generate_pixel_art(
                model_type=ModelType(request_data["model"]),
                user_prompt=request_data["prompt"],
                target_size=request_data.get("size", "16x16")
            )
            
            if result.success:
                # Save image
                image_url, thumbnail_url = await save_image(
                    result.image_data, 
                    generation_id
                )
                
                # Update database
                generation.status = RequestStatus.COMPLETED
                generation.image_url = image_url
                generation.thumbnail_url = thumbnail_url
                generation.processing_time_ms = result.processing_time_ms
                generation.completed_at = datetime.utcnow()
                
                # If public, add to gallery
                if generation.is_public:
                    gallery_entry = PublicGallery(
                        generation_id=generation_id,
                        title=request_data["prompt"][:100]
                    )
                    db.add(gallery_entry)
                
                await db.commit()
                logger.info(f"Generation {generation_id} completed successfully")
                return True
                
            else:
                generation.status = RequestStatus.FAILED
                generation.error_message = result.error_message
                generation.completed_at = datetime.utcnow()
                await db.commit()
                logger.error(f"Generation {generation_id} failed: {result.error_message}")
                return False
                
        except Exception as e:
            logger.exception(f"Error processing generation {generation_id}")
            try:
                generation.status = RequestStatus.FAILED
                generation.error_message = str(e)
                generation.completed_at = datetime.utcnow()
                await db.commit()
            except:
                pass
            return False


async def worker_loop():
    """Main worker loop - continuously processes queue items"""
    redis = await get_redis()
    
    # Register this container
    await redis.hset(KEY_CONTAINER_STATUS, CONTAINER_ID, "running")
    await redis.hset(KEY_CONTAINER_LOAD, CONTAINER_ID, "0")
    
    logger.info(f"Worker {CONTAINER_ID} started")
    
    active_tasks = 0
    
    try:
        while True:
            # Check if we can accept more work
            if active_tasks >= MAX_CONCURRENT_WORKERS:
                await asyncio.sleep(0.5)
                continue
            
            # Try to get a request from the queue
            request_id = await redis.rpoplpush(QUEUE_PENDING, QUEUE_PROCESSING)
            
            if not request_id:
                # No work available, wait a bit
                await asyncio.sleep(1)
                continue
            
            # Get request data
            request_json = await redis.get(f"{KEY_REQUEST_PREFIX}{request_id}")
            if not request_json:
                logger.error(f"Request data not found for {request_id}")
                await redis.lrem(QUEUE_PROCESSING, 1, request_id)
                continue
            
            request_data = json.loads(request_json)
            active_tasks += 1
            
            # Update load
            load_pct = int((active_tasks / MAX_CONCURRENT_WORKERS) * 100)
            await redis.hset(KEY_CONTAINER_LOAD, CONTAINER_ID, str(load_pct))
            
            # Process in background
            async def process_and_cleanup():
                nonlocal active_tasks
                try:
                    success = await process_generation(request_data)
                    
                    # Move to completed/failed queue
                    target_queue = QUEUE_COMPLETED if success else QUEUE_FAILED
                    await redis.lrem(QUEUE_PROCESSING, 1, request_id)
                    await redis.lpush(target_queue, request_id)
                    
                finally:
                    active_tasks -= 1
                    load_pct = int((active_tasks / MAX_CONCURRENT_WORKERS) * 100)
                    await redis.hset(KEY_CONTAINER_LOAD, CONTAINER_ID, str(load_pct))
            
            asyncio.create_task(process_and_cleanup())
            
    except asyncio.CancelledError:
        logger.info(f"Worker {CONTAINER_ID} shutting down...")
        await redis.hset(KEY_CONTAINER_STATUS, CONTAINER_ID, "stopped")
        raise


async def main():
    """Entry point for worker"""
    try:
        await worker_loop()
    except KeyboardInterrupt:
        logger.info("Worker interrupted")


if __name__ == "__main__":
    asyncio.run(main())
