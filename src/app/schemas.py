from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Literal
from datetime import datetime
from enum import Enum


# ========== Enums ==========

class ModelTypeEnum(str, Enum):
    BLOCK_AGENT = "block-agent"
    ITEM_AGENT = "item-agent"
    ARMOR_AGENT = "armor-agent"
    PROMPT_AGENT = "prompt-agent"
    PICTURE_AGENT = "picture-agent"
    LOGO_AGENT_2D = "logo-agent-2d"
    LOGO_AGENT_3D = "logo-agent-3d"
    CUSTOM = "custom"


class RequestStatusEnum(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AIProviderEnum(str, Enum):
    AUTO = "auto"  # Automatic fallback (default)
    STABILITY = "stability"  # Stability AI (SDXL)
    OPENAI = "openai"  # OpenAI DALL-E


# ========== Auth Schemas ==========

class UserRegister(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    avatar_url: Optional[str] = None
    is_active: bool
    is_verified: bool
    is_admin: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


# Response returned after registration to indicate approval requirement or include created user
class RegistrationResponse(BaseModel):
    message: str
    user: Optional[UserResponse] = None

    class Config:
        from_attributes = True


# ========== API Key Schemas ==========

class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    expires_in_days: Optional[int] = None  # None = never expires


class ApiKeyResponse(BaseModel):
    id: str
    key_prefix: str
    name: str
    is_active: bool
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class ApiKeyCreated(ApiKeyResponse):
    """Response when creating a new API key - includes the full key (only shown once)"""
    api_key: str


# ========== Generation Schemas ==========

class GenerationRequest(BaseModel):
    model: ModelTypeEnum
    input: str = Field(..., min_length=1, max_length=1000)
    size: str = Field(default="16x16", pattern=r"^\d+x\d+$")
    is_public: bool = False
    provider: AIProviderEnum = AIProviderEnum.AUTO  # AI provider selection
    reference_image_url: Optional[str] = None  # URL of uploaded reference image
    reference_strength: float = Field(default=0.5, ge=0.0, le=1.0)  # How much to follow the reference
    remove_bg: bool = True  # Whether to remove background (make transparent)
    logo_text: Optional[str] = Field(default=None, max_length=50)  # Exact text to render in logo


class GenerationResponse(BaseModel):
    id: str
    model: str
    prompt: str
    size: str
    status: RequestStatusEnum
    is_public: bool
    image_url: Optional[str]
    reference_image_url: Optional[str] = None
    reference_strength: Optional[float] = None
    remove_bg: bool = True
    logo_text: Optional[str] = None
    error_message: Optional[str]
    processing_time_ms: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class GenerationQueueResponse(BaseModel):
    id: str
    status: RequestStatusEnum
    position_in_queue: Optional[int]
    estimated_wait_seconds: Optional[int]


class GenerationListResponse(BaseModel):
    items: list[GenerationResponse]
    total: int
    page: int
    per_page: int


# ========== Gallery Schemas ==========

class GalleryItemResponse(BaseModel):
    id: str
    image_url: str
    thumbnail_url: Optional[str]
    title: Optional[str]
    model: str
    prompt: str
    size: str
    likes: int
    downloads: int
    created_at: datetime
    username: str
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True


class GalleryListResponse(BaseModel):
    items: list[GalleryItemResponse]
    total: int
    page: int
    per_page: int


# ========== Container Status Schemas ==========

class ContainerStatus(BaseModel):
    id: str
    status: Literal["running", "starting", "stopping", "stopped"]
    current_requests: int
    max_requests: int
    load_percentage: float
    started_at: Optional[datetime]


class ContainerScalingStatus(BaseModel):
    active_containers: int
    min_containers: int
    max_containers: int
    total_pending_requests: int
    total_processing_requests: int
    containers: list[ContainerStatus]


# ========== Health Schemas ==========

class HealthResponse(BaseModel):
    status: str
    version: str
    redis_connected: bool
    database_connected: bool
    active_containers: int

# ========== System/Admin Schemas ==========

class SystemSettingUpdate(BaseModel):
    key: str
    value: str

class SystemSettingResponse(BaseModel):
    key: str
    value: Optional[str]
    description: Optional[str]
    updated_at: datetime
    
    class Config:
        from_attributes = True

class UserApprovalUpdate(BaseModel):
    user_id: str
    login_enabled: bool

