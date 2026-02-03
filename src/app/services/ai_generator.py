"""
AI Generation Services for PixelKid

Supports multiple AI backends:
- Stability AI (Stable Diffusion)
- Replicate
- OpenAI (DALL-E)

Each model type has specific prompts optimized for pixel art generation.
With automatic fallback: Stability → Replicate → OpenAI
Includes prompt enhancement using GPT-4o-mini for prompt-agent.
"""

import httpx
import base64
import io
import json
import asyncio
import logging
from pathlib import Path
from PIL import Image
from typing import Optional
from dataclasses import dataclass
from src.app.config import STABILITY_API_KEYS, REPLICATE_API_KEY, OPENAI_API_KEY
from src.app.models import ModelType

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    success: bool
    image_data: Optional[bytes] = None
    error_message: Optional[str] = None
    processing_time_ms: Optional[int] = None
    provider_used: Optional[str] = None
    enhanced_prompt: Optional[str] = None


# SDXL allowed dimensions (must use these for Stability AI)
SDXL_DIMENSIONS = (1024, 1024)

# Load prompt configuration from JSON file
_CONFIG_PATH = Path(__file__).parent / "prompt_config.json"

def _load_prompt_config():
    """Load prompt configuration from JSON file"""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

_config = _load_prompt_config()

# Prompt enhancement system prompt
PROMPT_ENHANCEMENT_SYSTEM = _config["prompt_enhancement_system"]

# Model-specific prompt templates (convert string keys to ModelType enum)
_MODEL_TYPE_MAP = {
    "block-agent": ModelType.BLOCK_AGENT,
    "item-agent": ModelType.ITEM_AGENT,
    "armor-agent": ModelType.ARMOR_AGENT,
    "prompt-agent": ModelType.PROMPT_AGENT,
}

MODEL_PROMPTS = {
    _MODEL_TYPE_MAP[key]: value
    for key, value in _config["model_prompts"].items()
}


async def enhance_prompt_with_gpt(user_prompt: str) -> str:
    """
    Use GPT-4o-mini to enhance a simple prompt into a detailed pixel art prompt.
    This is cheap and fast (~$0.00015 per request).
    """
    if not OPENAI_API_KEY:
        logger.warning("OpenAI API key not configured, skipping prompt enhancement")
        return user_prompt
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",  # Super cheap: $0.15/1M input, $0.60/1M output
                    "messages": [
                        {"role": "system", "content": PROMPT_ENHANCEMENT_SYSTEM},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 200,
                    "temperature": 0.7
                }
            )
            
            if response.status_code != 200:
                logger.warning(f"GPT prompt enhancement failed: {response.text}")
                return user_prompt
            
            data = response.json()
            enhanced = data["choices"][0]["message"]["content"].strip()
            logger.info(f"Enhanced prompt: '{user_prompt}' → '{enhanced[:100]}...'")
            return enhanced
            
    except Exception as e:
        logger.error(f"Prompt enhancement error: {e}")
        return user_prompt


def build_prompt(model_type: ModelType, user_prompt: str) -> tuple[str, str]:
    """Build the full prompt from model template and user input"""
    template = MODEL_PROMPTS.get(model_type, MODEL_PROMPTS[ModelType.ITEM_AGENT])
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
    steps: int = 30,
    cfg_scale: float = 7
) -> GenerationResult:
    """Generate image using Stability AI API with SDXL (1024x1024). Tries multiple API keys if available."""
    if not STABILITY_API_KEYS:
        return GenerationResult(success=False, error_message="Stability API key not configured")
    
    last_error = None
    
    # Try each API key
    for i, api_key in enumerate(STABILITY_API_KEYS):
        try:
            logger.info(f"Trying Stability API key {i + 1}/{len(STABILITY_API_KEYS)}...")
            
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
                    headers={
                        "Authorization": f"Bearer {api_key}",
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
                
                if response.status_code == 200:
                    data = response.json()
                    image_b64 = data["artifacts"][0]["base64"]
                    image_data = base64.b64decode(image_b64)
                    
                    logger.info(f"Stability API key {i + 1} succeeded")
                    return GenerationResult(success=True, image_data=image_data, provider_used="stability")
                
                # Check if it's a balance error
                error_msg = f"Stability API error: {response.text}"
                last_error = error_msg
                
                if response.status_code == 429:
                    logger.warning(f"Stability API key {i + 1} failed (insufficient balance or rate limit): {response.text}")
                    continue  # Try next key
                else:
                    logger.warning(error_msg)
                    return GenerationResult(success=False, error_message=error_msg)
                
        except Exception as e:
            last_error = str(e)
            logger.error(f"Stability AI key {i + 1} exception: {e}")
            continue  # Try next key
    
    # All keys failed
    return GenerationResult(success=False, error_message=last_error or "All Stability API keys failed")


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
    1. Enhance prompt with GPT if using prompt-agent
    2. Build appropriate prompt based on model type
    3. Generate at higher resolution
    4. Downscale to target pixel size
    """
    import time
    start_time = time.time()
    
    # Get template settings
    template = MODEL_PROMPTS.get(model_type, MODEL_PROMPTS[ModelType.ITEM_AGENT])
    
    # Enhance prompt with GPT for prompt-agent
    enhanced_prompt = None
    working_prompt = user_prompt
    if template.get("enhance_prompt", False):
        logger.info(f"Enhancing prompt with GPT: '{user_prompt}'")
        enhanced_prompt = await enhance_prompt_with_gpt(user_prompt)
        working_prompt = enhanced_prompt
    
    # Build prompts
    full_prompt, negative_prompt = build_prompt(model_type, working_prompt)
    
    # Parse target size
    target_width, target_height = parse_size(target_size)
    
    # Track errors from each provider for debugging
    errors = []
    result = GenerationResult(success=False)
    
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
            processing_time_ms=processing_time,
            provider_used=result.provider_used,
            enhanced_prompt=enhanced_prompt
        )
    except Exception as e:
        return GenerationResult(success=False, error_message=f"Image processing error: {str(e)}")
