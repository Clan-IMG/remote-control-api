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
    "picture-agent": ModelType.PICTURE_AGENT,
    "logo-agent-2d": ModelType.LOGO_AGENT_2D,
    "logo-agent-3d": ModelType.LOGO_AGENT_3D,
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


def _color_distance(c1: tuple, c2: tuple) -> float:
    """Euclidean color distance in RGB space."""
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5


def remove_background(img: Image.Image, tolerance: int = 30) -> Image.Image:
    """
    Remove background using flood-fill from image edges.
    
    Only removes *connected* background regions that touch the image border,
    so light-colored pixels inside the subject are preserved.
    Uses BFS flood-fill starting from every border pixel whose color is
    close to the detected background color.
    
    Args:
        img: PIL Image (any mode, will be converted to RGBA)
        tolerance: Euclidean RGB distance threshold (0–441). 30–50 works well.
    
    Returns:
        Image with transparent background (PNG-ready RGBA)
    """
    from collections import deque

    if img.mode != "RGBA":
        img = img.convert("RGBA")

    img = img.copy()  # don't mutate the original
    pixels = img.load()
    width, height = img.size

    # --- 1. Detect background color from corner samples ---
    corners = [
        (0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1),
        (1, 0), (width - 2, 0), (0, 1), (width - 1, 1),
        (1, height - 1), (width - 2, height - 1), (0, height - 2), (width - 1, height - 2),
    ]
    bg_samples = [pixels[x, y][:3] for x, y in corners if 0 <= x < width and 0 <= y < height]

    if not bg_samples:
        return img

    avg_r = sum(c[0] for c in bg_samples) // len(bg_samples)
    avg_g = sum(c[1] for c in bg_samples) // len(bg_samples)
    avg_b = sum(c[2] for c in bg_samples) // len(bg_samples)
    bg_color = (avg_r, avg_g, avg_b)

    # Only remove light backgrounds (brightness > ~78 %)
    brightness = (bg_color[0] + bg_color[1] + bg_color[2]) / 3
    if brightness < 200:
        logger.info(f"Background {bg_color} too dark (brightness {brightness:.0f}), skipping removal")
        return img

    logger.info(f"Flood-fill background removal: bg={bg_color}, tolerance={tolerance}")

    # --- 2. Flood-fill from every border pixel ---
    visited = [[False] * height for _ in range(width)]
    queue: deque[tuple[int, int]] = deque()

    def _is_bg(x: int, y: int) -> bool:
        r, g, b, _a = pixels[x, y]
        return _color_distance((r, g, b), bg_color) <= tolerance

    # Seed: all border pixels that match the background color
    for x in range(width):
        for y in (0, height - 1):
            if _is_bg(x, y):
                queue.append((x, y))
                visited[x][y] = True
    for y in range(height):
        for x in (0, width - 1):
            if not visited[x][y] and _is_bg(x, y):
                queue.append((x, y))
                visited[x][y] = True

    # BFS
    while queue:
        cx, cy = queue.popleft()
        pixels[cx, cy] = (0, 0, 0, 0)  # make transparent
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < width and 0 <= ny < height and not visited[nx][ny]:
                visited[nx][ny] = True
                if _is_bg(nx, ny):
                    queue.append((nx, ny))

    # --- 3. Optional: soften edges (anti-alias cleanup) ---
    # Pixels that border a transparent pixel but are close to bg get partial alpha
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            # Check if any neighbor is transparent
            has_transparent_neighbor = False
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and pixels[nx, ny][3] == 0:
                    has_transparent_neighbor = True
                    break
            if has_transparent_neighbor:
                dist = _color_distance((r, g, b), bg_color)
                if dist <= tolerance * 1.5:
                    # Fade alpha proportionally: closer to bg = more transparent
                    alpha_ratio = min(dist / (tolerance * 1.5), 1.0)
                    pixels[x, y] = (r, g, b, int(alpha_ratio * 255))

    return img


