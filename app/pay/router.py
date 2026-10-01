import logging
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
logger = logging.getLogger(__name__)

CLAIM_EXPIRY_MINUTES = 5

# The Fabric mod polls /v1/pay/pending every 5 s while online — if we haven't
# seen a poll in this long, the payout bot is considered offline.
POLLER_ONLINE_THRESHOLD_SECONDS = 15

# The old mod reported "no reply within 3 s" as a failure ("Keine Bestätigung vom Server erhalten
# (Zeitüberschreitung).") although the /pay may well have gone through. Refunding that would free
# the balance for money that is already gone, so it's parked as 'unconfirmed' instead. Matched
# without the umlaut so a charset mix-up on the way can't let it slip through. The current mod
# never reports that case as a failure.
LEGACY_UNKNOWN_OUTCOME_LIKE = "Keine Best%tigung vom Server erhalten%"

IMMOMARKT_EXTERNAL_ID_PREFIX = "immomarkt-"


class PayRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    amount: Decimal = Field(..., gt=0)
    # id of the team_payout_requests row in api.clan-img.net, so a later failure
    # (e.g. player offline) can be reported back to revert that payout.
    external_id: str | None = None


class PayFailRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=255)


class PayStartRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=64)


def _is_legacy_unknown_outcome(reason: str) -> bool:
    return reason.startswith("Keine Best") and "tigung vom Server erhalten" in reason


def _payment_json(payment: Payment) -> dict:
    return {
        "id": payment.id,
        "name": payment.name,
        "amount": float(payment.amount),
        "status": payment.status,
    }


async def _is_poller_online(db: AsyncSession) -> bool:
    result = await db.execute(select(PollerHeartbeat).where(PollerHeartbeat.id == 1))
    heartbeat = result.scalar_one_or_none()
    if not heartbeat:
        return False
    return (datetime.utcnow() - heartbeat.last_seen_at) <= timedelta(seconds=POLLER_ONLINE_THRESHOLD_SECONDS)


async def _lock_payment(db: AsyncSession, payment_id: str) -> Payment:
    """Row-locks the payment for the rest of the transaction so concurrent calls for the same
    payment (mod retry, notify loop) are serialized and every status transition is checked
    against the current state."""
    result = await db.execute(select(Payment).where(Payment.id == payment_id).with_for_update())
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.get("/online")
async def get_poller_online(db: AsyncSession = Depends(get_db)):
    """Public status check for external watchdogs (e.g. rc-payout-watchdog) — reports whether
    the Fabric mod is currently polling, based on the same heartbeat used to gate /v1/pay/."""
    return {"online": await _is_poller_online(db)}


@router.post("/")
async def create_payment(data: PayRequest, db: AsyncSession = Depends(get_db)):
    # Idempotent per external_id: api.clan-img.net retries this call when it can't tell whether
    # the first one landed (e.g. a timeout after we already committed) - hand back the same
    # payment instead of queuing a second /pay for the same payout. Checked before the online
    # gate so such a retry can't be turned into a rejection while the payment is in fact queued.
    if data.external_id:
        result = await db.execute(select(Payment).where(Payment.external_id == data.external_id))
        existing = result.scalars().first()
        if existing:
            if existing.name != data.name or Decimal(existing.amount) != data.amount:
                raise HTTPException(
                    status_code=409,
                    detail="external_id ist bereits mit anderem Namen/Betrag eingereiht.",
                )
            return _payment_json(existing)

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
    return _payment_json(payment)


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

    # Only 'pending' is ever handed out - a payment the mod has /start-ed is never re-delivered.
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


@router.post("/{payment_id}/start")
async def start_payment(payment_id: str, data: PayStartRequest, db: AsyncSession = Depends(get_db)):
    """At-most-once gate: the mod calls this right before sending /pay and only sends it on a 2xx.
    A payment can be started exactly once - a repeat with the same token (the mod retrying after
    a lost response) is fine, anything else gets a 409. Once started it's never handed out by
    /pending again, so even a mod that lost its local journal, or a second bot instance, can
    never pay the same payout twice."""
    payment = await _lock_payment(db, payment_id)
    if payment.status == "pending":
        payment.status = "executing"
        payment.executor_token = data.token
        payment.started_at = datetime.utcnow()
        await db.commit()
        return {"ok": True}
    if payment.status == "executing" and payment.executor_token == data.token:
        return {"ok": True, "unchanged": True}
    raise HTTPException(status_code=409, detail=f"Payment is already {payment.status}")


