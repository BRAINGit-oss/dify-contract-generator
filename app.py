from collections import deque
from datetime import date, datetime, timezone
import base64
import hashlib
import hmac
from io import BytesIO
import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import pandas as pd
from docxtpl import DocxTemplate
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse


app = FastAPI(title="Contract Generator Service", version="2.0.0")

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "generated_contracts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOGGER = logging.getLogger("contract_service")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

API_TOKEN = os.getenv("API_TOKEN", "").strip()
SIGNING_SECRET = os.getenv("SIGNING_SECRET", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
MAX_EXCEL_BYTES = int(os.getenv("MAX_EXCEL_BYTES", str(10 * 1024 * 1024)))
MAX_TEMPLATE_BYTES = int(os.getenv("MAX_TEMPLATE_BYTES", str(5 * 1024 * 1024)))
MAX_ROWS = int(os.getenv("MAX_ROWS", "500"))
MAX_COLUMNS = int(os.getenv("MAX_COLUMNS", "100"))
MAX_OUTPUT_FILES = int(os.getenv("MAX_OUTPUT_FILES", "500"))
DOWNLOAD_TTL_SECONDS = int(os.getenv("DOWNLOAD_TTL_SECONDS", str(15 * 60)))
OUTPUT_RETENTION_SECONDS = int(os.getenv("OUTPUT_RETENTION_SECONDS", str(24 * 3600)))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "20"))
STRICT_COLUMNS = os.getenv("STRICT_COLUMNS", "false").lower() == "true"
ALLOWED_COLUMNS = {x.strip() for x in os.getenv("ALLOWED_COLUMNS", "").split(",") if x.strip()}
PATH_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_RATE_LIMITER_LOCK = threading.Lock()
_RATE_LIMITER_BUCKETS: dict[str, deque[float]] = {}


def normalize_value(value: Any) -> Any:
    if pd.isna(value):
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def clean_name(value: str) -> str:
    kept = "".join(ch for ch in value if ch.isascii() and (ch.isalnum() or ch in ("-", "_")))
    return kept[:64] or "contract"


def utc_now_ts() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


def ensure_path_safe(value: str, field_name: str) -> None:
    if not PATH_SAFE_PATTERN.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


def validate_extension(filename: str, allowed: set[str], field_name: str) -> str:
    lowered = filename.lower()
    for ext in allowed:
        if lowered.endswith(ext):
            return ext
    raise HTTPException(status_code=400, detail=f"{field_name} has invalid extension")


def validate_file_magic(file_bytes: bytes, ext: str, field_name: str) -> None:
    header = file_bytes[:8]
    is_zip = header.startswith(b"PK")
    is_xls = header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    if ext == ".docx" and not is_zip:
        raise HTTPException(status_code=400, detail=f"{field_name} content is not a valid docx")
    if ext in {".xlsx"} and not is_zip:
        raise HTTPException(status_code=400, detail=f"{field_name} content is not a valid xlsx")
    if ext == ".xls" and not (is_xls or is_zip):
        raise HTTPException(status_code=400, detail=f"{field_name} content is not a valid xls")


def require_auth(authorization: str | None) -> str:
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="Service auth is not configured")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = authorization[7:].strip()
    if not hmac.compare_digest(token, API_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def enforce_rate_limit(tenant_id: str, token_fingerprint: str) -> None:
    now = time.time()
    key = f"{tenant_id}:{token_fingerprint}"
    with _RATE_LIMITER_LOCK:
        bucket = _RATE_LIMITER_BUCKETS.setdefault(key, deque())
        threshold = now - RATE_LIMIT_WINDOW_SECONDS
        while bucket and bucket[0] < threshold:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_REQUESTS:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        bucket.append(now)


def ensure_signing_secret() -> str:
    if not SIGNING_SECRET:
        raise HTTPException(status_code=503, detail="Signing secret is not configured")
    return SIGNING_SECRET


def sign_download(batch_id: str, file_name: str, expires: int, secret: str) -> str:
    payload = f"{batch_id}:{file_name}:{expires}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def build_download_url(batch_id: str, file_name: str, expires: int, sig: str) -> str:
    path = f"/download/{quote(batch_id)}/{quote(file_name)}?expires={expires}&sig={quote(sig)}"
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}{path}"
    return path


def cleanup_expired_batches() -> None:
    now = utc_now_ts()
    if not OUTPUT_DIR.exists():
        return
    for child in OUTPUT_DIR.iterdir():
        if not child.is_dir():
            continue
        try:
            modified = int(child.stat().st_mtime)
        except OSError:
            continue
        if now - modified > OUTPUT_RETENTION_SECONDS:
            for sub in child.rglob("*"):
                if sub.is_file():
                    sub.unlink(missing_ok=True)
            for sub in sorted(child.rglob("*"), reverse=True):
                if sub.is_dir():
                    sub.rmdir()
            child.rmdir()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate-contracts")
