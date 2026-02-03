"""
Prompt Enhancement Routes

Uses OpenAI's cheap model (gpt-4o-mini) to enhance user prompts
for better AI image generation results.
"""

import httpx
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from src.app.config import OPENAI_API_KEY
from src.app.dependencies import get_current_user
from src.app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/prompts", tags=["prompts"])


class PromptEnhanceRequest(BaseModel):
    prompt: str
    model: str = "prompt-agent"


class PromptEnhanceResponse(BaseModel):
    enhanced_prompt: str
    original_prompt: str


# System prompts for different model types
ENHANCEMENT_PROMPTS = {
    "block-agent": """You are an expert at writing prompts for AI image generation, specifically for Minecraft block textures.
Transform the user's simple description into a detailed, optimized prompt for generating a 2D Minecraft block texture.

Rules:
- Keep it concise but descriptive (max 100 words)
- Focus on visual characteristics: colors, patterns, materials, surface details
- Mention it should be a seamless, tileable texture
- Use keywords like: pixel art, 16-bit, 2D frontal view, game asset, clean edges
- Do NOT include any explanations, just output the enhanced prompt""",

    "item-agent": """You are an expert at writing prompts for AI image generation, specifically for Minecraft item icons.
Transform the user's simple description into a detailed, optimized prompt for generating a Minecraft inventory item icon.

Rules:
- Keep it concise but descriptive (max 100 words)
- Focus on the item's visual design, material, and distinctive features
- Mention it should be an isometric or top-down view icon
- Use keywords like: pixel art, inventory icon, game item, flat colors, no shadow
- Do NOT include any explanations, just output the enhanced prompt""",

    "armor-agent": """You are an expert at writing prompts for AI image generation, specifically for Minecraft armor sprites.
Transform the user's simple description into a detailed, optimized prompt for generating a Minecraft armor piece.

Rules:
- Keep it concise but descriptive (max 100 words)
- Focus on armor design, material, enchantment effects, details
- Mention it should be a front-facing sprite
- Use keywords like: pixel art, armor sprite, equipment, game asset
- Do NOT include any explanations, just output the enhanced prompt""",

    "prompt-agent": """You are an expert at writing prompts for AI image generation, specifically for pixel art.
Transform the user's simple description into a detailed, optimized prompt for generating beautiful pixel art.

Rules:
- Keep it concise but descriptive (max 120 words)
- Add artistic details: lighting, mood, color palette, composition
- Use keywords like: pixel art, 16-bit, retro game style, crisp pixels, vibrant colors
- Make it vivid and imaginative while staying true to the user's intent
- Do NOT include any explanations, just output the enhanced prompt"""
}


@router.post("/enhance", response_model=PromptEnhanceResponse)
async def enhance_prompt(
    request: PromptEnhanceRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Enhance a user's prompt using OpenAI's gpt-4o-mini model.
    This improves the prompt for better AI image generation results.
    """
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Prompt enhancement not available (OpenAI API key not configured)"
        )
    
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    
    if len(request.prompt) > 500:
        raise HTTPException(status_code=400, detail="Prompt too long (max 500 characters)")
    
    # Get the system prompt for this model type
    system_prompt = ENHANCEMENT_PROMPTS.get(
        request.model, 
        ENHANCEMENT_PROMPTS["prompt-agent"]
    )
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",  # Cheap and fast
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": request.prompt}
                    ],
                    "max_tokens": 200,
                    "temperature": 0.7
                }
            )
            
            if response.status_code != 200:
                logger.error(f"OpenAI API error: {response.text}")
                raise HTTPException(
                    status_code=502,
                    detail="Failed to enhance prompt"
                )
            
            data = response.json()
            enhanced = data["choices"][0]["message"]["content"].strip()
            
            # Remove quotes if the model wrapped the response
            if enhanced.startswith('"') and enhanced.endswith('"'):
                enhanced = enhanced[1:-1]
            
            logger.info(f"Enhanced prompt: '{request.prompt}' -> '{enhanced[:50]}...'")
            
            return PromptEnhanceResponse(
                enhanced_prompt=enhanced,
                original_prompt=request.prompt
            )
            
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Enhancement timed out")
    except Exception as e:
        logger.error(f"Prompt enhancement error: {e}")
        raise HTTPException(status_code=500, detail="Enhancement failed")
