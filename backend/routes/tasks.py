import os
import tempfile
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import json

from backend.database import get_db
from backend.models import Request, OutputFile
from backend.auth import get_current_user
from backend.services.file_parser import FileParser
from backend.services.claude_service import ClaudeService
from backend.services.excel_builder import ExcelBuilder
from backend.services.pdf_builder import PDFBuilder

router = APIRouter()

# Директория для сохранения результатов
RESULTS_DIR = Path("/tmp/smeta_ai_results")
RESULTS_DIR.mkdir(exist_ok=True)

@router.post("/process")
async def process_request(
    files: List[UploadFile] = File(...),
    input_type: str = Form(...),
    requested_outputs: str = Form(...),  # JSON строка ["list", "estimate", "comparison"]
    user_comment: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Основной эндпоинт для обработки запросов"""
    
    try:
        # Парсим выбранные результаты
        outputs = json.loads(requested_outputs)
        
        # Создаем запись в БД
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
        
        # Сохраняем загруженные файлы временно
        temp_files = {}
        for file in files:
            content = await file.read()
            temp_path = Path(tempfile.gettempdir()) / file.filename
            temp_path.write_bytes(content)
            temp_files[file.filename] = str(temp_path)
        
        # Парсим файлы
        file_parser = FileParser()
        parsed_files = {}
        
        for file_name, file_path in temp_files.items():
            try:
                parsed_files[file_name] = file_parser.parse_file(file_path)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Ошибка при обработке файла {file_name}: {str(e)}"
                )
        
        # Инициализируем сервис Claude
        claude_service = ClaudeService()
        output_files = {}
        
        # Этап 1: Формирование Перечня
        list_data = None
        if "list" in outputs or "estimate" in outputs or "comparison" in outputs:
            try:
                # Создаем промпт для формирования перечня
                prompt = claude_service.create_list_prompt(parsed_files, user_comment)
                request_record.claude_prompt = prompt[:5000]  # Сохраняем первые 5000 символов
                
                # Отправляем запрос в Claude
                response = claude_service.call_claude(prompt, max_tokens=8000)
                request_record.claude_response = response[:5000]
                
                # Парсим JSON ответ
                list_data = claude_service.parse_json_response(response)
                
                # Создаем Excel файл для Перечня
                if "list" in outputs:
                    excel_builder = ExcelBuilder()
                    list_bytes = excel_builder.create_list_workbook(list_data)
                    
                    list_filename = f"Перечень_работ_и_материалов_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
                    list_path = RESULTS_DIR / list_filename
                    list_path.write_bytes(list_bytes)
                    
                    output_files["list"] = {
                        "name": list_filename,
                        "path": str(list_path),
                        "type": "excel_list"
                    }
                    
                    # Сохраняем в БД
                    output_file = OutputFile(
                        request_id=request_record.id,
                        file_name=list_filename,
                        file_path=str(list_path),
                        file_type="excel_list"
                    )
                    db.add(output_file)
                
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Ошибка при формировании Перечня: {str(e)}"
                )
        
        # Этап 2: Формирование Сметы
        if "estimate" in outputs:
            try:
                # Если перечня еще нет, создаем его
                if list_data is None:
                    prompt = claude_service.create_list_prompt(parsed_files, user_comment)
                    response = claude_service.call_claude(prompt, max_tokens=8000)
                    list_data = claude_service.parse_json_response(response)
                
                # Читаем прайс-листы
                pricelist_works = _read_pricelist("backend/pricelists/price_works.xlsx")
                pricelist_materials = _read_pricelist("backend/pricelists/price_materials.xlsx")
                
                # Создаем промпт для сметы
                prompt = claude_service.create_estimate_prompt(list_data, pricelist_works, pricelist_materials)
                response = claude_service.call_claude(prompt, max_tokens=8000)
                estimate_data = claude_service.parse_json_response(response)
                
                # Создаем Excel файл для Сметы
                excel_builder = ExcelBuilder()
                estimate_bytes = excel_builder.create_estimate_workbook(estimate_data)
                
                estimate_filename = f"Смета_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
                estimate_path = RESULTS_DIR / estimate_filename
                estimate_path.write_bytes(estimate_bytes)
                
                output_files["estimate"] = {
                    "name": estimate_filename,
                    "path": str(estimate_path),
                    "type": "excel_estimate"
                }
                
                output_file = OutputFile(
                    request_id=request_record.id,
                    file_name=estimate_filename,
                    file_path=str(estimate_path),
                    file_type="excel_estimate"
                )
                db.add(output_file)
                
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Ошибка при формировании Сметы: {str(e)}"
                )
        
        # Этап 3: Сравнительный анализ
        if "comparison" in outputs:
            try:
                # Проверяем наличие проекта и сметы
                has_project = any("проект" in str(f).lower() or "спец" in str(f).lower() for f in parsed_files.keys())
                
                if not has_project:
                    raise Exception("Сравнительный анализ требует загрузки проекта или спецификации")
                
                # Получаем информацию о проекте и смете
                project_content = "\n".join([str(v) for v in parsed_files.values()])
                estimate_content = json.dumps(estimate_data or list_data, ensure_ascii=False)
                
                # Создаем промпт для анализа
                prompt = claude_service.create_comparison_prompt(project_content, estimate_content)
                response = claude_service.call_claude(prompt, max_tokens=4000)
                comparison_data = claude_service.parse_json_response(response)
                
                # Создаем PDF файл
                pdf_builder = PDFBuilder()
                pdf_bytes = pdf_builder.create_comparison_report(comparison_data)
                
                comparison_filename = f"Сравнительный_анализ_{datetime.now().strftime('%Y-%m-%d')}.pdf"
                comparison_path = RESULTS_DIR / comparison_filename
                comparison_path.write_bytes(pdf_bytes)
                
                output_files["comparison"] = {
                    "name": comparison_filename,
                    "path": str(comparison_path),
                    "type": "pdf_comparison"
                }
                
                output_file = OutputFile(
                    request_id=request_record.id,
                    file_name=comparison_filename,
                    file_path=str(comparison_path),
                    file_type="pdf_comparison"
                )
                db.add(output_file)
                
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Ошибка при формировании сравнительного анализа: {str(e)}"
                )
        
        # Обновляем статус запроса
        request_record.status = "success"
        request_record.output_files = output_files
        db.commit()
        
        # Удаляем временные файлы
        for temp_path in temp_files.values():
            Path(temp_path).unlink(missing_ok=True)
        
        return {
            "request_id": request_record.id,
            "status": "success",
            "output_files": output_files
        }
        
    except HTTPException:
        raise
    except Exception as e:
        # Обновляем статус ошибки
        if 'request_record' in locals():
            request_record.status = "error"
            request_record.error_message = str(e)
            db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки: {str(e)}"
        )

@router.get("/download/{file_id}")
async def download_file(
    file_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Скачать готовый файл"""
    
    output_file = db.query(OutputFile).filter(OutputFile.id == file_id).first()
    
    if not output_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл не найден"
        )
    
    file_path = Path(output_file.file_path)
    
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл удален или недоступен"
        )
    
    return FileResponse(
        path=file_path,
        filename=output_file.file_name,
        media_type="application/octet-stream"
    )

@router.get("/history")
async def get_history(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить историю запросов пользователя"""
    
    requests = db.query(Request).order_by(Request.created_at.desc()).limit(50).all()
    
    history = []
    for req in requests:
        history.append({
            "id": req.id,
            "created_at": req.created_at.isoformat(),
            "input_type": req.input_type,
            "requested_outputs": req.requested_outputs,
            "status": req.status,
            "output_files": req.output_files,
            "error_message": req.error_message
        })
    
    return {"history": history}

def _read_pricelist(file_path: str) -> str:
    """Прочитать прайс-лист и вернуть в виде текста"""
    
    try:
        import pandas as pd
        if Path(file_path).exists():
            df = pd.read_excel(file_path, nrows=100)
            return df.to_string()
    except:
        pass
    
    return "(прайс-лист не найден или ошибка при чтении)"
