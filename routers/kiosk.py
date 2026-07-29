import datetime
from typing import Optional
from bca_helper import bca_helper
from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
import models
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/kiosk", tags=["Kiosk Terminal"])
templates = Jinja2Templates(directory="templates")


# ==========================================
# PYDANTIC SCHEMAS (Request Validation)
# ==========================================
class VerifyNRPRequest(BaseModel):
    nrp: str


class PrepaidCreateRequest(BaseModel):
    nrp: str
    amount: float


class PostpaidStartRequest(BaseModel):
    nrp: str


class PostpaidStopRequest(BaseModel):
    transaction_code: str
    kwh_used: float


# ==========================================
# 1. VIEW ROUTE (Render Template UI)
# ==========================================
@router.get("/")
async def kiosk_home(request: Request):
    """Menampilkan Tampilan Utama Terminal Kiosk"""
    return templates.TemplateResponse("kiosk/index.html", {"request": request})


# ==========================================
# 2. VALIDASI NRP & CEK TUNGGAKAN
# ==========================================
@router.post("/verify-nrp")
async def verify_nrp(req: VerifyNRPRequest, db: Session = Depends(get_db)):
    """Memeriksa keaktifan NRP & status tagihan tertunggak (Unpaid Bill)"""
    user = (
        db.query(models.UserNRP)
        .filter(models.UserNRP.nrp == req.nrp)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=404, detail="NRP tidak terdaftar di sistem."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=403, detail="Akses NRP Anda sedang dinonaktifkan."
        )

    # Cek apakah pengguna punya tagihan tertunggak dari Flow 2 sebelumnya
    if user.has_unpaid_bill:
        unpaid_trx = (
            db.query(models.Transaction)
            .filter(
                models.Transaction.nrp == req.nrp,
                models.Transaction.status.in_(["PENDING", "UNPAID"]),
            )
            .order_by(models.Transaction.id.desc())
            .first()
        )

        return {
            "status": "UNPAID_BILL_FOUND",
            "message": "Anda memiliki tagihan tertunggak dari pengisian sebelumnya.",
            "nrp": user.nrp,
            "name": user.name,
            "unpaid_trx_code": unpaid_trx.transaction_code
            if unpaid_trx
            else None,
            "amount": float(unpaid_trx.amount) if unpaid_trx else 0.0,
        }

    return {
        "status": "SUCCESS",
        "message": "NRP Valid",
        "nrp": user.nrp,
        "name": user.name,
    }


# ==========================================
# 3. FLOW 1: PRE-PAID (Bayar Dulu Baru Charging)
# ==========================================
@router.post("/prepaid/create-qris")
async def create_prepaid_qris(
    req: PrepaidCreateRequest, db: Session = Depends(get_db)
):
    """Flow 1: Generate QRIS BCA berdasarkan nominal input pengguna"""
    trx_code = f"TRX-PRE-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

    try:
        # Panggil helper BCA untuk generate Dynamic QRIS
        qris_res = bca_helper.generate_qris(
            price=req.amount, trx_id=trx_code
        )
        qr_content = qris_res.get("qrContent")

        # Simpan Transaksi ke DB dengan status PENDING
        new_trx = models.Transaction(
            transaction_code=trx_code,
            nrp=req.nrp,
            flow_type="PREPAID",
            amount=req.amount,
            qr_string=qr_content,
            status="PENDING",
        )
        db.add(new_trx)
        db.commit()

        return {
            "transaction_code": trx_code,
            "qr_content": qr_content,
            "amount": req.amount,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Gagal generate QRIS: {str(e)}"
        )


# ==========================================
# 4. FLOW 2: POST-PAID (Charging Dulu Baru Bayar)
# ==========================================
@router.post("/postpaid/start")
async def postpaid_start(
    req: PostpaidStartRequest, db: Session = Depends(get_db)
):
    """Flow 2: Langsung mulai charging tanpa bayar di awal"""
    trx_code = f"TRX-POST-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

    new_trx = models.Transaction(
        transaction_code=trx_code,
        nrp=req.nrp,
        flow_type="POSTPAID",
        amount=0.0,
        status="CHARGING",
    )
    db.add(new_trx)

    # Tandai pengguna sedang punya sesi berjalan
    user = (
        db.query(models.UserNRP)
        .filter(models.UserNRP.nrp == req.nrp)
        .first()
    )
    if user:
        user.has_unpaid_bill = True  # Flag terkunci sampai pembayaran selesai

    db.commit()

    # TODO: Panggil PLC Helper untuk kunci kabel & START Relay
    # plc_helper.start_charging()

    return {"transaction_code": trx_code, "status": "CHARGING"}


