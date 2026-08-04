import uuid
from sqlalchemy import Column, String, Numeric, Enum, DateTime, func
from app.database import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    status = Column(Enum("pending", "done"), nullable=False, default="pending")
    created_at = Column(DateTime, server_default=func.now())
