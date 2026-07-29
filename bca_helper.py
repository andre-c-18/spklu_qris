import os
import hmac
import hashlib
import json
import requests
from fastapi import HTTPException
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

# Konfigurasi BCA dari file .env
BCA_CLIENT_ID = os.getenv("BCA_CLIENT_ID", "")
BCA_CLIENT_SECRET = os.getenv("BCA_CLIENT_SECRET", "")
BCA_API_KEY = os.getenv("BCA_API_KEY", "")
BCA_API_SECRET = os.getenv("BCA_API_SECRET", "")
BCA_BASE_URL = os.getenv("BCA_BASE_URL", "https://sandbox.bca.co.id")

def get_wib_time_iso():
    """Mengembalikan waktu saat ini dalam format ISO 8601 (WIB)"""
    return datetime.now(ZoneInfo("Asia/Jakarta")).isoformat(timespec='seconds')

def get_bca_token():
    """
    Fungsi untuk mendapatkan Access Token dari BCA.
    (Saat integrasi SNAP BI asli, proses ini butuh RSA Signature. 
    Ini adalah representasi HTTP request standarnya).
    """
    url = f"{BCA_BASE_URL}/api/oauth/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    payload = {"grant_type": "client_credentials"}
    
    try:
        # Menggunakan Basic Auth untuk Client ID & Secret
        response = requests.post(url, auth=(BCA_CLIENT_ID, BCA_CLIENT_SECRET), headers=headers, data=payload, timeout=10)
        response.raise_for_status()
        return response.json().get("access_token")
    except Exception as e:
        print(f"Error Token BCA: {e}")
        return None

def generate_qris(price: float, trx_id: str) -> str:
    """
    Fungsi utama yang dipanggil oleh Kiosk untuk mencetak QR.
    Jika API_KEY belum ada, otomatis mengembalikan Dummy QRIS.
    """
    # 1. CEK KETERSEDIAAN KREDENSIAL (MODE SIMULASI)
    if not BCA_API_KEY or not BCA_API_SECRET:
        print("⚠️ BCA API Keys kosong. Menggunakan Dummy QRIS.")
        return f"00020101021226570011ID.CO.BCA.WWW0118...{int(price)}...{trx_id}"

    # 2. PROSES ASLI JIKA KREDENSIAL TERSEDIA
    token = get_bca_token()
    if not token:
        raise ValueError("Gagal mendapatkan token dari BCA")

    timestamp = get_wib_time_iso()
    relative_url = "/api/v1/qr/qr-mpm-generate" # Endpoint BCA SNAP
    
    # Body Request standar QRIS Dinamis
    payload = {
        "partnerReferenceNo": trx_id,
        "amount": {
            "value": f"{int(price)}.00",
            "currency": "IDR"
        },
        "merchantId": "MERCHANT_ANDA", 
        "terminalId": "SPKLU_01"
    }

    # 3. PEMBUATAN SIGNATURE HMAC-SHA (Standar Keamanan API)
    body_str = json.dumps(payload, separators=(',', ':'))
    body_hash = hashlib.sha256(body_str.encode('utf-8')).hexdigest().lower()
    string_to_sign = f"POST:{relative_url}:{token}:{body_hash}:{timestamp}"
    
    signature = hmac.new(
        BCA_API_SECRET.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-TIMESTAMP": timestamp,
        "X-SIGNATURE": signature,
        "X-PARTNER-ID": BCA_CLIENT_ID,
        "X-EXTERNAL-ID": trx_id
    }

    try:
        response = requests.post(f"{BCA_BASE_URL}{relative_url}", headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("qrContent") # Sesuaikan parameter balikan dari dokumen BCA asli
    except Exception as e:
        print(f"Error Generate QRIS BCA: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Detail: {e.response.text}")
        raise Exception("Gagal menghubungi server BCA")

def verify_signature(raw_body: bytes, headers: dict) -> bool:
    """
    Memvalidasi signature dari notifikasi webhook BCA untuk memastikan 
    request benar-benar datang dari bank, bukan dari hacker.
    """
    # 1. CEK MODE SIMULASI (Jika .env belum diisi)
    if not BCA_API_SECRET:
        print("⚠️ Mode Simulasi: Melewati validasi signature webhook.")
        return True

    # 2. AMBIL HEADER DARI BCA
    # FastAPI membaca header dengan huruf kecil semua (case-insensitive)
    x_signature = headers.get("x-signature") or headers.get("x-bca-signature")
    x_timestamp = headers.get("x-timestamp") or headers.get("x-bca-timestamp")

    if not x_signature or not x_timestamp:
        print("❌ Header BCA tidak lengkap!")
        raise HTTPException(status_code=401, detail="Missing BCA Headers")

    # 3. HASH BODY REQUEST
    # Kita menggunakan raw_body (bytes asli) agar tidak ada perbedaan spasi 
    # yang bisa membuat hasil hash meleset.
    body_hash = hashlib.sha256(raw_body).hexdigest().lower()

    # 4. SUSUN STRING TO SIGN
    # Format ini adalah standar Webhook SNAP BI (HTTPMethod:RelativePath:BodyHash:Timestamp)
    relative_url = "/api/bca-webhook" 
    string_to_sign = f"POST:{relative_url}:{body_hash}:{x_timestamp}"

    # 5. BUAT SIGNATURE PEMBANDING
    expected_signature = hmac.new(
        BCA_API_SECRET.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    # 6. BANDINGKAN SIGNATURE SECARA AMAN (Mencegah Timing Attack)
    if not hmac.compare_digest(expected_signature, x_signature):
        print(f"❌ Signature Tidak Cocok!\nExpected: {expected_signature}\nGot: {x_signature}")
        raise HTTPException(status_code=401, detail="Invalid Signature")
    
    print("✅ Signature BCA Valid!")
    return True