@router.post("/postpaid/stop")
async def postpaid_stop(
    req: PostpaidStopRequest, db: Session = Depends(get_db)
):
    """Flow 2: Stop charging -> Kalkulasi Biaya -> Generate QRIS"""
    trx = (
        db.query(models.Transaction)
        .filter(models.Transaction.transaction_code == req.transaction_code)
        .first()
    )
    if not trx:
        raise HTTPException(
            status_code=404, detail="Transaksi tidak ditemukan"
        )

    # TODO: Panggil PLC Helper untuk Stop Relay & Buka Kunci
    # plc_helper.stop_charging()

    # Hitung total tarif (misal Rp 1.500 / kWh)
    PRICE_PER_KWH = 1500.0
    total_price = req.kwh_used * PRICE_PER_KWH

    try:
        # Generate QRIS untuk tagihan pemakaian
        qris_res = bca_helper.generate_qris(
            price=total_price, trx_id=trx.transaction_code
        )
        qr_content = qris_res.get("qrContent")

        trx.amount = total_price
        trx.qr_string = qr_content
        trx.status = "UNPAID"
        db.commit()

        return {
            "transaction_code": trx.transaction_code,
            "qr_content": qr_content,
            "kwh_used": req.kwh_used,
            "total_price": total_price,
        }
    except Exception as e:
        trx.status = "FAILED"
        db.commit()
        raise HTTPException(
            status_code=500, detail=f"Gagal generate QRIS: {str(e)}"
        )


# ==========================================
# 5. CORE AJAX POLLING: QRIS MPM INQUIRY (CHECK STATUS)
# ==========================================
@router.get("/check-status/{transaction_code}")
async def check_qris_status_polling(
    transaction_code: str, db: Session = Depends(get_db)
):
    """Endpoint ini dipanggil berulang kali oleh jQuery AJAX Polling tiap 2-3 detik"""
    trx = (
        db.query(models.Transaction)
        .filter(models.Transaction.transaction_code == transaction_code)
        .first()
    )
    if not trx:
        raise HTTPException(
            status_code=404, detail="Transaksi tidak ditemukan."
        )

    # Jika transaksi di DB sudah PAID, langsung kembalikan status tanpa panggil API BCA lagi
    if trx.status == "PAID":
        return {"status": "PAID", "message": "Pembayaran lunas!"}

    # Jika transaksi masih PENDING / UNPAID, panggil API BCA: QRIS MPM Inquiry
    if trx.status in ["PENDING", "UNPAID"]:
        bca_res = bca_helper.check_qris_status(
            partner_ref_no=transaction_code
        )
        bca_status = bca_res.get("latestTransactionStatus")

        # Kode "00" dari BCA menandakan Pembayaran LUNAS (PAID)
        if bca_status == "00":
            trx.status = "PAID"
            trx.paid_at = datetime.datetime.utcnow()

            # Buka blokir Unpaid Bill pada NRP pengguna
            user = (
                db.query(models.UserNRP)
                .filter(models.UserNRP.nrp == trx.nrp)
                .first()
            )
            if user:
                user.has_unpaid_bill = False

            db.commit()

            # jika ini Flow 1 (Prepaid), baru picu PLC untuk nyalakan charging
            if trx.flow_type == "PREPAID":
                # plc_helper.start_charging()
                pass

            return {
                "status": "PAID",
                "message": "Pembayaran Berhasil Dikonfirmasi!",
            }

        # Kode "02" menandakan Expired / Failed
        elif bca_status == "02":
            trx.status = "EXPIRED"
            db.commit()
            return {"status": "EXPIRED", "message": "Waktu pembayaran expired."}

    return {"status": trx.status, "message": "Menunggu pembayaran..."}