import datetime
from database import Base
from sqlalchemy import DECIMAL, Boolean, Column, DateTime, Integer, String


class UserPending(Base):
    """
    Tabel user_pending: Mencatat NRP yang memiliki tunggakan (has_unpaid_bill).
    """

    __tablename__ = "user_pending"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    nrp = Column(String(20), unique=True, index=True, nullable=False)
    has_unpaid_bill = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )


class Transaction(Base):
    """
    Tabel transactions: Menyimpan riwayat charging & tagihan QRIS BCA.
    """

    __tablename__ = "transactions"

    id = Column(String(50), primary_key=True, index=True)  # TRX-Code
    nrp = Column(String(50), nullable=False)
    flow_type = Column(String(10), nullable=False, default="POSTPAID")
    kwh_amount = Column(DECIMAL(10, 2), default=0.00)
    price = Column(DECIMAL(10, 2), default=0.00)
    qris_string = Column(String(500), nullable=True)
    status = Column(String(20), default="PENDING")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )