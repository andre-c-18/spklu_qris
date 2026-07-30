# main.py
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from database import engine
import models
from routers import admin, kiosk

# Inisialisasi tabel database
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="SPKLU Payment Gateway")

# Mount aset statis (CSS, JS, Gambar)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ==========================================
# ROOT REDIRECT (Mengarahkan "/" ke "/api/kiosk/")
# ==========================================
@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/api/kiosk/")

# Registrasi Router
app.include_router(kiosk.router)
app.include_router(admin.router)