import os
import tempfile
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import json

from backend.database import get_db, SessionLocal
from backend.models import Request, OutputFile
from backend.auth import get_current_user
from backend.services.file_parser import FileParser
from backend.services.claude_service import ClaudeService
from backend.services.excel_builder import ExcelBuilder
from backend.services.pdf_builder import PDFBuilder

router = APIRouter()

RESULTS_DIR = Path("/data/results")
RESULTS_DIR.mkdir(exist_ok=True)


def process_in_background(request_id: int, temp_files: dict, outputs: list, user_comment):
    db = SessionLocal()
    request_record = None
    try:
        request_record = db.query(Request).filter(Request.id == request_id).first()

        file_parser = FileParser()
        parsed_files = {}
        for file_name, file_path in temp_files.items():
            try:
                parsed_files[file_name] = file_parser.parse_file(file_path)
            except Exception as e:
                request_record.status = "error"
                request_record.error_message = f"Ошибка файла {file_name}: {str(e)}"
                db.commit()
                return

        claude_service = ClaudeService()
        output_files = {}
        list_data = None
        estimate_data = None

        if "list" in outputs or "estimate" in outputs or "comparison" in outputs:
            try:
                prompt = claude_service.create_list_prompt(parsed_files, user_comment)
                request_record.claude_prompt = prompt[:5000]
                db.commit()
                response = claude_service.call_claude(prompt, max_tokens=8000)
                request_record.claude_response = response[:5000]
                list_data = claude_service.parse_json_response(response)

                if "list" in outputs:
                    excel_builder = ExcelBuilder()
                    list_bytes = excel_builder.create_list_workbook(list_data)
                    list_filename = f"Перечень_работ_и_материалов_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.xlsx"
                    list_path = RESULTS_DIR / list_filename
                    list_path.write_bytes(list_bytes)
                    output_files["list"] = {"name": list_filename, "path": str(list_path), "type": "excel_list"}
                    db.add(OutputFile(request_id=request_id, file_name=list_filename, file_path=str(list_path), file_type="excel_list"))
                    db.commit()
            except Exception as e:
                request_record.status = "error"
                request_record.error_message = f"Ошибка Перечня: {str(e)}"
                db.commit()
                return

        if "estimate" in outputs:
            try:
                pricelist_works = _read_pricelist("pricelists/price_works.xlsx")
                pricelist_materials = _read_pricelist("pricelists/price_materials.xlsx")
                prompt = claude_service.create_estimate_prompt(list_data, pricelist_works, pricelist_materials)
                response = claude_service.call_claude(prompt, max_tokens=8000)
                estimate_data = claude_service.parse_json_response(response)

                excel_builder = ExcelBuilder()
                estimate_bytes = excel_builder.create_estimate_workbook(estimate_data)
                estimate_filename = f"Смета_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.xlsx"
                estimate_path = RESULTS_DIR / estimate_filename
                estimate_path.write_bytes(estimate_bytes)
                output_files["estimate"] = {"name": estimate_filename, "path": str(estimate_path), "type": "excel_estimate"}
                db.add(OutputFile(request_id=request_id, file_name=estimate_filename, file_path=str(estimate_path), file_type="excel_estimate"))
                db.commit()
            except Exception as e:
                request_record.status = "error"
                request_record.error_message = f"Ошибка Сметы: {str(e)}"
                db.commit()
                return

        if "comparison" in outputs:
            try:
                project_content = "\n".join([str(v) for v in parsed_files.values()])
                estimate_content = json.dumps(estimate_data or list_data, ensure_ascii=False)
                prompt = claude_service.create_comparison_prompt(project_content, estimate_content)
                response = claude_service.call_claude(prompt, max_tokens=4000)
                comparison_data = claude_service.parse_json_response(response)

                pdf_builder = PDFBuilder()
                pdf_bytes = pdf_builder.create_comparison_report(comparison_data)
                comparison_filename = f"Сравнительный_анализ_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.pdf"
                comparison_path = RESULTS_DIR / comparison_filename
                comparison_path.write_bytes(pdf_bytes)
                output_files["comparison"] = {"name": comparison_filename, "path": str(comparison_path), "type": "pdf_comparison"}
                db.add(OutputFile(request_id=request_id, file_name=comparison_filename, file_path=str(comparison_path), file_type="pdf_comparison"))
                db.commit()
            except Exception as e:
                request_record.status = "error"
                request_record.error_message = f"Ошибка анализа: {str(e)}"
                db.commit()
                return

        request_record.status = "success"
        request_record.output_files = output_files
        db.commit()

    except Exception as e:
        if request_record:
            request_record.status = "error"
            request_record.error_message = str(e)
            db.commit()
    finally:
        for temp_path in temp_files.values():
            Path(temp_path).unlink(missing_ok=True)
        db.close()


@router.post("/process")
async def process_request(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    input_type: str = Form(...),
    requested_outputs: str = Form(...),
    user_comment: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    outputs = json.loads(requested_outputs)

    temp_files = {}
    for file in files:
        content = await file.read()
        temp_path = Path(tempfile.gettempdir()) / f"{datetime.now().timestamp()}_{file.filename}"
        temp_path.write_bytes(content)
        temp_files[file.filename] = str(temp_path)

    request_record = Request(
        input_type=input_type,
        requested_outputs=outputs,
        status="processing",
        uploaded_files=[{"name": f.filename, "size": f.size, "format": f.content_type} for f in files],
        user_comment=user_comment
    )
    db.add(request_record)
    db.commit()
    db.refresh(request_record)

    background_tasks.add_task(process_in_background, request_record.id, temp_files, outputs, user_comment)

    return {"request_id": request_record.id, "status": "processing"}


@router.get("/status/{request_id}")
async def get_status(
    request_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    req = db.query(Request).filter(Request.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Запрос не найден")
    return {
        "request_id": req.id,
        "status": req.status,
        "output_files": req.output_files or {},
        "error_message": req.error_message
    }


@router.get("/download/{file_id}")
async def download_file(
    file_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    output_file = db.query(OutputFile).filter(OutputFile.id == file_id).first()
    if not output_file:
        raise HTTPException(status_code=404, detail="Файл не найден")
    file_path = Path(output_file.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл удален")
    return FileResponse(path=file_path, filename=output_file.file_name, media_type="application/octet-stream")


@router.get("/download-by-name/{file_name}")
async def download_by_name(
    file_name: str,
):
    file_path = RESULTS_DIR / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(path=file_path, filename=file_name, media_type="application/octet-stream")


@router.get("/history")
async def get_history(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    requests = db.query(Request).order_by(Request.created_at.desc()).limit(50).all()
    return {"history": [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "input_type": r.input_type,
            "requested_outputs": r.requested_outputs,
            "status": r.status,
            "output_files": r.output_files,
            "error_message": r.error_message
        } for r in requests
    ]}


def _read_pricelist(file_path: str) -> str:
    try:
        import pandas as pd
        if Path(file_path).exists():
            df = pd.read_excel(file_path, nrows=100)
            return df.to_string()
    except:
        pass
    return "(прайс-лист не найден)"
