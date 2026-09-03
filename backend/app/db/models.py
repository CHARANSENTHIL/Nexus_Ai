import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, BigInteger, Float, JSON
from app.db.session import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    action_type = Column(String(100), nullable=False)
    details = Column(JSON, nullable=True)
    outcome = Column(String(50), nullable=False)  # e.g. APPROVED, REJECTED, EXECUTED, FAILED

class SystemStateHistory(Base):
    __tablename__ = "system_state_history"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    cpu_percent = Column(Float, nullable=False)
    ram_percent = Column(Float, nullable=False)
    disk_percent = Column(Float, nullable=False)
    disk_free_gb = Column(Float, nullable=False)
    raw_state = Column(JSON, nullable=True)
