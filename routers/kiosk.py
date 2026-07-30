import datetime
from bca_helper import bca_helper
from database import get_db
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
import models
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/kiosk", tags=["Kiosk Terminal"])
templates = Jinja2Templates(directory="templates")

# ==========================================
# PYDANTIC SCHEMAS
# ==========================================
class VerifyNRPRequest(BaseModel):
    nrp: str


class PostpaidStartRequest(BaseModel):
    nrp: str


class PostpaidStopRequest(BaseModel):
    transaction_code: str
    kwh_used: float


@router.get("/")
async def kiosk_home(request: Request):
    """Menampilkan halaman utama UI Terminal Kiosk"""
    return templates.TemplateResponse("kiosk/index.html", {"request": request})

# ==========================================
# 1. VERIFY NRP (Cek tabel user_pending)
# ==========================================
@router.post("/verify-nrp")
async def verify_nrp(req: VerifyNRPRequest, db: Session = Depends(get_db)):
    """
    Mengecek apakah NRP terdaftar di user_pending dengan status has_unpaid_bill == True.
    """
    pending_user = (
        db.query(models.UserPending)
        .filter(models.UserPending.nrp == req.nrp)
        .first()
    )

    # TAHAN HANYA JIKA ADA RECORD DAN HAS_UNPAID_BILL == TRUE
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

    # TIDAK ADA TUNGGAKAN -> LOLOSKAN
    return {
        "status": "SUCCESS",
        "message": "Lolos pengecekan, silakan lanjutkan.",
        "nrp": req.nrp,
        "name": f"Karyawan ({req.nrp})",
    }


# ==========================================
# 2. POSTPAID START (Set Flag in user_pending)
# ==========================================
@router.post("/postpaid/start")
async def postpaid_start(
    req: PostpaidStartRequest, db: Session = Depends(get_db)
):
    trx_code = f"TRX-POST-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Cari atau buat record di tabel user_pending
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

    # Buat Transaksi Baru
    new_trx = models.Transaction(
        id=trx_code,
        nrp=req.nrp,
        flow_type="POSTPAID",
        kwh_amount=0.0,
        price=0.0,
        status="CHARGING",
    )
    db.add(new_trx)
    db.commit()

    # TODO: Panggil PLC Helper untuk Nyalakan Relay (snap7)

    return {"transaction_code": trx_code, "status": "CHARGING"}


# ==========================================
# 3. POSTPAID STOP (Generate QRIS Tagihan)
# ==========================================
@router.post("/postpaid/stop")
async def postpaid_stop(
    req: PostpaidStopRequest, db: Session = Depends(get_db)
):
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

    PRICE_PER_KWH = 1500.0
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
            status_code=500, detail=f"Gagal generate QRIS: {str(e)}"
        )


# ==========================================
# 4. AJAX POLLING INQUIRY (Clear Flag saat Lunas)
# ==========================================
@router.get("/check-status/{transaction_code}")
async def check_qris_status_polling(
    transaction_code: str, db: Session = Depends(get_db)
):
    trx = (
        db.query(models.Transaction)
        .filter(models.Transaction.id == transaction_code)
        .first()
    )

    if not trx:
        raise HTTPException(
            status_code=404, detail="Transaksi tidak ditemukan."
        )

    if trx.status == "PAID":
        return {"status": "PAID", "message": "Pembayaran lunas!"}

    if trx.status in ["PENDING", "UNPAID"]:
        bca_res = bca_helper.check_qris_status(partner_ref_no=transaction_code)
        bca_status = bca_res.get("latestTransactionStatus")

        if bca_status == "00":  # LUNAS
            trx.status = "PAID"

            # UNFLAG UNPAID BILL
            pending_user = (
                db.query(models.UserPending)
                .filter(models.UserPending.nrp == trx.nrp)
                .first()
            )
            if pending_user:
                pending_user.has_unpaid_bill = False

            db.commit()
            return {
                "status": "PAID",
                "message": "Pembayaran Berhasil Dikonfirmasi!",
            }

        elif bca_status == "02":  # EXPIRED
            trx.status = "EXPIRED"
            db.commit()
            return {"status": "EXPIRED", "message": "Waktu pembayaran expired."}

    return {"status": trx.status, "message": "Menunggu pembayaran..."}