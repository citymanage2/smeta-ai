from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from backend.database import get_db
from backend.models import Request, OutputFile
from backend.auth import get_current_admin

router = APIRouter()

@router.get("/requests")
async def get_all_requests(
    current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
    skip: int = Query(0),
    limit: int = Query(50),
    date_from: str = Query(None),
    date_to: str = Query(None)
):
    """Получить все запросы с фильтрацией по дате"""
    
    query = db.query(Request)
    
    # Фильтр по дате
    if date_from:
        try:
            start_date = datetime.fromisoformat(date_from)
            query = query.filter(Request.created_at >= start_date)
        except:
            pass
    
    if date_to:
        try:
            end_date = datetime.fromisoformat(date_to) + timedelta(days=1)
            query = query.filter(Request.created_at < end_date)
        except:
            pass
    
    total = query.count()
    requests = query.order_by(Request.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for req in requests:
        result.append({
            "id": req.id,
            "created_at": req.created_at.isoformat(),
            "input_type": req.input_type,
            "uploaded_files": req.uploaded_files,
            "requested_outputs": req.requested_outputs,
            "status": req.status,
            "output_files": req.output_files,
            "error_message": req.error_message
        })
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "requests": result
    }

@router.get("/request/{request_id}")
async def get_request_detail(
    request_id: int,
    current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Получить детали конкретного запроса"""
    
    request = db.query(Request).filter(Request.id == request_id).first()
    
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Запрос не найден"
        )
    
    return {
        "id": request.id,
        "created_at": request.created_at.isoformat(),
        "input_type": request.input_type,
        "uploaded_files": request.uploaded_files,
        "requested_outputs": request.requested_outputs,
        "status": request.status,
        "claude_prompt": request.claude_prompt,
        "claude_response": request.claude_response,
        "output_files": request.output_files,
        "error_message": request.error_message,
        "user_comment": request.user_comment
    }

@router.get("/export-csv")
async def export_history_csv(
    current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Экспортировать историю в CSV"""
    
    from fastapi.responses import StreamingResponse
    import csv
    import io
    
    requests = db.query(Request).order_by(Request.created_at.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Заголовок
    writer.writerow([
        "ID", "Дата", "Тип ввода", "Файлы", "Результаты", "Статус", "Ошибка"
    ])
    
    # Данные
    for req in requests:
        uploaded_files = ", ".join([f.get('name', '') for f in req.uploaded_files]) if req.uploaded_files else ""
        outputs = ", ".join(req.requested_outputs) if req.requested_outputs else ""
        
        writer.writerow([
            req.id,
            req.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            req.input_type,
            uploaded_files,
            outputs,
            req.status,
            req.error_message or ""
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=history.csv"}
    )

@router.get("/stats")
async def get_stats(
    current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Получить статистику по запросам"""
    
    total_requests = db.query(Request).count()
    successful = db.query(Request).filter(Request.status == "success").count()
    failed = db.query(Request).filter(Request.status == "error").count()
    
    # Популярные типы входных данных
    input_types = db.query(Request.input_type).all()
    type_counts = {}
    for (input_type,) in input_types:
        if input_type:
            type_counts[input_type] = type_counts.get(input_type, 0) + 1
    
    return {
        "total_requests": total_requests,
        "successful": successful,
        "failed": failed,
        "success_rate": round(100 * successful / total_requests, 2) if total_requests > 0 else 0,
        "input_types_distribution": type_counts
    }