def downscale_to_pixel_art(image_data: bytes, target_width: int, target_height: int, remove_bg: bool = True) -> bytes:
    """
    Downscale image to target pixel size using nearest neighbor resampling.
    This preserves the crisp pixel art look.
    
    Args:
        image_data: Raw image bytes
        target_width: Target pixel width
        target_height: Target pixel height
        remove_bg: Whether to remove white/gray background and make transparent
    """
    img = Image.open(io.BytesIO(image_data))
    
    # Convert to RGBA if needed
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    
    # Remove background on full-res image first (better accuracy)
    if remove_bg:
        img = remove_background(img, tolerance=35)
    
    # Downscale using NEAREST to keep pixel art crisp
    img_small = img.resize((target_width, target_height), Image.Resampling.NEAREST)
    
    # Second pass on the small image to clean up any leftover edge artifacts
    if remove_bg:
        img_small = remove_background(img_small, tolerance=25)
    
    # Save to bytes as PNG (preserves alpha channel)
    output = io.BytesIO()
    img_small.save(output, format="PNG")
    return output.getvalue()


async def generate_with_stability(
    prompt: str,
    negative_prompt: str,
    steps: int = 30,
    cfg_scale: float = 7,
    reference_image: Optional[bytes] = None,
    reference_strength: Optional[float] = 0.5
) -> GenerationResult:
    """Generate image using Stability AI API with SDXL (1024x1024). Tries multiple API keys if available.
    If reference_image is provided, uses image-to-image mode with multipart/form-data."""
    if not STABILITY_API_KEYS:
        return GenerationResult(success=False, error_message="Stability API key not configured")
    
    last_error = None
    use_img2img = reference_image is not None
    
    # For img2img, prepare the init image (resize to 1024x1024 PNG)
    init_image_bytes = None
    if use_img2img:
        try:
            init_img = Image.open(io.BytesIO(reference_image))
            init_img = init_img.convert("RGB")
            init_img = init_img.resize(SDXL_DIMENSIONS, Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            init_img.save(buf, format="PNG")
            init_image_bytes = buf.getvalue()
            logger.info(f"Prepared reference image for img2img (strength: {reference_strength}, size: {len(init_image_bytes)} bytes)")
        except Exception as e:
            logger.warning(f"Failed to prepare reference image: {e}, falling back to txt2img")
            use_img2img = False
    
    # Normalize reference_strength: allow callers to pass None and coerce to a valid float
    if reference_strength is None:
        reference_strength = 0.5
    try:
        reference_strength = float(reference_strength)
    except Exception:
        reference_strength = 0.5
    # Clamp to valid range
    reference_strength = max(0.0, min(1.0, reference_strength))

    # image_strength mapping:
    # Our reference_strength: 0 = ignore reference, 1 = follow strongly
    # Stability image_strength: 0 = keep original exactly, 1 = ignore original completely
    # So: image_strength = 1 - reference_strength
    image_strength = max(0.05, min(0.95, 1.0 - reference_strength))
    
    # Try each API key
    for i, api_key in enumerate(STABILITY_API_KEYS):
        try:
            logger.info(f"Trying Stability API key {i + 1}/{len(STABILITY_API_KEYS)} ({'img2img' if use_img2img else 'txt2img'})...")
            
            async with httpx.AsyncClient(timeout=120.0) as client:
                if use_img2img and init_image_bytes:
                    # Image-to-image: Stability requires multipart/form-data
                    form_data = {
                        "init_image": ("reference.png", init_image_bytes, "image/png"),
                        "init_image_mode": (None, "IMAGE_STRENGTH"),
                        "image_strength": (None, str(image_strength)),
                        "text_prompts[0][text]": (None, prompt),
                        "text_prompts[0][weight]": (None, "1"),
                        "text_prompts[1][text]": (None, negative_prompt),
                        "text_prompts[1][weight]": (None, "-1"),
                        "cfg_scale": (None, str(cfg_scale)),
                        "steps": (None, str(steps)),
                        "samples": (None, "1"),
                    }
                    
                    response = await client.post(
                        "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/image-to-image",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Accept": "application/json"
                        },
                        files=form_data
                    )
                else:
                    # Standard text-to-image (JSON)
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
                            "width": SDXL_DIMENSIONS[0],
                            "height": SDXL_DIMENSIONS[1],
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
    prompt: str,
    reference_image: Optional[bytes] = None,
    reference_strength: Optional[float] = 0.5
) -> GenerationResult:
    """Generate image using OpenAI DALL-E API.
    If reference_image is provided, uses GPT-4o-mini vision to analyse the reference
    and enriches the prompt with a visual description so DALL-E follows it."""
    if not OPENAI_API_KEY:
        return GenerationResult(success=False, error_message="OpenAI API key not configured")
    
    # Normalize reference_strength early so downstream comparisons are safe
    if reference_strength is None:
        reference_strength = 0.5
    try:
        reference_strength = float(reference_strength)
    except Exception:
        reference_strength = 0.5
    reference_strength = max(0.0, min(1.0, reference_strength))

    final_prompt = prompt
    
    # If reference image provided, describe it with GPT-4o-mini vision and merge into prompt
    if reference_image is not None:
        try:
            # Resize to small JPEG to keep token cost low
            ref_img = Image.open(io.BytesIO(reference_image))
            ref_img = ref_img.convert("RGB")
            ref_img.thumbnail((512, 512), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            ref_img.save(buf, format="JPEG", quality=80)
            ref_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            
            # Build a very specific vision analysis prompt depending on strength
            if reference_strength >= 0.85:
                vision_system = (
                    "You are an expert image analyst. Describe this reference image in EXTREME detail (3-4 sentences): "
                    "exact colors (use specific color names like 'coral red', 'midnight blue'), exact shapes, "
                    "facial features, hair color/style, eye color, clothing, pose, expression, art style, "
                    "lighting direction, and color palette. Be VERY precise about every visual element. "
                    "Output ONLY the description."
                )
            elif reference_strength >= 0.5:
                vision_system = (
                    "You are an image description assistant. Describe the key visual elements of this reference image "
                    "in 2-3 sentences: main colors, shapes, style, composition, and notable features. "
                    "Be specific about colors and forms. Output ONLY the description, no preamble."
                )
            else:
                vision_system = (
                    "You are an image description assistant. Briefly describe the overall style and mood of "
                    "this reference image in 1-2 sentences: general color palette, art style, and atmosphere. "
                    "Output ONLY the description."
                )
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                vision_response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {
                                "role": "system",
                                "content": vision_system
                            },
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Describe this reference image:"},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{ref_b64}", "detail": "low"}}
                                ]
                            }
                        ],
                        "max_tokens": 200,
                        "temperature": 0.2
                    }
                )
                
                if vision_response.status_code == 200:
                    description = vision_response.json()["choices"][0]["message"]["content"].strip()
                    logger.info(f"OpenAI reference description: {description[:100]}...")
                    
                    # At very high strength: reference description IS the prompt, user prompt is secondary
                    if reference_strength >= 0.85:
                        final_prompt = (
                            f"IMPORTANT: Reproduce this exact image as pixel art: {description}. "
                            f"Match the exact colors, shapes, and composition described above. "
                            f"Additional context from user: {prompt}"
                        )
                    elif reference_strength >= 0.6:
                        final_prompt = (
                            f"Create pixel art that closely matches this reference: {description}. "
                            f"Use the same colors, forms, and style. "
                            f"User request: {prompt}"
                        )
                    elif reference_strength >= 0.35:
                        final_prompt = (
                            f"{prompt}. Follow the style and color palette of this reference: {description}"
                        )
                    else:
                        final_prompt = (
                            f"{prompt}. Loosely inspired by this mood/style: {description}"
                        )
                else:
                    logger.warning(f"GPT-4o vision failed ({vision_response.status_code}), using prompt without reference")
                    
        except Exception as e:
            logger.warning(f"Reference image analysis failed: {e}, using prompt without reference")
    
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
                    "prompt": final_prompt,
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
    target_size: str = "16x16",
    provider: str = "auto",
    reference_image: Optional[bytes] = None,
    reference_strength: Optional[float] = 0.5
) -> GenerationResult:
    """
    Main generation function.
    1. Enhance prompt with GPT if using prompt-agent
    2. Build appropriate prompt based on model type
    3. Generate at higher resolution (optionally using reference image for img2img)
    4. Downscale to target pixel size
    
    Args:
        model_type: The model type to use for generation
        user_prompt: The user's prompt
        target_size: Target pixel size (e.g., "16x16")
        provider: AI provider to use ("auto", "stability", "openai")
        reference_image: Optional reference image bytes for img2img
        reference_strength: How strongly to follow the reference (0.0-1.0)
    """
    import time
    start_time = time.time()
    
    # Normalize reference_strength early so callers passing None don't break comparisons
    if reference_strength is None:
        reference_strength = 0.5
    try:
        reference_strength = float(reference_strength)
    except Exception:
        reference_strength = 0.5
    reference_strength = max(0.0, min(1.0, reference_strength))

    # Get template settings
    template = MODEL_PROMPTS.get(model_type, MODEL_PROMPTS[ModelType.ITEM_AGENT])
    
    # Enhance prompt with GPT for prompt-agent
    # Skip enhancement when reference image is provided with high strength,
    # because enhancement invents creative details that contradict the reference.
    enhanced_prompt = None
    working_prompt = user_prompt
    skip_enhance = reference_image is not None and reference_strength >= 0.6
    if template.get("enhance_prompt", False) and not skip_enhance:
        logger.info(f"Enhancing prompt with GPT: '{user_prompt}'")
        enhanced_prompt = await enhance_prompt_with_gpt(user_prompt)
        working_prompt = enhanced_prompt
    elif skip_enhance:
        logger.info(f"Skipping prompt enhancement (reference_strength={reference_strength:.2f} >= 0.6)")
    
    # Build prompts
    full_prompt, negative_prompt = build_prompt(model_type, working_prompt)
    
    # Parse target size
    target_width, target_height = parse_size(target_size)
    
    # Track errors from each provider for debugging
    errors = []
    result = GenerationResult(success=False)
    
    # Provider-specific logic
    if provider == "stability":
        # Force Stability AI only
        if STABILITY_API_KEYS:
            logger.info("Using Stability AI (user selected)...")
            result = await generate_with_stability(
                prompt=full_prompt,
                negative_prompt=negative_prompt,
                steps=template["steps"],
                cfg_scale=template["cfg_scale"],
                reference_image=reference_image,
                reference_strength=reference_strength
            )
            if result.success:
                logger.info("Stability AI succeeded")
            else:
                errors.append(f"Stability: {result.error_message}")
                logger.warning(f"Stability AI failed: {result.error_message}")
        else:
            errors.append("Stability: No API key configured")
            
    elif provider == "openai":
        # Force OpenAI DALL-E (uses GPT-4o vision to describe reference for prompt enrichment)
        if OPENAI_API_KEY:
            logger.info("Using OpenAI DALL-E (user selected)...")
            result = await generate_with_openai(
                prompt=full_prompt,
                reference_image=reference_image,
                reference_strength=reference_strength
            )
            if result.success:
                logger.info("OpenAI DALL-E succeeded")
            else:
                errors.append(f"OpenAI: {result.error_message}")
                logger.warning(f"OpenAI failed: {result.error_message}")
        else:
            errors.append("OpenAI: No API key configured")
            
    else:
        # Auto mode: Try Stability AI first, then fallback
        # When reference image is provided, STRONGLY prefer Stability (real img2img)
        if reference_image is not None and STABILITY_API_KEYS:
            logger.info("Auto mode with reference image → forcing Stability AI (real img2img)...")
        
        if STABILITY_API_KEYS:
            logger.info("Trying Stability AI...")
            result = await generate_with_stability(
                prompt=full_prompt,
                negative_prompt=negative_prompt,
                steps=template["steps"],
                cfg_scale=template["cfg_scale"],
                reference_image=reference_image,
                reference_strength=reference_strength
            )
            if result.success:
                logger.info("Stability AI succeeded")
            else:
                errors.append(f"Stability: {result.error_message}")
                logger.warning(f"Stability AI failed: {result.error_message}")
        else:
            errors.append("Stability: No API key configured")
        
        # Fallback to Replicate (no img2img support currently)
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
        
        # Fallback to OpenAI (prompt enrichment only, no real img2img)
        if not result.success and OPENAI_API_KEY:
            logger.info("Falling back to OpenAI DALL-E (text-only, no real img2img)...")
            result = await generate_with_openai(
                prompt=full_prompt,
                reference_image=reference_image,
                reference_strength=reference_strength
            )
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
