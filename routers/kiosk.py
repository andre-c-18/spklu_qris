from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

import models
import bca_helper
from database import get_db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# ==========================================
# PYDANTIC SCHEMAS
# ==========================================
class StartChargingRequest(BaseModel):
    nrp: str

class StopChargingRequest(BaseModel):
    trx_id: str
    kwh_used: float

# ==========================================
# ENDPOINTS
# ==========================================
@router.get("/")
async def kiosk_home(request: Request):
    return templates.TemplateResponse("kiosk/index.html", {"request": request})

@router.post("/api/kiosk/start")
async def start_charging(req: StartChargingRequest, db: Session = Depends(get_db)):
    new_trx = models.Transaction(
        nrp=req.nrp,
        kwh_amount=0.0, 
        price=0.0,
        status=models.TransactionStatus.CHARGING
    )
    db.add(new_trx)
    db.commit()
    db.refresh(new_trx)
    
    # TODO: spklu_controller.start_charging() -> Kunci kabel (Auto-Lock) & Nyalakan Relay
    return {"trx_id": new_trx.id, "status": new_trx.status}

@router.post("/api/kiosk/stop")
async def stop_charging(req: StopChargingRequest, db: Session = Depends(get_db)):
    trx = db.query(models.Transaction).filter(models.Transaction.id == req.trx_id).first()
    if not trx:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")

    # TODO: Matikan relay SPKLU di sini!
    
    PRICE_PER_KWH = 1200
    trx.kwh_amount = req.kwh_used
    trx.price = req.kwh_used * PRICE_PER_KWH
    
    try:
        qris_string = bca_helper.generate_qris(trx.price, trx.id)
        trx.qris_string = qris_string
        trx.status = models.TransactionStatus.UNPAID
        db.commit()
        
        return {
            "trx_id": trx.id, 
            "qris_string": qris_string,
            "kwh_amount": trx.kwh_amount,
            "price": trx.price
        }
    except Exception as e:
        trx.status = models.TransactionStatus.FAILED
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/kiosk/status/{trx_id}")
async def check_status(trx_id: str, db: Session = Depends(get_db)):
    trx = db.query(models.Transaction).filter(models.Transaction.id == trx_id).first()
    if not trx:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": trx.status}

# Rangka Webhook BCA yang sebenarnya
@router.post("/api/bca-webhook")
async def bca_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    headers = request.headers
    # bca_helper.verify_signature(body, headers)
    
    trx_id = body.get("partnerReferenceNo")
    
    trx = db.query(models.Transaction).filter(models.Transaction.id == trx_id).first()
    # UBAH PENDING MENJADI UNPAID DI SINI
    if trx and trx.status == models.TransactionStatus.UNPAID:
        trx.status = models.TransactionStatus.PAID
        db.commit()
        
    return {"responseCode": "2002500", "responseMessage": "Success"}

@router.get("/api/dummy-pay/{trx_id}")
async def dummy_bca_webhook(trx_id: str, db: Session = Depends(get_db)):
    """
    Tiruan Webhook BCA. 
    """
    trx = db.query(models.Transaction).filter(models.Transaction.id == trx_id).first()
    
    if not trx:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    
    if trx.status == models.TransactionStatus.PAID:
        return {"status": "info", "message": "Transaksi ini sudah dibayar sebelumnya."}

    # UBAH VALIDASI STATUS MENJADI UNPAID SEBELUM JADI PAID
    if trx.status != models.TransactionStatus.UNPAID:
        return {"status": "error", "message": f"Status transaksi tidak valid untuk dibayar. Status saat ini: {trx.status}"}

    trx.status = models.TransactionStatus.PAID
    db.commit()

    return {
        "status": "success", 
        "message": f"Simulasi sukses! Transaksi {trx_id} telah dibayar. Cek layar Kiosk Anda."
    }