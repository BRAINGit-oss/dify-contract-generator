from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from docxtpl import DocxTemplate
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse


app = FastAPI(title="Contract Generator Service", version="1.0.0")

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "generated_contracts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def normalize_value(value: Any) -> Any:
    if pd.isna(value):
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def clean_name(value: str) -> str:
    kept = "".join(ch for ch in value if ch.isalnum() or ch in ("-", "_"))
    return kept[:64] or "contract"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate-contracts")
async def generate_contracts(
    excel_file: UploadFile = File(...),
    template_file: UploadFile = File(...),
    output_format: str = Form("docx"),
) -> dict[str, Any]:
    if output_format.lower() != "docx":
        raise HTTPException(status_code=400, detail="Only docx output is supported.")

    excel_name = (excel_file.filename or "").lower()
    template_name = (template_file.filename or "").lower()
    if not (excel_name.endswith(".xlsx") or excel_name.endswith(".xls")):
        raise HTTPException(status_code=400, detail="excel_file must be .xlsx or .xls")
    if not template_name.endswith(".docx"):
        raise HTTPException(status_code=400, detail="template_file must be .docx")

    excel_bytes = await excel_file.read()
    template_bytes = await template_file.read()
    if not excel_bytes:
        raise HTTPException(status_code=400, detail="excel_file is empty")
    if not template_bytes:
        raise HTTPException(status_code=400, detail="template_file is empty")

    try:
        df = pd.read_excel(BytesIO(excel_bytes), dtype=object)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read Excel: {exc}") from exc

    if df.empty:
        raise HTTPException(status_code=400, detail="Excel has no data rows")

    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
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

        generated_files.append(
            {
                "file_name": output_name,
                "relative_path": f"generated_contracts/{batch_id}/{output_name}",
                "download_url": f"/download/{batch_id}/{output_name}",
            }
        )

    return {
        "message": "Contracts generated successfully",
        "count": len(generated_files),
        "batch_id": batch_id,
        "files": generated_files,
    }


@app.get("/download/{batch_id}/{file_name}")
def download_contract(batch_id: str, file_name: str) -> FileResponse:
    target = OUTPUT_DIR / batch_id / file_name
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path=str(target),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=file_name,
    )
