from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from bca_helper import bca_helper
from database import get_db

router = APIRouter(prefix="/api/kiosk", tags=["Kiosk Terminal"])
templates = Jinja2Templates(directory="templates")

# Helper Waktu WIB (Asia/Jakarta)
def get_wib_now():
    return datetime.now(ZoneInfo("Asia/Jakarta")).replace(tzinfo=None)

PRICE_PER_KWH = 1500.0  # Tarif SPKLU per kWh

# ==========================================
# PYDANTIC SCHEMAS (Request Body Validation)
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
# 1. VIEW ROUTE (Render UI Kiosk)
# ==========================================
@router.get("/")
async def kiosk_home(request: Request):
    """Menampilkan halaman utama UI Terminal Kiosk"""
    return templates.TemplateResponse("kiosk/index.html", {"request": request})


# ==========================================
# 2. VERIFY NRP (Cek Tabel user_pending)
# ==========================================
@router.post("/verify-nrp")
async def verify_nrp(req: VerifyNRPRequest, db: Session = Depends(get_db)):
    """Mengecek apakah NRP terdaftar di user_pending dengan has_unpaid_bill == True."""
    pending_user = (
        db.query(models.UserPending)
        .filter(models.UserPending.nrp == req.nrp)
        .first()
    )

    # Jika ada tunggakan dari sesi sebelumnya -> Tahan & Arahkan ke Recovery
    if pending_user and pending_user.has_unpaid_bill:
        unpaid_trx = (
            db.query(models.Transaction)
            .filter(
                models.Transaction.nrp == req.nrp,
                models.Transaction.status.in_(["PENDING", "UNPAID"]),
            )
            .order_by(models.Transaction.created_at.desc())
            .first()
        )

        return {
            "status": "UNPAID_BILL_FOUND",
            "message": "NRP Anda memiliki tagihan tertunggak dari sesi sebelumnya.",
            "nrp": req.nrp,
            "name": f"Karyawan ({req.nrp})",
            "unpaid_trx_code": unpaid_trx.id if unpaid_trx else None,
            "amount": float(unpaid_trx.price) if unpaid_trx else 0.0,
        }

    # Tidak ada tunggakan -> Loloskan
    return {
        "status": "SUCCESS",
        "message": "Lolos pengecekan, silakan lanjutkan.",
        "nrp": req.nrp,
        "name": f"Karyawan ({req.nrp})",
    }


# ==========================================
# 3. FLOW 1: PRE-PAID (Create QRIS di Awal)
# ==========================================
@router.post("/prepaid/create-qris")
async def prepaid_create_qris(
    req: PrepaidCreateRequest, db: Session = Depends(get_db)
):
    if req.amount < 1500:
        raise HTTPException(
            status_code=400, detail="Nominal pengisian minimal Rp 1.500"
        )

    trx_code = f"TRX-PRE-{get_wib_now().strftime('%Y%m%d%H%M%S')}"

    target_kwh = req.amount / PRICE_PER_KWH

    try:
        qris_res = bca_helper.generate_qris(price=req.amount, trx_id=trx_code)
        qr_content = qris_res.get("qrContent")

        # Simpan kwh_amount sebagai kuota target pengisian
        new_trx = models.Transaction(
            id=trx_code,
            nrp=req.nrp,
            flow_type="PREPAID",
            kwh_amount=target_kwh,  # Target kWh tersimpan di DB
            price=req.amount,
            qris_string=qr_content,
            status="PENDING",
        )
        db.add(new_trx)
        db.commit()

        return {
            "transaction_code": trx_code,
            "qr_content": qr_content,
            "amount": req.amount,
            "target_kwh": round(target_kwh, 2),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Gagal generate QRIS Prepaid: {str(e)}"
        )

