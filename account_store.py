import json
import logging
from itsdangerous import URLSafeSerializer
from werkzeug.security import check_password_hash
import config

logger = logging.getLogger(__name__)

VAULT_COOKIE_NAME = "_su_v"
VAULT_COOKIE_MAX_AGE = 365 * 24 * 3600  # 1 year

def _get_serializer():
    return URLSafeSerializer(config.SECRET_KEY, salt="student-vault-v1")

def unpack_vault(token):
    """Unpack and verify the signed vault token."""
    if not token or not isinstance(token, str):
        return {}
    try:
        data = _get_serializer().loads(token.strip())
        if isinstance(data, dict):
            # Format: {"accounts": {ident: {...}}}
            return data.get("accounts", data)
    except Exception as e:
        logger.debug(f"Could not unpack vault token: {e}")
    return {}

def pack_vault(accounts_dict):
    """Sign and pack accounts dict into a tamper-proof URL-safe token."""
    try:
        clean_accounts = {}
        for k, v in accounts_dict.items():
            if isinstance(v, dict):
                clean_accounts[str(k).lower().strip()] = {
                    "id": v.get("id"),
                    "student_id": str(v.get("student_id") or "").strip(),
                    "email": str(v.get("email") or "").strip().lower(),
                    "name": str(v.get("name") or "").strip(),
                    "batch": str(v.get("batch") or "2024").strip(),
                    "gender": str(v.get("gender") or "").strip(),
                    "pw_hash": str(v.get("pw_hash") or "").strip(),
                    "status": str(v.get("status") or "active").strip(),
                    "is_demo": int(v.get("is_demo") or 0)
                }
        return _get_serializer().dumps({"accounts": clean_accounts})
    except Exception as e:
        logger.warning(f"Could not pack vault: {e}")
        return ""

def get_vault_from_request(req):
    """Read vault tokens from Cookie, Form, Header, and JSON body, merging all valid accounts."""
    if not req:
        return {}
    accounts = {}
    tokens = []

    # 1. Cookie
    c_token = req.cookies.get(VAULT_COOKIE_NAME)
    if c_token:
        tokens.append(c_token)

    # 2. Form field
    if req.form:
        f_token = req.form.get("client_vault")
        if f_token:
            tokens.append(f_token)

    # 3. Request Header
    h_token = req.headers.get("X-Client-Vault")
    if h_token:
        tokens.append(h_token)

    # 4. JSON body if applicable
    if req.is_json:
        try:
            j = req.get_json(silent=True) or {}
            j_token = j.get("client_vault")
            if j_token:
                tokens.append(j_token)
        except Exception:
            pass

    for t in tokens:
        unpacked = unpack_vault(t)
        if isinstance(unpacked, dict):
            for k, v in unpacked.items():
                if isinstance(v, dict):
                    accounts[str(k).lower().strip()] = v

    return accounts


def add_student_to_vault(req, student_data):
    """Add or update student in the device vault and return a new signed token."""
    accounts = get_vault_from_request(req) if req else {}
    sid = str(student_data.get("student_id") or "").strip().lower()
    email = str(student_data.get("email") or "").strip().lower()

    payload = {
        "id": student_data.get("id"),
        "student_id": student_data.get("student_id"),
        "email": student_data.get("email"),
        "name": student_data.get("name"),
        "batch": student_data.get("batch") or "2024",
        "gender": student_data.get("gender") or "",
        "pw_hash": student_data.get("pw_hash"),
        "status": student_data.get("status") or "active",
        "is_demo": int(student_data.get("is_demo") or 0)
    }

    if sid:
        accounts[sid] = payload
    if email:
        accounts[email] = payload

    return pack_vault(accounts)

def find_student_in_vault(req, identifier):
    """Search for student by identifier (student ID or email) in the device vault."""
    ident = str(identifier or "").strip().lower()
    if not ident:
        return None
    accounts = get_vault_from_request(req)
    # Direct match
    if ident in accounts:
        return accounts[ident]
    # Check within values
    for acc in accounts.values():
        if isinstance(acc, dict):
            if str(acc.get("student_id") or "").strip().lower() == ident:
                return acc
            if str(acc.get("email") or "").strip().lower() == ident:
                return acc
    return None

# ------------------------------------------------ Optional Cloud KV Sync
# If user sets KV_REST_API_URL / UPSTASH_REDIS_REST_URL in Vercel settings,
# student accounts are automatically backed up to cloud KV.
import os, urllib.request

KV_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")

def sync_to_cloud_kv(student_data):
    """Optionally sync student account to Vercel KV / Upstash Redis if configured."""
    if not KV_URL or not KV_TOKEN:
        return
    try:
        sid = str(student_data.get("student_id") or "").strip().lower()
        email = str(student_data.get("email") or "").strip().lower()
        val = json.dumps({
            "id": student_data.get("id"),
            "student_id": student_data.get("student_id"),
            "email": student_data.get("email"),
            "name": student_data.get("name"),
            "batch": student_data.get("batch") or "2024",
            "gender": student_data.get("gender") or "",
            "pw_hash": student_data.get("pw_hash"),
            "status": student_data.get("status") or "active",
            "is_demo": int(student_data.get("is_demo") or 0)
        })
        for key in [f"su_stu:{sid}", f"su_stu:{email}"]:
            if not key.endswith(":"):
                req = urllib.request.Request(
                    f"{KV_URL.rstrip('/')}/set/{key}",
                    data=val.encode("utf-8"),
                    headers={"Authorization": f"Bearer {KV_TOKEN}", "Content-Type": "application/json"},
                    method="POST"
                )
                urllib.request.urlopen(req, timeout=3)
    except Exception as ex:
        logger.warning(f"KV sync failed: {ex}")

def sync_from_cloud_kv(identifier):
    """Retrieve student account from Vercel KV / Upstash Redis if configured."""
    if not KV_URL or not KV_TOKEN:
        return None
    try:
        ident = str(identifier or "").strip().lower()
        req = urllib.request.Request(
            f"{KV_URL.rstrip('/')}/get/su_stu:{ident}",
            headers={"Authorization": f"Bearer {KV_TOKEN}"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data.get("result")
            if result:
                if isinstance(result, str):
                    return json.loads(result)
                elif isinstance(result, dict):
                    return result
    except Exception as ex:
        logger.warning(f"KV fetch failed: {ex}")
    return None
