"""
AI Generation Services for PixelKid

Supports multiple AI backends:
- Stability AI (Stable Diffusion)
- Replicate
- OpenAI (DALL-E)

Each model type has specific prompts optimized for pixel art generation.
With automatic fallback: Stability → Replicate → OpenAI
"""

import httpx
import base64
import io
import asyncio
import logging
from PIL import Image
from typing import Optional
from dataclasses import dataclass
from src.app.config import STABILITY_API_KEY, REPLICATE_API_KEY, OPENAI_API_KEY
from src.app.models import ModelType

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    success: bool
    image_data: Optional[bytes] = None  # The actual pixel art (16x16, 32x32, etc.)
    preview_data: Optional[bytes] = None  # Upscaled preview for display (512x512)
    error_message: Optional[str] = None
    processing_time_ms: Optional[int] = None
    provider_used: Optional[str] = None


# SDXL allowed dimensions (must use these for Stability AI)
SDXL_DIMENSIONS = (1024, 1024)

# Model-specific prompt templates - OPTIMIZED FOR 2D FLAT TEXTURES
MODEL_PROMPTS = {
    ModelType.BLOCK_AGENT: {
        "base": "minecraft texture, flat 2D square texture, pixel art, 16x16 pixel grid, "
                "{user_prompt}, single flat surface, NO 3D, NO perspective, NO cube, NO block shape, "
                "seamless tileable, limited color palette, crisp pixel edges, retro game texture, "
                "top-down view of one face only, solid colors, no gradients, no shading",
        "negative": "3d, cube, block, perspective, isometric, depth, shadow, shading, gradient, "
                   "blurry, realistic, photo, render, multiple sides, corner, edge view, "
                   "anti-aliasing, smooth, text, watermark, complex, detailed",
        "steps": 35,
        "cfg_scale": 9
    },
    ModelType.ITEM_AGENT: {
        "base": "minecraft item sprite, flat 2D pixel art icon, 16x16 pixel grid, "
                "{user_prompt}, game inventory icon, NO 3D, NO perspective, NO depth, "
                "flat colors, clean pixel edges, limited palette, retro game sprite, "
                "centered item on transparent background, crisp pixels",
        "negative": "3d, perspective, depth, shadow, shading, gradient, blurry, realistic, "
                   "photo, render, anti-aliasing, smooth, text, watermark, complex background",
        "steps": 35,
        "cfg_scale": 9
    },
    ModelType.ARMOR_AGENT: {
        "base": "minecraft armor texture, flat 2D sprite sheet style, pixel art, "
                "{user_prompt}, NO 3D, NO perspective, flat design, limited color palette, "
                "clean pixel edges, game character equipment sprite, front facing flat view",
        "negative": "3d, perspective, depth, shadow, shading, gradient, blurry, realistic, "
                   "photo, render, anti-aliasing, smooth, text, watermark, worn by character",
        "steps": 35,
        "cfg_scale": 9
    },
    ModelType.PROMPT_AGENT: {
        "base": "pixel art, 16-bit retro game style, {user_prompt}, flat 2D, "
                "clean crisp pixels, limited color palette, no anti-aliasing, no gradients",
        "negative": "3d, blurry, gradient, realistic, smooth, anti-aliasing, noisy, complex",
        "steps": 35,
        "cfg_scale": 8
    },
    ModelType.CUSTOM: {
        "base": "{user_prompt}",
        "negative": "blurry, noise, low quality",
        "steps": 30,
        "cfg_scale": 7
    }
}


def build_prompt(model_type: ModelType, user_prompt: str) -> tuple[str, str]:
    """Build the full prompt from model template and user input"""
    template = MODEL_PROMPTS.get(model_type, MODEL_PROMPTS[ModelType.CUSTOM])
    full_prompt = template["base"].format(user_prompt=user_prompt)
    negative_prompt = template["negative"]
    return full_prompt, negative_prompt


def parse_size(size_str: str) -> tuple[int, int]:
    """Parse size string like '16x16' to (width, height)"""
    parts = size_str.lower().split("x")
    return int(parts[0]), int(parts[1])


