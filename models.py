import enum
import uuid
import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import Column, String, Float, DateTime, Enum
from database import Base

def get_wib_time():
    return datetime.datetime.now(ZoneInfo("Asia/Jakarta")).replace(tzinfo=None)

class TransactionStatus(str, enum.Enum):
    CHARGING = "CHARGING"
    UNPAID = "UNPAID"
    PAID = "PAID"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    nrp = Column(String(50), nullable=False)
    kwh_amount = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    qris_string = Column(String(500), nullable=True)
    status = Column(Enum(TransactionStatus), default=TransactionStatus.CHARGING)
    
    created_at = Column(DateTime, default=get_wib_time)
    updated_at = Column(DateTime, default=get_wib_time, onupdate=get_wib_time)