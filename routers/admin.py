from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import pandas as pd
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import models
from database import get_db

def get_wib_time():
    return datetime.now(ZoneInfo("Asia/Jakarta")).replace(tzinfo=None)

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")

@router.get("")
@router.get("/")
async def admin_dashboard(request: Request):
    return templates.TemplateResponse("admin/index.html", {"request": request})

# Endpoint untuk mengambil data JSON dengan filter tanggal
@router.get("/api/transactions")
async def get_transactions(
    start_date: str = Query(None),
    end_date: str = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(models.Transaction)
    
    # Terapkan filter jika ada parameter tanggal yang dikirim
    if start_date:
        query = query.filter(models.Transaction.created_at >= f"{start_date} 00:00:00")
    if end_date:
        query = query.filter(models.Transaction.created_at <= f"{end_date} 23:59:59")
        
    # Urutkan dari yang terbaru
    transactions = query.order_by(models.Transaction.created_at.desc()).all()
    return transactions

# Endpoint untuk Download Excel via Pandas
@router.get("/api/download-excel")
async def download_excel(
    start_date: str = Query(None),
    end_date: str = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(models.Transaction)
    
    if start_date:
        query = query.filter(models.Transaction.created_at >= f"{start_date} 00:00:00")
    if end_date:
        query = query.filter(models.Transaction.created_at <= f"{end_date} 23:59:59")

    # Konversi query SQLAlchemy langsung menjadi DataFrame Pandas
    df = pd.read_sql(query.statement, db.connection())
    
    # Jika database kosong, buat DataFrame kosong dengan kolom yang rapi
    if df.empty:
        df = pd.DataFrame(columns=["ID", "NRP", "kWh", "Harga", "QRIS", "Status", "Dibuat", "Diupdate"])
    else:
        # Bersihkan timezone agar kompatibel dengan Excel
        if 'created_at' in df.columns:
            df['created_at'] = df['created_at'].dt.tz_localize(None)
        if 'updated_at' in df.columns:
            df['updated_at'] = df['updated_at'].dt.tz_localize(None)

    # Tulis DataFrame ke dalam object BytesIO (memori), bukan ke hardisk server
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Log Transaksi')
    output.seek(0)

    # Nama file dinamis
    filename = f"Laporan_SPKLU_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        output, 
        headers=headers, 
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@router.get("/api/chart-data")
async def get_chart_data(db: Session = Depends(get_db)):
    """
    Mengambil rekap pendapatan dan kWh selama 7 hari terakhir.
    Hanya menghitung transaksi yang sukses (PAID).
    """
    # 1. Siapkan daftar 7 hari terakhir (agar hari yang kosong tetap tampil di grafik dengan nilai 0)
    today = get_wib_time()
    last_7_days = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    
    # Inisialisasi dictionary dengan nilai 0
    chart_data = {date: {"revenue": 0, "kwh": 0} for date in last_7_days}
    
    # 2. Ambil data dari 7 hari terakhir yang statusnya PAID
    start_date = today - timedelta(days=6)
    start_date_str = start_date.strftime("%Y-%m-%d 00:00:00")
    
    trxs = db.query(models.Transaction).filter(
        models.Transaction.status == models.TransactionStatus.PAID,
        models.Transaction.created_at >= start_date_str
    ).all()
    
    # 3. Kelompokkan dan jumlahkan berdasarkan tanggal
    for trx in trxs:
        date_str = trx.created_at.strftime("%Y-%m-%d")
        if date_str in chart_data:
            chart_data[date_str]["revenue"] += trx.price
            chart_data[date_str]["kwh"] += trx.kwh_amount
            
    # 4. Ubah formatnya menjadi array agar mudah dibaca oleh Chart.js
    labels = list(chart_data.keys())
    revenues = [data["revenue"] for data in chart_data.values()]
    kwhs = [data["kwh"] for data in chart_data.values()]
    
    return {
        "labels": labels,
        "revenues": revenues,
        "kwhs": kwhs
    }