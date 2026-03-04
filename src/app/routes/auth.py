from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
import os
import uuid
import aiofiles
from src.app.database import get_db
from src.app.models import User, ApiKey, SystemSetting
from src.app.schemas import (
    UserRegister, UserLogin, UserResponse, TokenResponse,
    ApiKeyCreate, ApiKeyResponse, ApiKeyCreated, ProfileUpdate,
    RefreshTokenRequest, RegistrationResponse,
    EmailUpdate, AccountDeleteRequest, AccountDeleteResponse,
    SendVerificationEmailResponse, VerifyEmailRequest
)
from src.app.auth import (
    hash_password, verify_password, authenticate_user, create_access_token, 
    create_refresh_token, generate_api_key, verify_token,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from src.app.dependencies import get_current_user
from src.app.config import UPLOAD_DIR, OTP_TTL_SECONDS
from src.app.services.email_service import (
    generate_otp, store_otp, verify_otp, otp_ttl_remaining,
    send_verification_email,
)

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])

# Allowed image types
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/register", response_model=RegistrationResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    db: AsyncSession = Depends(get_db)
):
    """Register a new user"""
    # Check if email exists
    existing = await db.execute(select(User).where(User.email == user_data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Check if username exists
    existing = await db.execute(select(User).where(User.username == user_data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )
    
    # Check public registration setting
    registration_setting = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "public_registration")
    )
    setting = registration_setting.scalar_one_or_none()
    
    # Default to False (Private Beta) unless explicitly enabled
    login_enabled = False
    if setting and setting.value and setting.value.lower() == "true":
        login_enabled = True
    
    # Create user
    user = User(
        email=user_data.email,
        username=user_data.username,
        password_hash=hash_password(user_data.password),
        login_enabled=login_enabled
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    # If registrations are closed (private beta), return a friendly message
    if not login_enabled:
        return RegistrationResponse(
            message=f"To get free access, please message WrobelXXL on Discord: https://discord.gg/D9tgwpb65e",
            user=None
        )

    # If login is enabled, return the created user
    return RegistrationResponse(
        message="Account created",
        user=user
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    """Login and get access token"""
    user = await authenticate_user(db, credentials.email, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated"
        )
    
    if not user.login_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="To get free access, please message WrobelXXL on Discord: https://discord.gg/D9tgwpb65e"
        )
    
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """Refresh access token using refresh token"""
    user_id = verify_token(request.refresh_token, token_type="refresh")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )
    
    access_token = create_access_token(user_id)
    new_refresh_token = create_refresh_token(user_id)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user info"""
    return current_user


# ========== Profile Management ==========

@router.patch("/profile", response_model=UserResponse)
async def update_profile(
    profile_data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user profile (username)"""
    # Check if username is already taken by another user
    if profile_data.username != current_user.username:
        existing = await db.execute(
            select(User).where(User.username == profile_data.username)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )
    
    # Update username
    current_user.username = profile_data.username
    await db.commit()
    await db.refresh(current_user)
    
    return current_user


@router.post("/avatar", response_model=UserResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload user avatar image"""
    # Validate file type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Allowed: JPEG, PNG, GIF, WebP"
        )
    
    # Read file and check size
    content = await file.read()
    if len(content) > MAX_AVATAR_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size: 5MB"
        )
    
    # Generate unique filename
    file_ext = file.filename.split(".")[-1] if file.filename else "png"
    filename = f"avatars/{current_user.id}_{uuid.uuid4().hex[:8]}.{file_ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    
    # Ensure avatars directory exists
    os.makedirs(os.path.join(UPLOAD_DIR, "avatars"), exist_ok=True)
    
    # Delete old avatar if exists
    if current_user.avatar_url:
        old_path = os.path.join(UPLOAD_DIR, current_user.avatar_url.lstrip("/uploads/"))
        if os.path.exists(old_path):
            os.remove(old_path)
    
    # Save new file
    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)
    
    # Update user avatar URL
    current_user.avatar_url = f"/uploads/{filename}"
    await db.commit()
    await db.refresh(current_user)
    
    return current_user


@router.delete("/avatar", response_model=UserResponse)
async def delete_avatar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete user avatar"""
    if not current_user.avatar_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No avatar to delete"
        )
    
    # Delete file from disk
    filepath = os.path.join(UPLOAD_DIR, current_user.avatar_url.lstrip("/uploads/"))
    if os.path.exists(filepath):
        os.remove(filepath)
    
    # Clear avatar URL
    current_user.avatar_url = None
    await db.commit()
    await db.refresh(current_user)
    
    return current_user


# ========== API Keys ==========

@router.post("/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_data: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new API key (max 5 per user)"""
    # Check limit
    existing = await db.execute(
        select(ApiKey).where(ApiKey.user_id == current_user.id)
    )
    if len(existing.scalars().all()) >= 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum of 5 API keys reached"
        )
    
    full_key, key_hash, key_prefix = generate_api_key()
    
    expires_at = None
    if key_data.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=key_data.expires_in_days)
    
    api_key = ApiKey(
        user_id=current_user.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=key_data.name,
        allowed_host=key_data.allowed_host,
        expires_at=expires_at
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    
    return ApiKeyCreated(
        id=api_key.id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        allowed_host=api_key.allowed_host,
        is_active=api_key.is_active,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
        api_key=full_key  # Only returned once!
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all API keys for current user"""
    result = await db.execute(
        select(ApiKey).where(ApiKey.user_id == current_user.id)
    )
    return result.scalars().all()


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete an API key"""
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.id == key_id)
        .where(ApiKey.user_id == current_user.id)
    )
    api_key = result.scalar_one_or_none()
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    await db.delete(api_key)
    await db.commit()


