import uuid
from decimal import Decimal
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.pay.models import Payment

router = APIRouter(prefix="/v1/pay")

CLAIM_EXPIRY_MINUTES = 5


class PayRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    amount: Decimal = Field(..., gt=0)


@router.post("/")
async def create_payment(data: PayRequest, db: AsyncSession = Depends(get_db)):
    payment = Payment(
        id=str(uuid.uuid4()),
        name=data.name,
        amount=data.amount,
        status="pending",
    )
    db.add(payment)
    await db.commit()
    return {
        "id": payment.id,
        "name": payment.name,
        "amount": float(payment.amount),
        "status": payment.status,
    }


@router.get("/pending")
async def get_pending(db: AsyncSession = Depends(get_db)):
    expiry = datetime.utcnow() - timedelta(minutes=CLAIM_EXPIRY_MINUTES)
    result = await db.execute(
        select(Payment)
        .where(
            Payment.status == "pending",
            or_(Payment.claimed_at.is_(None), Payment.claimed_at < expiry)
        )
        .with_for_update()
    )
    payments = result.scalars().all()
    now = datetime.utcnow()
    for p in payments:
        p.claimed_at = now
    await db.commit()
    return [{"id": p.id, "name": p.name, "amount": float(p.amount)} for p in payments]


@router.post("/{payment_id}/done")
async def mark_done(payment_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment.status = "done"
    await db.commit()
    return {"ok": True}