def downscale_to_pixel_art(image_data: bytes, target_width: int, target_height: int, model_type: str = "prompt-agent") -> bytes:
    """
    Process image for pixel art output.
    Creates a REAL pixel art image at the target size using NEAREST neighbor.
    
    This produces actual 16x16, 32x32, 64x64 etc. pixel images that work in Blockbench.
    """
    img = Image.open(io.BytesIO(image_data))
    
    # Convert to RGBA if needed
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    
    # For Minecraft textures, we want ACTUAL pixel dimensions
    # Use NEAREST neighbor resampling for crisp pixel art look
    target_size = (target_width, target_height)
    
    # Resize using NEAREST for that authentic pixel art look
    img_resized = img.resize(target_size, Image.Resampling.NEAREST)
    
    # Save to bytes
    output = io.BytesIO()
    img_resized.save(output, format="PNG", optimize=True)
    return output.getvalue()


def create_preview_image(image_data: bytes, model_type: str = "prompt-agent") -> bytes:
    """
    Create a larger preview image for display purposes.
    The preview is upscaled from the pixel art version for consistent display.
    """
    img = Image.open(io.BytesIO(image_data))
    
    # Convert to RGBA if needed
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    
    # Create a larger preview using NEAREST to maintain pixel art aesthetic
    if model_type in ["block-agent", "item-agent", "armor-agent"]:
        preview_size = (512, 512)  # 16x16 → 512x512 = 32x upscale
    else:
        preview_size = (512, 512)
    
    img_preview = img.resize(preview_size, Image.Resampling.NEAREST)
    
    output = io.BytesIO()
    img_preview.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def generate_with_stability(
    prompt: str,
    negative_prompt: str,
    steps: int = 30,
    cfg_scale: float = 7
) -> GenerationResult:
    """Generate image using Stability AI API with SDXL (1024x1024)"""
    if not STABILITY_API_KEY:
        return GenerationResult(success=False, error_message="Stability API key not configured")
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
                headers={
                    "Authorization": f"Bearer {STABILITY_API_KEY}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                json={
                    "text_prompts": [
                        {"text": prompt, "weight": 1},
                        {"text": negative_prompt, "weight": -1}
                    ],
                    "cfg_scale": cfg_scale,
                    "width": SDXL_DIMENSIONS[0],  # Must be 1024
                    "height": SDXL_DIMENSIONS[1],  # Must be 1024
                    "steps": steps,
                    "samples": 1
                }
            )
            
            if response.status_code != 200:
                error_msg = f"Stability API error: {response.text}"
                logger.warning(error_msg)
                return GenerationResult(success=False, error_message=error_msg)
            
            data = response.json()
            image_b64 = data["artifacts"][0]["base64"]
            image_data = base64.b64decode(image_b64)
            
            return GenerationResult(success=True, image_data=image_data, provider_used="stability")
            
    except Exception as e:
        logger.error(f"Stability AI exception: {e}")
        return GenerationResult(success=False, error_message=str(e))


async def generate_with_replicate(
    prompt: str,
    negative_prompt: str
) -> GenerationResult:
    """Generate image using Replicate API (SDXL)"""
    if not REPLICATE_API_KEY:
        return GenerationResult(success=False, error_message="Replicate API key not configured")
    
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            # Start prediction
            response = await client.post(
                "https://api.replicate.com/v1/predictions",
                headers={
                    "Authorization": f"Token {REPLICATE_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "version": "39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",  # SDXL
                    "input": {
                        "prompt": prompt,
                        "negative_prompt": negative_prompt,
                        "width": 1024,
                        "height": 1024,
                        "num_outputs": 1
                    }
                }
            )
            
            if response.status_code != 201:
                error_msg = f"Replicate API error: {response.text}"
                logger.warning(error_msg)
                return GenerationResult(success=False, error_message=error_msg)
            
            prediction = response.json()
            prediction_url = prediction["urls"]["get"]
            
            # Poll for completion
            for _ in range(60):  # Max 60 attempts (3 minutes)
                await asyncio.sleep(3)
                
                status_response = await client.get(
                    prediction_url,
                    headers={"Authorization": f"Token {REPLICATE_API_KEY}"}
                )
                status_data = status_response.json()
                
                if status_data["status"] == "succeeded":
                    image_url = status_data["output"][0]
                    
                    # Download image
                    img_response = await client.get(image_url)
                    return GenerationResult(success=True, image_data=img_response.content, provider_used="replicate")
                
                elif status_data["status"] == "failed":
                    error_msg = status_data.get("error", "Generation failed")
                    logger.warning(f"Replicate failed: {error_msg}")
                    return GenerationResult(success=False, error_message=error_msg)
            
            return GenerationResult(success=False, error_message="Generation timed out")
            
    except Exception as e:
        logger.error(f"Replicate exception: {e}")
        return GenerationResult(success=False, error_message=str(e))


