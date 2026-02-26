from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os
from dotenv import load_dotenv

# Загрузить переменные окружения
load_dotenv()

from backend.database import init_db
from backend.routes import auth, tasks, admin

app = FastAPI(
    title="Smeta AI",
    description="Веб-сервис для автоматизированного формирования смет и анализа проектов",
    version="1.0.0"
)

# CORS настройка
origins = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost",
    "https://smeta-ai.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация базы данных
init_db()

# Подключение маршрутов
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])

# Статические файлы фронтенда
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Smeta AI"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