def _callback_request(external_id: str, status: str, reject_reason: str | None) -> tuple[str, dict]:
    """Immomarkt payouts are queued with external_id "immomarkt-<id>" and confirmed on their own
    route with their own body shape - sending them to the team-space route 422'd forever, so they
    were never booked as paid nor refunded."""
    if external_id.startswith(IMMOMARKT_EXTERNAL_ID_PREFIX):
        return (
            f"/team-space/immomarkt/payout-requests/{external_id[len(IMMOMARKT_EXTERNAL_ID_PREFIX):]}",
            {"status": status, "rejectReason": reject_reason, "handledByName": "Remote-Control-API"},
        )
    return (
        f"/team-space/payout-requests/{external_id}",
        {
            "status": status,
            "reject_reason": reject_reason,
            "handled_by_discord_id": "system",
            "handled_by_name": "Remote-Control-API",
        },
    )


async def _notify_clanimg(external_id: str, status: str, reject_reason: str | None) -> bool:
    """Reports the final /pay outcome back to api.clan-img.net so the payout request
    (created optimistically as 'processing') is resolved to its real status — this is also
    what triggers the automatic Buchhalter entry on the 'paid' transition. Returns whether the
    callback actually succeeded so the caller can retry later instead of silently giving up."""
    clanimg_url = os.getenv("CLANIMG_API_URL", "").rstrip("/")
    clanimg_token = os.getenv("CLANIMG_API_TOKEN", "")
    if not clanimg_url:
        return False
    path, body = _callback_request(external_id, status, reject_reason)
    try:
        # Generous timeout — the target domain can be slow to respond on a cold connection,
        # and a spurious timeout here just means one more silently-missed payout confirmation.
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.patch(
                f"{clanimg_url}{path}",
                json=body,
                headers={"X-API-Token": clanimg_token} if clanimg_token else {},
            )
            if resp.status_code >= 400:
                logger.warning("_notify_clanimg failed for external_id=%s status=%s: HTTP %s %s", external_id, status, resp.status_code, resp.text)
                return False
            return True
    except Exception as exc:
        logger.warning("_notify_clanimg failed for external_id=%s status=%s: %r", external_id, status, exc)
        return False


@router.post("/{payment_id}/done")
async def mark_done(payment_id: str, db: AsyncSession = Depends(get_db)):
    """Mod confirms the /pay command actually succeeded (saw the server's success chat message) —
    resolves the corresponding payout request in api.clan-img.net to 'paid'. Also the manual
    resolution of an 'unconfirmed' payment after checking in-game that it did arrive."""
    payment = await _lock_payment(db, payment_id)
    if payment.status == "done":
        # The mod retries until it gets a 2xx - a repeat must not notify (and book) a second
        # time; a notify that hasn't landed yet is picked up by retry_unnotified_payments.
        return {"ok": True, "unchanged": True}
    if payment.status not in ("pending", "executing", "unconfirmed"):
        raise HTTPException(status_code=409, detail=f"Payment is already {payment.status}")
    payment.status = "done"
    await db.commit()

    if payment.external_id:
        payment.notified = await _notify_clanimg(payment.external_id, "paid", None)
        await db.commit()

    return {"ok": True}


@router.post("/{payment_id}/fail")
async def mark_failed(payment_id: str, data: PayFailRequest, db: AsyncSession = Depends(get_db)):
    """Mod reports that the /pay command failed (e.g. target player not online) —
    reverts the corresponding payout request in api.clan-img.net so the balance is refunded.
    Also the manual resolution of an 'unconfirmed' payment that did not arrive."""
    payment = await _lock_payment(db, payment_id)
    if payment.status == "failed":
        return {"ok": True, "unchanged": True}
    if payment.status not in ("pending", "executing", "unconfirmed"):
        raise HTTPException(status_code=409, detail=f"Payment is already {payment.status}")

    if payment.status != "unconfirmed" and _is_legacy_unknown_outcome(data.reason):
        # No reply is not a failure - keep the balance locked until someone checked in-game
        payment.status = "unconfirmed"
        payment.fail_reason = data.reason
        await db.commit()
        logger.warning(
            "Payment %s (%s, %s$) has an unknown outcome - parked as 'unconfirmed', resolve with /done or /fail after checking in-game",
            payment.id, payment.name, payment.amount,
        )
        return {"ok": True, "status": "unconfirmed"}

    payment.status = "failed"
    payment.fail_reason = data.reason
    await db.commit()

    if payment.external_id:
        payment.notified = await _notify_clanimg(payment.external_id, "rejected", data.reason)
        await db.commit()

    return {"ok": True}


async def retry_unnotified_payments(db: AsyncSession) -> None:
    """Safety net for the background loop in api.py: retries the api.clan-img.net callback for any
    resolved payment that never got a successful notify (e.g. api.clan-img.net was briefly down),
    so a transient failure can't permanently strand a payout in 'processing' with no Buchhalter entry."""
    result = await db.execute(
        select(Payment).where(Payment.status.in_(("done", "failed")), Payment.notified.is_(False), Payment.external_id.isnot(None))
    )
    for payment in result.scalars().all():
        status = "paid" if payment.status == "done" else "rejected"
        reason = payment.fail_reason if payment.status == "failed" else None
        if await _notify_clanimg(payment.external_id, status, reason):
            payment.notified = True
    await db.commit()
