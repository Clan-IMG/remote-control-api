"""
AI Generation Services for PixelKid

Supports multiple AI backends:
- Stability AI (Stable Diffusion)
- Replicate
- Local Stable Diffusion

Each model type has specific prompts optimized for pixel art generation.
"""

import httpx
import base64
import io
from PIL import Image
from typing import Optional
from dataclasses import dataclass
from src.app.config import STABILITY_API_KEY, REPLICATE_API_KEY
from src.app.models import ModelType


@dataclass
class GenerationResult:
    success: bool
    image_data: Optional[bytes] = None
    error_message: Optional[str] = None
    processing_time_ms: Optional[int] = None


# Model-specific prompt templates
MODEL_PROMPTS = {
    ModelType.BLOCK_AGENT: {
        "base": "minecraft block texture, 2D front view, flat design, 16-bit pixel art style, "
                "seamless tileable texture, {user_prompt}, clean edges, no gradients, "
                "game asset, isolated on transparent background",
        "negative": "3d, perspective, shading, gradient, blurry, noise, realistic, photo, "
                   "complex details, text, watermark, signature",
        "width": 256,
        "height": 256,
        "steps": 30,
        "cfg_scale": 7
    },
    ModelType.ITEM_AGENT: {
        "base": "minecraft item icon, 2D top-down isometric view, 16-bit pixel art style, "
                "{user_prompt}, clean pixel edges, flat colors, game inventory icon, "
                "isolated on transparent background, no shadow",
        "negative": "3d render, realistic, photo, blurry, noise, gradient shading, "
                   "complex background, text, watermark",
        "width": 256,
        "height": 256,
        "steps": 30,
        "cfg_scale": 7
    },
    ModelType.ARMOR_AGENT: {
        "base": "minecraft armor piece, pixel art sprite, 16-bit style, {user_prompt}, "
                "front facing, flat colors, clean edges, game character equipment, "
                "isolated on transparent background",
        "negative": "3d, realistic, photo, gradient, blur, complex details, "
                   "text, watermark, background scenery",
        "width": 256,
        "height": 256,
        "steps": 30,
        "cfg_scale": 7
    },
    ModelType.PROMPT_AGENT: {
        "base": "16-bit pixel art, retro game style, {user_prompt}, clean pixels, "
                "flat colors, no anti-aliasing, crisp edges",
        "negative": "blurry, gradient, realistic, 3d, complex, noisy",
        "width": 512,
        "height": 512,
        "steps": 35,
        "cfg_scale": 8
    },
    ModelType.CUSTOM: {
        "base": "{user_prompt}",
        "negative": "blurry, noise, low quality",
        "width": 512,
        "height": 512,
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


def downscale_to_pixel_art(image_data: bytes, target_width: int, target_height: int) -> bytes:
    """
    Downscale image to target pixel size using nearest neighbor resampling.
    This preserves the crisp pixel art look.
    """
    img = Image.open(io.BytesIO(image_data))
    
    # Convert to RGBA if needed
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    
    # Downscale using NEAREST to keep pixel art crisp
    img_small = img.resize((target_width, target_height), Image.Resampling.NEAREST)
    
    # Save to bytes
    output = io.BytesIO()
    img_small.save(output, format="PNG")
    return output.getvalue()


async def generate_with_stability(
    prompt: str,
    negative_prompt: str,
    width: int = 256,
    height: int = 256,
    steps: int = 30,
    cfg_scale: float = 7
) -> GenerationResult:
    """Generate image using Stability AI API"""
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
                    "width": width,
                    "height": height,
                    "steps": steps,
                    "samples": 1
                }
            )
            
            if response.status_code != 200:
                return GenerationResult(
                    success=False, 
                    error_message=f"Stability API error: {response.text}"
                )
            
            data = response.json()
            image_b64 = data["artifacts"][0]["base64"]
            image_data = base64.b64decode(image_b64)
            
            return GenerationResult(success=True, image_data=image_data)
            
    except Exception as e:
        return GenerationResult(success=False, error_message=str(e))


async def generate_with_replicate(
    prompt: str,
    negative_prompt: str,
    width: int = 256,
    height: int = 256
) -> GenerationResult:
    """Generate image using Replicate API"""
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
                        "width": width,
                        "height": height,
                        "num_outputs": 1
                    }
                }
            )
            
            if response.status_code != 201:
                return GenerationResult(
                    success=False,
                    error_message=f"Replicate API error: {response.text}"
                )
            
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
                    return GenerationResult(success=True, image_data=img_response.content)
                
                elif status_data["status"] == "failed":
                    return GenerationResult(
                        success=False,
                        error_message=status_data.get("error", "Generation failed")
                    )
            
            return GenerationResult(success=False, error_message="Generation timed out")
            
    except Exception as e:
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
    
    # Generate at higher resolution
    gen_width = template["width"]
    gen_height = template["height"]
    
    # Try Stability AI first, fall back to Replicate
    result = await generate_with_stability(
        prompt=full_prompt,
        negative_prompt=negative_prompt,
        width=gen_width,
        height=gen_height,
        steps=template["steps"],
        cfg_scale=template["cfg_scale"]
    )
    
    if not result.success and REPLICATE_API_KEY:
        result = await generate_with_replicate(
            prompt=full_prompt,
            negative_prompt=negative_prompt,
            width=gen_width,
            height=gen_height
        )
    
    if not result.success:
        return result
    
    # Downscale to pixel art size
    try:
        pixel_art_data = downscale_to_pixel_art(
            result.image_data,
            target_width,
            target_height
        )
        
        processing_time = int((time.time() - start_time) * 1000)
        
        return GenerationResult(
            success=True,
            image_data=pixel_art_data,
            processing_time_ms=processing_time
        )
    except Exception as e:
        return GenerationResult(success=False, error_message=f"Image processing error: {str(e)}")


# Need to import asyncio for Replicate polling
import asyncio