async def generate_with_openai(
    prompt: str
) -> GenerationResult:
    """Generate image using OpenAI DALL-E API"""
    if not OPENAI_API_KEY:
        return GenerationResult(success=False, error_message="OpenAI API key not configured")
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "dall-e-3",
                    "prompt": prompt,
                    "n": 1,
                    "size": "1024x1024",
                    "response_format": "b64_json"
                }
            )
            
            if response.status_code != 200:
                error_msg = f"OpenAI API error: {response.text}"
                logger.warning(error_msg)
                return GenerationResult(success=False, error_message=error_msg)
            
            data = response.json()
            image_b64 = data["data"][0]["b64_json"]
            image_data = base64.b64decode(image_b64)
            
            return GenerationResult(success=True, image_data=image_data, provider_used="openai")
            
    except Exception as e:
        logger.error(f"OpenAI exception: {e}")
        return GenerationResult(success=False, error_message=str(e))


async def generate_pixel_art(
    model_type: ModelType,
    user_prompt: str,
    target_size: str = "16x16"
) -> GenerationResult:
    """
    Main generation function.
    1. Build appropriate prompt based on model type
    2. Generate at higher resolution
    3. Downscale to target pixel size
    """
    import time
    start_time = time.time()
    
    # Get template settings
    template = MODEL_PROMPTS.get(model_type, MODEL_PROMPTS[ModelType.CUSTOM])
    
    # Build prompts
    full_prompt, negative_prompt = build_prompt(model_type, user_prompt)
    
    # Parse target size
    target_width, target_height = parse_size(target_size)
    
    # Track errors from each provider for debugging
    errors = []
    
    # Try Stability AI first
    if STABILITY_API_KEY:
        logger.info("Trying Stability AI...")
        result = await generate_with_stability(
            prompt=full_prompt,
            negative_prompt=negative_prompt,
            steps=template["steps"],
            cfg_scale=template["cfg_scale"]
        )
        if result.success:
            logger.info("Stability AI succeeded")
        else:
            errors.append(f"Stability: {result.error_message}")
            logger.warning(f"Stability AI failed: {result.error_message}")
    else:
        result = GenerationResult(success=False, error_message="No API key")
        errors.append("Stability: No API key configured")
    
    # Fallback to Replicate
    if not result.success and REPLICATE_API_KEY:
        logger.info("Falling back to Replicate...")
        result = await generate_with_replicate(
            prompt=full_prompt,
            negative_prompt=negative_prompt
        )
        if result.success:
            logger.info("Replicate succeeded")
        else:
            errors.append(f"Replicate: {result.error_message}")
            logger.warning(f"Replicate failed: {result.error_message}")
    
    # Fallback to OpenAI
    if not result.success and OPENAI_API_KEY:
        logger.info("Falling back to OpenAI DALL-E...")
        result = await generate_with_openai(prompt=full_prompt)
        if result.success:
            logger.info("OpenAI DALL-E succeeded")
        else:
            errors.append(f"OpenAI: {result.error_message}")
            logger.warning(f"OpenAI failed: {result.error_message}")
    
    # If all failed, return combined error message
    if not result.success:
        combined_error = " | ".join(errors) if errors else "No AI providers configured"
        return GenerationResult(success=False, error_message=combined_error)
    
    # Process image to appropriate size
    try:
        model_type_str = model_type.value if hasattr(model_type, 'value') else str(model_type)
        
        # Create the actual pixel art image (16x16, 32x32, etc.)
        pixel_art_data = downscale_to_pixel_art(
            result.image_data,
            target_width,
            target_height,
            model_type_str
        )
        
        # Create a larger preview image for display (upscaled from pixel art)
        preview_data = create_preview_image(
            pixel_art_data,
            model_type_str
        )
        
        processing_time = int((time.time() - start_time) * 1000)
        
        return GenerationResult(
            success=True,
            image_data=pixel_art_data,  # Actual 16x16 for Blockbench
            preview_data=preview_data,  # 512x512 for display
            processing_time_ms=processing_time,
            provider_used=result.provider_used
        )
    except Exception as e:
        return GenerationResult(success=False, error_message=f"Image processing error: {str(e)}")
