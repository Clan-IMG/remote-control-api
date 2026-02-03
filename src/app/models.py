from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, Enum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.app.database import Base
import enum
import uuid


class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ModelType(str, enum.Enum):
    BLOCK_AGENT = "block-agent"
    ITEM_AGENT = "item-agent"
    ARMOR_AGENT = "armor-agent"
    PROMPT_AGENT = "prompt-agent"
    CUSTOM = "custom"


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    username = Column(String(50), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    generations = relationship("Generation", back_populates="user", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    key_hash = Column(String(255), nullable=False, unique=True)
    key_prefix = Column(String(20), nullable=False)  # pk_xxxx for display
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="api_keys")


class Generation(Base):
    __tablename__ = "generations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    model = Column(Enum(ModelType), nullable=False)
    prompt = Column(Text, nullable=False)
    processed_prompt = Column(Text, nullable=True)  # The actual prompt sent to AI
    size = Column(String(20), default="16x16")
    status = Column(Enum(RequestStatus), default=RequestStatus.PENDING)
    is_public = Column(Boolean, default=False)
    image_url = Column(String(500), nullable=True)
    thumbnail_url = Column(String(500), nullable=True)
    error_message = Column(Text, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    container_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="generations")


class PublicGallery(Base):
    __tablename__ = "public_gallery"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    generation_id = Column(String(36), ForeignKey("generations.id"), nullable=False)
    title = Column(String(200), nullable=True)
    likes = Column(Integer, default=0)
    downloads = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    generation = relationship("Generation")


class ModelTemplate(Base):
    """Stores prompt templates for different model types"""
    __tablename__ = "model_templates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_type = Column(Enum(ModelType), nullable=False, unique=True)
    base_prompt = Column(Text, nullable=False)
    negative_prompt = Column(Text, nullable=True)
    generation_width = Column(Integer, default=256)
    generation_height = Column(Integer, default=256)
    target_width = Column(Integer, default=16)
    target_height = Column(Integer, default=16)
    cfg_scale = Column(Integer, default=7)
    steps = Column(Integer, default=30)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