# ==========================================
# 4. FLOW 2: POST-PAID START (Set Flag user_pending)
# ==========================================
@router.post("/postpaid/start")
async def postpaid_start(
    req: PostpaidStartRequest, db: Session = Depends(get_db)
):
    """Flow 2: Langsung mulai charging & tandai flag tunggakan di user_pending."""
    trx_code = f"TRX-POST-{get_wib_now().strftime('%Y%m%d%H%M%S')}"

    # Cari atau catat NRP di tabel user_pending
    pending_user = (
        db.query(models.UserPending)
        .filter(models.UserPending.nrp == req.nrp)
        .first()
    )

    if not pending_user:
        pending_user = models.UserPending(nrp=req.nrp, has_unpaid_bill=True)
        db.add(pending_user)
    else:
        pending_user.has_unpaid_bill = True

    # Buat Transaksi Sesi Charging
    new_trx = models.Transaction(
        id=trx_code,
        nrp=req.nrp,
        flow_type="POSTPAID",
        kwh_amount=0.00,
        price=0.00,
        status="CHARGING",
    )
    db.add(new_trx)
    db.commit()

    # TODO: Panggil PLC Helper untuk Nyalakan Relay (snap7)

    return {"transaction_code": trx_code, "status": "CHARGING"}


# ==========================================
# 5. FLOW 2: POST-PAID STOP (Generate QRIS Tagihan)
# ==========================================
@router.post("/postpaid/stop")
async def postpaid_stop(
    req: PostpaidStopRequest, db: Session = Depends(get_db)
):
    """Flow 2: Stop charging -> Hitung Tagihan Pemakaian -> Generate QRIS."""
    trx = (
        db.query(models.Transaction)
        .filter(models.Transaction.id == req.transaction_code)
        .first()
    )

    if not trx:
        raise HTTPException(
            status_code=404, detail="Transaksi tidak ditemukan"
        )

    # TODO: Panggil PLC Helper untuk Matikan Relay (snap7)

    total_price = req.kwh_used * PRICE_PER_KWH

    try:
        qris_res = bca_helper.generate_qris(price=total_price, trx_id=trx.id)
        qr_content = qris_res.get("qrContent")

        trx.kwh_amount = req.kwh_used
        trx.price = total_price
        trx.qris_string = qr_content
        trx.status = "UNPAID"
        db.commit()

        return {
            "transaction_code": trx.id,
            "qr_content": qr_content,
            "kwh_used": req.kwh_used,
            "total_price": total_price,
        }
    except Exception as e:
        trx.status = "FAILED"
        db.commit()
        raise HTTPException(
            status_code=500, detail=f"Gagal generate QRIS Postpaid: {str(e)}"
        )


# ==========================================
# 6. CORE AJAX POLLING: QRIS MPM INQUIRY
# ==========================================
@router.get("/check-status/{transaction_code}")
async def check_qris_status_polling(
    transaction_code: str, db: Session = Depends(get_db)
):
    """Endpoint ini dipanggil berulang kali oleh jQuery AJAX Polling tiap 3 detik."""
    trx = (
        db.query(models.Transaction)
        .filter(models.Transaction.id == transaction_code)
        .first()
    )

    if not trx:
        raise HTTPException(
            status_code=404, detail="Transaksi tidak ditemukan."
        )

    res_payload = {
        "status": trx.status,
        "qr_content": trx.qris_string,
        "price": float(trx.price),
        "kwh_amount": float(trx.kwh_amount),
    }

    if trx.status == "PAID":
        res_payload["message"] = "Pembayaran lunas!"
        return res_payload

    if trx.status in ["PENDING", "UNPAID"]:
        bca_res = bca_helper.check_qris_status(partner_ref_no=transaction_code)
        bca_status = bca_res.get("latestTransactionStatus")

        if bca_status == "00":  # LUNAS / PAID
            trx.status = "PAID"

            # Hapus Flag Unpaid Bill dari user_pending
            pending_user = (
                db.query(models.UserPending)
                .filter(models.UserPending.nrp == trx.nrp)
                .first()
            )
            if pending_user:
                pending_user.has_unpaid_bill = False

            db.commit()
            res_payload["status"] = "PAID"
            res_payload["message"] = "Pembayaran Berhasil Dikonfirmasi!"
            return res_payload

        elif bca_status == "02":  # EXPIRED
            trx.status = "EXPIRED"
            db.commit()
            res_payload["status"] = "EXPIRED"
            res_payload["message"] = "Waktu pembayaran expired."
            return res_payload

    res_payload["message"] = "Menunggu pembayaran..."
    return res_payload