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
    CUSTOM = "custom"


class RequestStatusEnum(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


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


class GenerationResponse(BaseModel):
    id: str
    model: str
    prompt: str
    size: str
    status: RequestStatusEnum
    is_public: bool
    image_url: Optional[str]
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
