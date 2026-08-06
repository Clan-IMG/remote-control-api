import os
import uuid
import httpx
from decimal import Decimal
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.pay.models import Payment, PollerHeartbeat

router = APIRouter(prefix="/v1/pay")

CLAIM_EXPIRY_MINUTES = 5

# The Fabric mod polls /v1/pay/pending every 5 s while online — if we haven't
# seen a poll in this long, the payout bot is considered offline.
POLLER_ONLINE_THRESHOLD_SECONDS = 15


class PayRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    amount: Decimal = Field(..., gt=0)
    # id of the team_payout_requests row in api.clan-img.net, so a later failure
    # (e.g. player offline) can be reported back to revert that payout.
    external_id: str | None = None


class PayFailRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=255)


async def _is_poller_online(db: AsyncSession) -> bool:
    result = await db.execute(select(PollerHeartbeat).where(PollerHeartbeat.id == 1))
    heartbeat = result.scalar_one_or_none()
    if not heartbeat:
        return False
    return (datetime.utcnow() - heartbeat.last_seen_at) <= timedelta(seconds=POLLER_ONLINE_THRESHOLD_SECONDS)


@router.post("/")
async def create_payment(data: PayRequest, db: AsyncSession = Depends(get_db)):
    if not await _is_poller_online(db):
        raise HTTPException(
            status_code=503,
            detail="Payout-Bot ist nicht online (Minecraft-Mod nicht verbunden). Zahlung abgelehnt.",
        )

    payment = Payment(
        id=str(uuid.uuid4()),
        name=data.name,
        amount=data.amount,
        status="pending",
        external_id=data.external_id,
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
    # Every poll is a heartbeat — proves the payout bot is currently online.
    now = datetime.utcnow()
    result = await db.execute(select(PollerHeartbeat).where(PollerHeartbeat.id == 1))
    heartbeat = result.scalar_one_or_none()
    if heartbeat:
        heartbeat.last_seen_at = now
    else:
        db.add(PollerHeartbeat(id=1, last_seen_at=now))
    await db.commit()

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


@router.post("/{payment_id}/fail")
async def mark_failed(payment_id: str, data: PayFailRequest, db: AsyncSession = Depends(get_db)):
    """Mod reports that the /pay command failed (e.g. target player not online) —
    reverts the corresponding payout request in api.clan-img.net so the balance is refunded."""
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment.status = "failed"
    payment.fail_reason = data.reason
    await db.commit()

    if payment.external_id:
        clanimg_url = os.getenv("CLANIMG_API_URL", "").rstrip("/")
        clanimg_token = os.getenv("CLANIMG_API_TOKEN", "")
        if clanimg_url:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.patch(
                        f"{clanimg_url}/team-space/payout-requests/{payment.external_id}",
                        json={
                            "status": "rejected",
                            "reject_reason": data.reason,
                            "handled_by_discord_id": "system",
                            "handled_by_name": "Remote-Control-API",
                        },
                        headers={"X-API-Token": clanimg_token} if clanimg_token else {},
                    )
            except Exception:
                pass

    return {"ok": True}
