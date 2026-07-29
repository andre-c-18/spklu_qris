import base64
import datetime
import hashlib
import hmac
import json
import os
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv

# Import PyCryptodome jika tersedia untuk RSA Signature asli BCA
try:
    from Crypto.Hash import SHA256
    from Crypto.PublicKey import RSA
    from Crypto.Signature import pkcs1_15

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

load_dotenv()


class BCAHelper:

    def __init__(self):
        # Konfigurasi BCA dari file .env
        self.client_id = os.getenv("BCA_CLIENT_ID", "")
        self.client_secret = os.getenv("BCA_CLIENT_SECRET", "")
        self.partner_id = os.getenv("BCA_PARTNER_ID", "12345")
        self.merchant_id = os.getenv("BCA_MERCHANT_ID", "0000001")
        self.terminal_id = os.getenv("BCA_TERMINAL_ID", "001")
        self.base_url = os.getenv(
            "BCA_BASE_URL", "https://sandbox.bca.co.id"
        ).rstrip("/")
        self.private_key_pem = os.getenv("BCA_PRIVATE_KEY", "")

        # Flag Mode Simulasi / Mock
        self.mock_mode = (
            os.getenv("BCA_MOCK_MODE", "True").lower() == "true"
            or not self.client_id
        )
        self._mock_poll_counter = {}

    def get_wib_timestamp(self) -> str:
        """Mengembalikan waktu saat ini dalam format ISO 8601 (WIB / Asia/Jakarta)"""
        return datetime.datetime.now(ZoneInfo("Asia/Jakarta")).isoformat(
            timespec="seconds"
        )

    def _generate_rsa_signature(self, string_to_sign: str) -> str:
        """Membuat RSA-SHA256 Signature untuk Access Token SNAP BCA"""
        if not HAS_CRYPTO or not self.private_key_pem:
            return "MOCK_RSA_SIGNATURE"
        key = RSA.import_key(self.private_key_pem)
        h = SHA256.new(string_to_sign.encode("utf-8"))
        signature = pkcs1_15.new(key).sign(h)
        return base64.b64encode(signature).decode("utf-8")

    def _generate_hmac_signature(
        self,
        http_method: str,
        endpoint_url: str,
        access_token: str,
        payload_json: str,
        timestamp: str,
    ) -> str:
        """Membuat HMAC-SHA512 Signature untuk Request Service SNAP BCA"""
        minified_body = (
            json.dumps(json.loads(payload_json)) if payload_json else ""
        )
        body_hash = (
            hashlib.sha256(minified_body.encode("utf-8")).hexdigest().lower()
        )
        string_to_sign = f"{http_method.upper()}:{endpoint_url}:{access_token}:{body_hash}:{timestamp}"

        hmac_code = hmac.new(
            self.client_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha512,  # Standar SNAP BI
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    def get_bca_token(self) -> str:
        """Langkah 1: Mengambil B2B Access Token"""
        if self.mock_mode:
            return "mock_access_token_12345"

        endpoint = "/snap/v1.0/access-token/b2b"
        url = f"{self.base_url}{endpoint}"
        timestamp = self.get_wib_timestamp()
        string_to_sign = f"{self.client_id}|{timestamp}"
        signature = self._generate_rsa_signature(string_to_sign)

        headers = {
            "X-TIMESTAMP": timestamp,
            "X-CLIENT-KEY": self.client_id,
            "X-SIGNATURE": signature,
            "Content-Type": "application/json",
        }
        payload = {"grantType": "client_credentials"}

        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            res.raise_for_status()
            return res.json().get("accessToken")
        except Exception as e:
            print(f"[BCA Error Token]: {e}")
            return None

    def generate_qris(self, price: float, trx_id: str) -> dict:
        """Langkah 2: Generate Dynamic QRIS (QRIS MPM Generate)"""
        if self.mock_mode:
            print(f"[MOCK MODE] Generating Dummy QRIS for TRX: {trx_id}")
            qr_content = f"00020101021226680014ID.BCA.WWW01189360091100108936009115204581253033605405{int(price):05d}5802ID5911CHARGING_ST6007JAKARTA61051234562070703A0163041A2B"
            return {
                "responseCode": "2004700",
                "responseMessage": "Successful",
                "partnerReferenceNo": trx_id,
                "qrContent": qr_content,
            }

        token = self.get_bca_token()
        if not token:
            raise Exception("Gagal mendapatkan Access Token dari BCA")

        endpoint = "/snap/v1.0/qr/qr-mpm-generate"
        url = f"{self.base_url}{endpoint}"
        timestamp = self.get_wib_timestamp()

        payload = {
            "partnerReferenceNo": trx_id,
            "amount": {"value": f"{price:.2f}", "currency": "IDR"},
            "merchantId": self.merchant_id,
            "terminalId": self.terminal_id,
            "validityPeriod": "15m",
        }

        payload_json = json.dumps(payload)
        signature = self._generate_hmac_signature(
            "POST", endpoint, token, payload_json, timestamp
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-TIMESTAMP": timestamp,
            "X-SIGNATURE": signature,
            "X-PARTNER-ID": self.partner_id,
            "X-EXTERNAL-ID": trx_id,
            "CHANNEL-ID": "95051",
        }

        try:
            res = requests.post(
                url, headers=headers, data=payload_json, timeout=10
            )
            res.raise_for_status()
            return res.json()
        except Exception as e:
            print(f"[BCA Error Generate QRIS]: {e}")
            raise Exception("Gagal menghubungi server BCA untuk Generate QRIS")

    def check_qris_status(self, partner_ref_no: str) -> dict:
        """Langkah 3: Memanggil API BCA QRIS MPM Inquiry (Dipanggil via Polling)"""
        if self.mock_mode:
            # Simulasi Polling: Polling ke-1 dan ke-2 status "01" (Pending), Polling ke-3 status "00" (PAID)
            counter = self._mock_poll_counter.get(partner_ref_no, 0) + 1
            self._mock_poll_counter[partner_ref_no] = counter

            if counter < 3:
                return {
                    "responseCode": "2004700",
                    "latestTransactionStatus": "01",
                    "transactionStatusDesc": "Pending",
                }
            else:
                return {
                    "responseCode": "2004700",
                    "latestTransactionStatus": "00",
                    "transactionStatusDesc": "Success",
                }

        token = self.get_bca_token()
        if not token:
            return {
                "latestTransactionStatus": "02",
                "transactionStatusDesc": "Failed Token",
            }

        endpoint = "/snap/v1.0/qr/qr-mpm-query"
        url = f"{self.base_url}{endpoint}"
        timestamp = self.get_wib_timestamp()

        payload = {
            "originalPartnerReferenceNo": partner_ref_no,
            "merchantId": self.merchant_id,
            "serviceCode": "47",
        }

        payload_json = json.dumps(payload)
        signature = self._generate_hmac_signature(
            "POST", endpoint, token, payload_json, timestamp
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-TIMESTAMP": timestamp,
            "X-SIGNATURE": signature,
            "X-PARTNER-ID": self.partner_id,
            "X-EXTERNAL-ID": partner_ref_no,
            "CHANNEL-ID": "95051",
        }

        try:
            res = requests.post(
                url, headers=headers, data=payload_json, timeout=10
            )
            res.raise_for_status()
            return res.json()
        except Exception as e:
            print(f"[BCA Error Check Status]: {e}")
            return {
                "latestTransactionStatus": "02",
                "transactionStatusDesc": "API Error",
            }

# Instansiasi Objek Global agar siap di-import oleh router FastAPI
bca_helper = BCAHelper()