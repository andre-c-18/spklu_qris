import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database import engine, SessionLocal
import models
from routers import kiosk, admin

models.Base.metadata.create_all(bind=engine)

def get_wib_time():
    return datetime.now(ZoneInfo("Asia/Jakarta")).replace(tzinfo=None)

async def check_expired_transactions():
    while True:
        await asyncio.sleep(60) 
        
        db = SessionLocal()
        try:
            expiration_time = get_wib_time() - timedelta(minutes=5)

            expired_trxs = db.query(models.Transaction).filter(
                models.Transaction.status == models.TransactionStatus.UNPAID,
                models.Transaction.updated_at < expiration_time
            ).all()

            for trx in expired_trxs:
                trx.status = models.TransactionStatus.EXPIRED
            
            if expired_trxs:
                db.commit()
                print(f"[{get_wib_time()}] Membatalkan {len(expired_trxs)} transaksi kadaluarsa.")
                
        except Exception as e:
            print(f"Error pada Background Task: {repr(e)}") 
        finally:
            db.close()

# ==========================================
# LIFESPAN APP (STARTUP & SHUTDOWN)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dijalankan saat server Uvicorn mulai
    print("Memulai Background Task Pembersihan Transaksi...")
    task = asyncio.create_task(check_expired_transactions())
    
    yield # Mengizinkan FastAPI berjalan normal
    
    # Dijalankan saat server Uvicorn dimatikan (Ctrl+C)
    print("Mematikan Background Task...")
    task.cancel()

# ==========================================
# INISIALISASI FASTAPI
# ==========================================
app = FastAPI(
    title="SPKLU Payment Gateway", 
    description="API untuk Kiosk dan Admin SPKLU",
    lifespan=lifespan # Daftarkan lifespan di sini
)

# Mount folder static
app.mount("/static", StaticFiles(directory="static"), name="static")

# Daftarkan router
app.include_router(kiosk.router)
app.include_router(admin.router)