# ========== Account Deletion ==========

@router.delete("/account", response_model=AccountDeleteResponse)
async def schedule_account_deletion(
    data: AccountDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Schedule account deletion in 30 days. User must confirm with password.
    
    All user data (API keys, generations, public gallery entries) will be deleted.
    The user can revoke within 30 days via DELETE /account/cancel.
    """
    # Verify password
    if not verify_password(data.password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Incorrect password"
        )

    # If already scheduled, just return the existing date
    if current_user.deletion_scheduled_at:
        return AccountDeleteResponse(
            message="Account deletion already scheduled",
            deletion_scheduled_at=current_user.deletion_scheduled_at
        )

    deletion_at = datetime.utcnow() + timedelta(days=30)
    current_user.deletion_scheduled_at = deletion_at
    await db.commit()
    await db.refresh(current_user)

    return AccountDeleteResponse(
        message=(
            "Your account and all associated data (API keys, generated images, public gallery entries) "
            "will be permanently deleted in 30 days. You can cancel this any time before then."
        ),
        deletion_scheduled_at=deletion_at
    )


@router.post("/account/cancel-deletion", response_model=UserResponse)
async def cancel_account_deletion(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel a scheduled account deletion."""
    if not current_user.deletion_scheduled_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No account deletion is scheduled"
        )

    current_user.deletion_scheduled_at = None
    await db.commit()
    await db.refresh(current_user)
    return current_user


# ========== Email Update ==========

@router.patch("/email", response_model=UserResponse)
async def update_email(
    data: EmailUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user email address. Requires current password for verification."""
    # Verify current password
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Incorrect password"
        )

    # Check if new email already in use by another account
    if data.email != current_user.email:
        existing = await db.execute(select(User).where(User.email == data.email))
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use"
            )

    current_user.email = data.email
    await db.commit()
    await db.refresh(current_user)
    return current_user


# ========== Email Verification (OTP) ==========

@router.post("/send-verification", response_model=SendVerificationEmailResponse)
async def send_verification(
    current_user: User = Depends(get_current_user),
):
    """Send a 6-digit verification OTP to the user's current email address.
    
    Rate-limited via OTP TTL: if an unexpired code already exists the remaining
    seconds are returned without re-sending.
    """
    if current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already verified"
        )

    # Check if a code was already sent recently (avoid spam)
    remaining = await otp_ttl_remaining(current_user.id)
    if remaining > 0:
        return SendVerificationEmailResponse(
            message="A verification code was already sent. Please check your inbox.",
            expires_in_seconds=remaining,
        )

    code = generate_otp()
    await store_otp(current_user.id, code)

    try:
        await send_verification_email(current_user.email, current_user.username, code)
    except Exception as exc:
        # Roll back stored OTP so user can retry immediately
        from src.app.redis_client import redis_client
        await redis_client.delete(f"pixelkid:otp:{current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to send email: {exc}"
        )

    return SendVerificationEmailResponse(
        message="Verification code sent. Please check your inbox.",
        expires_in_seconds=OTP_TTL_SECONDS,
    )


@router.post("/verify-email", response_model=UserResponse)
async def verify_email(
    data: VerifyEmailRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify the user's email with the 6-digit OTP."""
    if current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already verified"
        )

    valid = await verify_otp(current_user.id, data.code)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code"
        )

    current_user.is_verified = True
    await db.commit()
    await db.refresh(current_user)
    return current_user
