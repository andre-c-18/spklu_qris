from datetime import datetime, timedelta
import io
from zoneinfo import ZoneInfo

from database import get_db
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
import models
import pandas as pd
from sqlalchemy.orm import Session


# Helper Waktu WIB (Asia/Jakarta)
def get_wib_time():
    return datetime.now(ZoneInfo("Asia/Jakarta")).replace(tzinfo=None)


router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])
templates = Jinja2Templates(directory="templates")


# ==========================================
# 1. VIEW ROUTE (Render Dashboard Admin)
# ==========================================
@router.get("")
@router.get("/")
async def admin_dashboard(request: Request):
    """Menampilkan halaman utama Dashboard Admin SPKLU"""
    return templates.TemplateResponse("admin/index.html", {"request": request})


# ==========================================
# 2. API SUMMARY CARDS (Statistik KPI)
# ==========================================
@router.get("/api/summary")
async def get_summary_cards(db: Session = Depends(get_db)):
    """Memberikan data statistik ringkas untuk kartu indikator di dashboard."""
    today_start = get_wib_time().strftime("%Y-%m-%d 00:00:00")

    # 1. Total Transaksi Lunas
    paid_trxs = (
        db.query(models.Transaction)
        .filter(models.Transaction.status == "PAID")
        .all()
    )

    total_revenue = sum(float(t.price or 0) for t in paid_trxs)
    total_kwh = sum(float(t.kwh_amount or 0) for t in paid_trxs)

    # 2. Pendapatan Hari Ini
    today_trxs = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.status == "PAID",
            models.Transaction.created_at >= today_start,
        )
        .all()
    )
    today_revenue = sum(float(t.price or 0) for t in today_trxs)

    # 3. User Tertunggak dari user_pending
    unpaid_users_count = (
        db.query(models.UserPending)
        .filter(models.UserPending.has_unpaid_bill == True)
        .count()
    )

    return {
        "total_revenue": total_revenue,
        "total_kwh": round(total_kwh, 2),
        "today_revenue": today_revenue,
        "total_transactions": len(paid_trxs),
        "unpaid_users_count": unpaid_users_count,
    }


# ==========================================
# 3. API TRANSACTIONS LIST (Data Datatable)
# ==========================================
@router.get("/api/transactions")
async def get_transactions(
    start_date: str = Query(None),
    end_date: str = Query(None),
    flow_type: str = Query(None),
    status: str = Query(None),
    db: Session = Depends(get_db),
):
    """Mengambil daftar transaksi dengan filter tanggal, tipe flow, dan status."""
    query = db.query(models.Transaction)

    if start_date:
        query = query.filter(
            models.Transaction.created_at >= f"{start_date} 00:00:00"
        )
    if end_date:
        query = query.filter(
            models.Transaction.created_at <= f"{end_date} 23:59:59"
        )
    if flow_type:
        query = query.filter(models.Transaction.flow_type == flow_type)
    if status:
        query = query.filter(models.Transaction.status == status)

    transactions = (
        query.order_by(models.Transaction.created_at.desc()).all()
    )

    # Serialisasi manual untuk konversi Decimal & Datetime ke JSON
    result = []
    for item in transactions:
        result.append(
            {
                "id": item.id,
                "nrp": item.nrp,
                "flow_type": item.flow_type,
                "kwh_amount": float(item.kwh_amount or 0),
                "price": float(item.price or 0),
                "qris_string": item.qris_string,
                "status": item.status,
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if item.created_at
                else None,
                "updated_at": item.updated_at.strftime("%Y-%m-%d %H:%M:%S")
                if item.updated_at
                else None,
            }
        )

    return result


# ==========================================
# 4. API CHART DATA (Grafik 7 Hari Terakhir)
# ==========================================
@router.get("/api/chart-data")
async def get_chart_data(db: Session = Depends(get_db)):
    """
    Mengambil rekap pendapatan, kWh, dan jumlah transaksi (Prepaid vs Postpaid)
    selama 7 hari terakhir untuk Chart.js.
    """
    today = get_wib_time()
    last_7_days = [
        (today - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(6, -1, -1)
    ]

    # Inisialisasi struktur data 7 hari terakhir
    chart_data = {
        date: {"revenue": 0.0, "kwh": 0.0, "prepaid": 0, "postpaid": 0}
        for date in last_7_days
    }

    start_date = today - timedelta(days=6)
    start_date_str = start_date.strftime("%Y-%m-%d 00:00:00")

    # Ambil transaksi PAID 7 hari terakhir
    trxs = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.status == "PAID",
            models.Transaction.created_at >= start_date_str,
        )
        .all()
    )

    # Akumulasi data per tanggal
    for trx in trxs:
        if trx.created_at:
            date_str = trx.created_at.strftime("%Y-%m-%d")
            if date_str in chart_data:
                chart_data[date_str]["revenue"] += float(trx.price or 0)
                chart_data[date_str]["kwh"] += float(trx.kwh_amount or 0)

                if trx.flow_type == "PREPAID":
                    chart_data[date_str]["prepaid"] += 1
                else:
                    chart_data[date_str]["postpaid"] += 1

    labels = list(chart_data.keys())
    revenues = [round(data["revenue"], 2) for data in chart_data.values()]
    kwhs = [round(data["kwh"], 2) for data in chart_data.values()]
    prepaid_counts = [data["prepaid"] for data in chart_data.values()]
    postpaid_counts = [data["postpaid"] for data in chart_data.values()]

    return {
        "labels": labels,
        "revenues": revenues,
        "kwhs": kwhs,
        "prepaid_counts": prepaid_counts,
        "postpaid_counts": postpaid_counts,
    }


# ==========================================
# 5. API DOWNLOAD EXCEL (Export Laporan)
# ==========================================
@router.get("/api/download-excel")
async def download_excel(
    start_date: str = Query(None),
    end_date: str = Query(None),
    db: Session = Depends(get_db),
):
    """Mengeksport data transaksi ke file Excel (.xlsx) dengan header Bahasa Indonesia."""
    query = db.query(models.Transaction)

    if start_date:
        query = query.filter(
            models.Transaction.created_at >= f"{start_date} 00:00:00"
        )
    if end_date:
        query = query.filter(
            models.Transaction.created_at <= f"{end_date} 23:59:59"
        )

    transactions = (
        query.order_by(models.Transaction.created_at.desc()).all()
    )

    # Susun data dengan nama header kolom yang ramah dibaca di Excel
    data = []
    for t in transactions:
        data.append(
            {
                "Kode Transaksi": t.id,
                "NRP Karyawan": t.nrp,
                "Metode Pengisian": t.flow_type,
                "Daya Terpakai (kWh)": float(t.kwh_amount or 0),
                "Total Biaya (Rp)": float(t.price or 0),
                "Status Transaksi": t.status,
                "Waktu Transaksi": t.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if t.created_at
                else "",
                "Terakhir Diperbarui": t.updated_at.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                if t.updated_at
                else "",
            }
        )

    df = pd.DataFrame(data)

    # Format jika tidak ada data
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "Kode Transaksi",
                "NRP Karyawan",
                "Metode Pengisian",
                "Daya Terpakai (kWh)",
                "Total Biaya (Rp)",
                "Status Transaksi",
                "Waktu Transaksi",
                "Terakhir Diperbarui",
            ]
        )

    # Tulis ke memory buffer
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Laporan SPKLU")
    output.seek(0)

    filename = f"Laporan_SPKLU_{get_wib_time().strftime('%Y%m%d_%H%M')}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        output,
        headers=headers,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )