from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List

from src.app.database import get_db
from src.app.models import User, SystemSetting
from src.app.schemas import UserResponse, SystemSettingResponse, SystemSettingUpdate, UserApprovalUpdate
from src.app.dependencies import get_current_admin

router = APIRouter(prefix="/v1/admin", tags=["Admin"])

@router.get("/users/pending", response_model=List[UserResponse])
async def get_pending_users(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Get all users waiting for approval"""
    result = await db.execute(select(User).where(User.login_enabled == False))
    return result.scalars().all()

@router.post("/users/approve")
async def approve_user(
    data: UserApprovalUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Approve or disapprove a user login"""
    user = await db.get(User, data.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.login_enabled = data.login_enabled
    await db.commit()
    return {"message": f"User login status updated to {data.login_enabled}"}

@router.get("/settings", response_model=List[SystemSettingResponse])
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Get all system settings"""
    result = await db.execute(select(SystemSetting))
    return result.scalars().all()

@router.put("/settings")
async def update_setting(
    data: SystemSettingUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Update a system setting"""
    setting = await db.get(SystemSetting, data.key)
    if not setting:
        # Create if not exists
        setting = SystemSetting(key=data.key, value=data.value)
        db.add(setting)
    else:
        setting.value = data.value
    
    await db.commit()
    await db.refresh(setting)
    return setting
