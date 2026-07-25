FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc g++ libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
    libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info \
    fonts-dejavu-core \
    tesseract-ocr tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# CPU-only PyTorch: иначе sentence-transformers тянет CUDA-сборку torch с пакетами
# nvidia-* (~4-5 ГБ), бесполезными на сервере без GPU. Ставим CPU-колёса ПЕРВЫМИ —
# последующий requirements.txt увидит уже установленный torch и не переустановит его.
# Обычный inference идёт на fastembed (ONNX); torch нужен лишь для дообучения — на CPU ок.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