async def generate_contracts(
    excel_file: UploadFile = File(...),
    template_file: UploadFile = File(...),
    output_format: str = Form("docx"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    tenant_id: str = Header(default="default", alias="X-Tenant-ID"),
) -> dict[str, Any]:
    ensure_path_safe(tenant_id, "tenant_id")
    token_fingerprint = require_auth(authorization)
    enforce_rate_limit(tenant_id, token_fingerprint)
    cleanup_expired_batches()
    if output_format.lower() != "docx":
        raise HTTPException(status_code=400, detail="Only docx output is supported.")

    excel_name = (excel_file.filename or "").lower()
    template_name = (template_file.filename or "").lower()
    excel_ext = validate_extension(excel_name, {".xlsx", ".xls"}, "excel_file")
    template_ext = validate_extension(template_name, {".docx"}, "template_file")

    excel_bytes = await excel_file.read()
    template_bytes = await template_file.read()
    if not excel_bytes:
        raise HTTPException(status_code=400, detail="excel_file is empty")
    if not template_bytes:
        raise HTTPException(status_code=400, detail="template_file is empty")
    if len(excel_bytes) > MAX_EXCEL_BYTES:
        raise HTTPException(status_code=413, detail="excel_file exceeds size limit")
    if len(template_bytes) > MAX_TEMPLATE_BYTES:
        raise HTTPException(status_code=413, detail="template_file exceeds size limit")
    validate_file_magic(excel_bytes, excel_ext, "excel_file")
    validate_file_magic(template_bytes, template_ext, "template_file")

    try:
        df = pd.read_excel(BytesIO(excel_bytes), dtype=object)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read Excel: {exc}") from exc

    if df.empty:
        raise HTTPException(status_code=400, detail="Excel has no data rows")
    if len(df) > MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"Excel rows exceed limit: {MAX_ROWS}")
    if len(df.columns) > MAX_COLUMNS:
        raise HTTPException(status_code=400, detail=f"Excel columns exceed limit: {MAX_COLUMNS}")
    if len(df) > MAX_OUTPUT_FILES:
        raise HTTPException(status_code=400, detail=f"Output files exceed limit: {MAX_OUTPUT_FILES}")

    input_columns = {str(col).strip() for col in df.columns}
    if STRICT_COLUMNS and ALLOWED_COLUMNS:
        unknown = sorted(input_columns - ALLOWED_COLUMNS)
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown columns: {', '.join(unknown)}")

    secret = ensure_signing_secret()
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:12]
    batch_dir = OUTPUT_DIR / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    generated_files: list[dict[str, str]] = []

    for row_index, row in df.iterrows():
        context = {str(col): normalize_value(row[col]) for col in df.columns}
        contract_no = str(context.get("contract_no", "")).strip()
        customer_name = str(context.get("customer_name", "")).strip()
        filename_base = clean_name(contract_no or customer_name or f"contract_{row_index + 1}")
        output_name = f"{row_index + 1:04d}_{filename_base}.docx"
        output_path = batch_dir / output_name

        doc = DocxTemplate(BytesIO(template_bytes))
        doc.render(context)
        doc.save(str(output_path))
        expires = utc_now_ts() + DOWNLOAD_TTL_SECONDS
        sig = sign_download(batch_id, output_name, expires, secret)

        generated_files.append(
            {
                "file_name": output_name,
                "relative_path": f"generated_contracts/{batch_id}/{output_name}",
                "expires_at": expires,
                "download_url": build_download_url(batch_id, output_name, expires, sig),
            }
        )
    LOGGER.info(
        "contracts_generated tenant=%s batch=%s files=%s token=%s",
        tenant_id,
        batch_id,
        len(generated_files),
        token_fingerprint,
    )

    return {
        "message": "Contracts generated successfully",
        "count": len(generated_files),
        "batch_id": batch_id,
        "files": generated_files,
    }


@app.get("/download/{batch_id}/{file_name}")
def download_contract(
    batch_id: str,
    file_name: str,
    expires: int = Query(..., ge=1),
    sig: str = Query(..., min_length=16),
) -> FileResponse:
    ensure_path_safe(batch_id, "batch_id")
    ensure_path_safe(file_name, "file_name")
    secret = ensure_signing_secret()
    expected = sign_download(batch_id, file_name, expires, secret)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="Invalid download signature")
    if utc_now_ts() > expires:
        raise HTTPException(status_code=401, detail="Download URL expired")
    cleanup_expired_batches()
    target = OUTPUT_DIR / batch_id / file_name
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path=str(target),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=file_name,
    )
