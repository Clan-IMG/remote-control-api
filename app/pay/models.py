import uuid
from sqlalchemy import Column, String, Numeric, Enum, DateTime, Integer, Boolean, func
from app.database import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    status = Column(Enum("pending", "done", "failed"), nullable=False, default="pending")
    # id of the corresponding team_payout_requests row in api.clan-img.net, used to report
    # back a failure (e.g. target player offline) so the payout can be reverted there.
    external_id = Column(String(64), nullable=True)
    fail_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    claimed_at = Column(DateTime, nullable=True, default=None)
    # False until _notify_clanimg's callback (which flips the payout to paid/rejected and, for
    # 'paid', creates the Buchhalter entry) has actually succeeded — a background retry loop
    # keeps retrying rows stuck at False so a transient network failure can't strand a payout.
    notified = Column(Boolean, nullable=False, default=False)


class PollerHeartbeat(Base):
    """Single-row table updated every time the Fabric mod polls for pending payments.

    Used to determine whether the payout bot is currently online before accepting new payments.
    """

    __tablename__ = "poller_heartbeat"

    id = Column(Integer, primary_key=True, default=1)
    last_seen_at = Column(DateTime, nullable=False, server_default=func.now())
