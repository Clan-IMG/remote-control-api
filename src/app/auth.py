import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional
import jwt
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.app.models import User, ApiKey
from src.app.config import JWT_SECRET, API_KEY_PREFIX

# JWT Settings
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    """Hash a password using bcrypt directly"""
    # Truncate password to 72 bytes (bcrypt limit)
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    try:
        password_bytes = plain_password.encode('utf-8')[:72]
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.
    Returns: (full_key, key_hash, key_prefix)
    """
    random_bytes = secrets.token_bytes(32)
    key_body = secrets.token_urlsafe(32)
    full_key = f"{API_KEY_PREFIX}{key_body}"
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    key_prefix = f"{API_KEY_PREFIX}{key_body[:8]}..."
    return full_key, key_hash, key_prefix


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage/lookup"""
    return hashlib.sha256(api_key.encode()).hexdigest()


def create_access_token(user_id: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": user_id,
        "exp": expire,
        "type": "access"
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "exp": expire,
        "type": "refresh"
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str, token_type: str = "access") -> Optional[str]:
    """Verify a JWT token and return the user_id if valid"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != token_type:
            return None
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_api_key(db: AsyncSession, api_key: str) -> Optional[User]:
    """Get user by API key"""
    key_hash = hash_api_key(api_key)
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.key_hash == key_hash)
        .where(ApiKey.is_active == True)
    )
    api_key_obj = result.scalar_one_or_none()
    
    if not api_key_obj:
        return None
    
    # Check expiration
    if api_key_obj.expires_at and api_key_obj.expires_at < datetime.utcnow():
        return None
    
    # Update last used
    api_key_obj.last_used_at = datetime.utcnow()
    await db.commit()
    
    return await get_user_by_id(db, api_key_obj.user_id)


async def authenticate_user(db: AsyncSession, email: str, password: str) -> Optional[User]:
    user = await get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
