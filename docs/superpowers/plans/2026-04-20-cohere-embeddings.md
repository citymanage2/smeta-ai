# Cohere Embeddings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить OpenAI `text-embedding-3-small` на Cohere `embed-multilingual-v3.0` для семантического поиска по прайс-листу.

**Architecture:** Все изменения инкапсулированы в `embedding_service.py` — публичный интерфейс (`generate_embedding`, `generate_embeddings_batch`, `EmbeddingUnavailableError`) остаётся прежним. `price_service.py` получает только добавление `input_type="search_query"` в вызовы. Alembic-миграция сбрасывает `embedding_status` в `pending`, чтобы сигнализировать о необходимости перегенерации.

**Tech Stack:** `cohere>=5.0.0`, Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL, Alembic.

---

## Файлы изменений

| Файл | Действие |
|---|---|
| `backend/requirements.txt` | заменить `openai>=1.0.0` → `cohere>=5.0.0` |
| `backend/app/config.py` | добавить `COHERE_API_KEY: str = ""` |
| `backend/app/services/embedding_service.py` | полная замена реализации |
| `backend/app/services/price_service.py` | добавить `input_type="search_query"` в 2 вызова |
| `backend/alembic/versions/012_reset_embedding_status.py` | новая миграция |
| `render.yaml` | заменить `OPENAI_API_KEY` → `COHERE_API_KEY` |
| `backend/tests/test_embedding_service.py` | обновить моки: openai → cohere, размерность 1536 → 1024 |
| `backend/tests/test_price_service_embedding.py` | обновить DIM: 1536 → 1024 |
| `backend/tests/test_generate_embeddings_endpoint.py` | обновить FAKE_VECTOR: 1536 → 1024 |

---

## Task 1: Зависимости и конфиг

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/config.py`
- Modify: `render.yaml`

- [ ] **Step 1: Заменить openai на cohere в requirements.txt**

В `backend/requirements.txt` найти строку `openai>=1.0.0` и заменить на:
```
cohere>=5.0.0
```

- [ ] **Step 2: Добавить COHERE_API_KEY в config.py**

В `backend/app/config.py` добавить поле после `OPENAI_API_KEY`:
```python
COHERE_API_KEY: str = ""
```

Итоговый класс Settings:
```python
class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    COHERE_API_KEY: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost/smeta_ai"
    JWT_SECRET: str = "changeme-use-strong-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    USER_PASSWORD: str = "user123"
    ADMIN_PASSWORD: str = "admin123"
    MAX_FILE_SIZE_MB: int = 20
    MAX_FILES_PER_REQUEST: int = 10
    TASK_TIMEOUT_SECONDS: int = 600
    CORS_ORIGINS: str = "*"
    ...
```

- [ ] **Step 3: Обновить render.yaml**

Заменить:
```yaml
      - key: OPENAI_API_KEY
        sync: false
```
на:
```yaml
      - key: COHERE_API_KEY
        sync: false
```

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt backend/app/config.py render.yaml
git commit -m "chore: replace openai with cohere dependency, add COHERE_API_KEY config"
```

---

## Task 2: Alembic-миграция сброса embedding_status

**Files:**
- Create: `backend/alembic/versions/012_reset_embedding_status.py`

Цель: сигнализировать что старые OpenAI-векторы (1536 мер) устарели. После деплоя нужно нажать «Перегенерировать» в Admin.

- [ ] **Step 1: Создать файл миграции**

Создать `backend/alembic/versions/012_reset_embedding_status.py`:

```python
"""Reset embedding_status to pending after switching to Cohere

Revision ID: 012
Revises: 011
Create Date: 2026-04-20 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE price_lists SET embedding_status = 'pending'")


def downgrade() -> None:
    pass
```

- [ ] **Step 2: Commit**

```bash
git add backend/alembic/versions/012_reset_embedding_status.py
git commit -m "db: миграция сброса embedding_status при переходе на Cohere"
```

---

## Task 3: Переписать embedding_service.py

**Files:**
- Modify: `backend/app/services/embedding_service.py`

Интерфейс не меняется: `normalize_name`, `generate_embedding`, `generate_embeddings_batch`, `EmbeddingUnavailableError` — те же имена.
Добавляется параметр `input_type` в `generate_embedding` и `generate_embeddings_batch`.
Размерность: 1024 (вместо 1536).
Batch limit: 96 (Cohere v3 embed ограничение на практике).

- [ ] **Step 1: Написать failing тест (новый мок Cohere)**

В `backend/tests/test_embedding_service.py` полностью заменить содержимое:

```python
"""Unit tests for embedding_service: normalize_name и generate_embeddings_batch (Cohere)."""
import sys
import pytest
from unittest.mock import patch, MagicMock

# Мокируем cohere до импорта embedding_service
_cohere_mock = MagicMock()
sys.modules.setdefault("cohere", _cohere_mock)

from app.services.embedding_service import (
    normalize_name,
    generate_embeddings_batch,
    generate_embedding,
    EmbeddingUnavailableError,
)

DIM = 1024


# ---------------------------------------------------------------------------
# normalize_name (без изменений — тесты должны пройти)
# ---------------------------------------------------------------------------

def test_normalize_m_defi_100():
    assert normalize_name("M defi 100") == "м100"

def test_normalize_m_dash_50():
    assert normalize_name("М-50") == "м50"

def test_normalize_extra_spaces():
    assert normalize_name("  Кладка  кирпичная  ") == "кладка кирпичная"

def test_normalize_empty_string():
    assert normalize_name("") == ""

def test_normalize_m100_lowercase():
    assert normalize_name("М100") == "м100"

def test_normalize_m_defi_100_equals_m100():
    assert normalize_name("M defi 100") == normalize_name("М100")

def test_normalize_m100_not_equals_m50():
    assert normalize_name("М100") != normalize_name("М50")

def test_normalize_latin_m_to_cyrillic():
    assert normalize_name("M100") == "м100"


# ---------------------------------------------------------------------------
# generate_embeddings_batch (Cohere mock)
# ---------------------------------------------------------------------------

def _make_cohere_client_mock(count: int, dim: int = DIM) -> MagicMock:
    """Возвращает mock клиента Cohere с правильным форматом ответа."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.embeddings.float_ = [
        [float(i % 10) / 10.0 + 0.1] * dim for i in range(count)
    ]
    mock_client.embed.return_value = mock_response
    return mock_client


def test_generate_embeddings_batch_success():
    """Успешная генерация: возвращает вектор для каждого текста."""
    texts = ["кладка кирпичная", "штукатурка", "бетонирование"]
    mock_client = _make_cohere_client_mock(len(texts))

    with patch("app.services.embedding_service._get_cohere_client", return_value=mock_client):
        result = generate_embeddings_batch(texts)

    assert len(result) == 3
    assert all(len(v) == DIM for v in result)
    mock_client.embed.assert_called_once()


def test_generate_embeddings_batch_empty_input():
    """Пустой список → пустой результат без вызовов API."""
    result = generate_embeddings_batch([])
    assert result == []


def test_generate_embeddings_batch_api_error_raises():
    """Любая ошибка Cohere API → EmbeddingUnavailableError."""
    mock_client = MagicMock()
    mock_client.embed.side_effect = RuntimeError("connection timeout")

    with patch("app.services.embedding_service._get_cohere_client", return_value=mock_client):
        with pytest.raises(EmbeddingUnavailableError):
            generate_embeddings_batch(["тест"])


def test_generate_embeddings_batch_passes_input_type():
    """input_type передаётся в Cohere API."""
    texts = ["запрос"]
    mock_client = _make_cohere_client_mock(1)

    with patch("app.services.embedding_service._get_cohere_client", return_value=mock_client):
        generate_embeddings_batch(texts, input_type="search_query")

    call_kwargs = mock_client.embed.call_args.kwargs
    assert call_kwargs["input_type"] == "search_query"


def test_generate_embeddings_batch_default_input_type_is_document():
    """По умолчанию input_type='search_document'."""
    texts = ["документ"]
    mock_client = _make_cohere_client_mock(1)

    with patch("app.services.embedding_service._get_cohere_client", return_value=mock_client):
        generate_embeddings_batch(texts)

    call_kwargs = mock_client.embed.call_args.kwargs
    assert call_kwargs["input_type"] == "search_document"


def test_generate_embedding_single_returns_first_vector():
    """generate_embedding возвращает первый вектор из батча."""
    mock_client = _make_cohere_client_mock(1)

    with patch("app.services.embedding_service._get_cohere_client", return_value=mock_client):
        result = generate_embedding("тест", input_type="search_query")

    assert len(result) == DIM


def test_no_api_key_raises():
    """COHERE_API_KEY не задан → EmbeddingUnavailableError."""
    with patch("app.services.embedding_service._get_cohere_client",
               side_effect=EmbeddingUnavailableError("COHERE_API_KEY не настроен")):
        with pytest.raises(EmbeddingUnavailableError, match="COHERE_API_KEY"):
            generate_embedding("тест")
```

- [ ] **Step 2: Запустить тесты — убедиться что падают**

```bash
cd backend && python -m pytest tests/test_embedding_service.py -v 2>&1 | tail -20
```

Ожидание: FAIL (функции ещё используют OpenAI).

- [ ] **Step 3: Переписать embedding_service.py**

Полностью заменить содержимое `backend/app/services/embedding_service.py`:

```python
"""
Сервис для генерации embedding-векторов через Cohere.

Используется для семантического поиска по прайс-листу.
Векторы генерируются один раз при загрузке прайса и хранятся в БД.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "embed-multilingual-v3.0"
EMBEDDING_DIMENSION = 1024
COHERE_BATCH_LIMIT = 96  # максимум текстов за один API-вызов для v3 моделей


class EmbeddingUnavailableError(Exception):
    """Cohere недоступен или ключ не настроен."""


def normalize_name(text: str) -> str:
    """
    Нормализует название позиции перед генерацией embedding.

    Применять одинаково и при загрузке прайса, и при поиске из сметы.

    Правила:
    - Латинские буквы, визуально совпадающие с кириллическими → кириллица
    - Марки материалов: М-100, M defi 100, м 100 → М100
    - Двойные пробелы убираются, текст trim-ится
    - Результат — нижний регистр для сравнения
    """
    if not text:
        return ""

    _simple_lat_cyr = {
        'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К',
        'M': 'М', 'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х',
        'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х',
    }
    result = "".join(_simple_lat_cyr.get(ch, ch) for ch in text)

    result = re.sub(
        r'([А-ЯЁа-яёA-Za-z])\s*[-_]?\s*(?:[a-zA-Zа-яА-ЯёЁ]+\s+)*(\d+)',
        lambda m: m.group(1).upper() + m.group(2),
        result
    )

    result = " ".join(result.split())
    return result.lower()


def _get_cohere_client():
    """Создаёт Cohere клиент. Бросает EmbeddingUnavailableError если ключ не задан."""
    try:
        import cohere
        from app.config import settings

        if not settings.COHERE_API_KEY:
            raise EmbeddingUnavailableError("COHERE_API_KEY не настроен")

        return cohere.Client(api_key=settings.COHERE_API_KEY)
    except ImportError:
        raise EmbeddingUnavailableError("Библиотека cohere не установлена")


def generate_embedding(text: str, input_type: str = "search_document") -> list[float]:
    """
    Генерирует embedding-вектор для одного текста.

    input_type: "search_document" при индексации, "search_query" при поиске.
    Возвращает список из 1024 float.
    Бросает EmbeddingUnavailableError при ошибке API.
    """
    results = generate_embeddings_batch([text], input_type=input_type)
    return results[0]


def generate_embeddings_batch(
    texts: list[str],
    input_type: str = "search_document",
) -> list[list[float]]:
    """
    Генерирует embedding-векторы для списка текстов.

    input_type: "search_document" при индексации прайса, "search_query" при поиске запроса.
    Автоматически разбивает на чанки по COHERE_BATCH_LIMIT (96).
    Возвращает список векторов в том же порядке что и входные тексты.
    Бросает EmbeddingUnavailableError при ошибке API.
    """
    if not texts:
        return []

    try:
        client = _get_cohere_client()
        all_embeddings: list[list[float]] = []

        for chunk_start in range(0, len(texts), COHERE_BATCH_LIMIT):
            chunk = texts[chunk_start: chunk_start + COHERE_BATCH_LIMIT]
            response = client.embed(
                texts=chunk,
                model=EMBEDDING_MODEL,
                input_type=input_type,
                embedding_types=["float"],
            )
            all_embeddings.extend(response.embeddings.float_)

        return all_embeddings

    except EmbeddingUnavailableError:
        raise
    except Exception as e:
        logger.error("Ошибка Cohere embeddings API: %s", e)
        raise EmbeddingUnavailableError(f"Ошибка Cohere API: {e}") from e
```

- [ ] **Step 4: Запустить тесты — убедиться что проходят**

```bash
cd backend && python -m pytest tests/test_embedding_service.py -v 2>&1 | tail -25
```

Ожидание: все тесты PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/embedding_service.py backend/tests/test_embedding_service.py
git commit -m "feat: заменить OpenAI на Cohere embed-multilingual-v3.0"
```

---

## Task 4: Обновить вызовы в price_service.py

**Files:**
- Modify: `backend/app/services/price_service.py` (строки ~68–71 и ~96–99)

Нужно передать `input_type="search_query"` в оба вызова `generate_embedding`.

- [ ] **Step 1: Обновить _embedding_match_work (строка ~71)**

Найти в `price_service.py`:
```python
query_vec = await asyncio.to_thread(generate_embedding, normalized)
```
(в функции `_embedding_match_work`)

Заменить на:
```python
query_vec = await asyncio.to_thread(generate_embedding, normalized, "search_query")
```

- [ ] **Step 2: Обновить _embedding_match_material (строка ~99)**

Найти в `price_service.py`:
```python
query_vec = await asyncio.to_thread(generate_embedding, normalized)
```
(в функции `_embedding_match_material`)

Заменить на:
```python
query_vec = await asyncio.to_thread(generate_embedding, normalized, "search_query")
```

- [ ] **Step 3: Обновить тест test_price_service_embedding.py — DIM 1536 → 1024**

В `backend/tests/test_price_service_embedding.py` найти:
```python
DIM = 1536
```
Заменить на:
```python
DIM = 1024
```

- [ ] **Step 4: Запустить тесты price_service**

```bash
cd backend && python -m pytest tests/test_price_service_embedding.py -v 2>&1 | tail -20
```

Ожидание: все тесты PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/price_service.py backend/tests/test_price_service_embedding.py
git commit -m "fix: передавать input_type=search_query при поиске в прайсе"
```

---

## Task 5: Обновить endpoint-тест

**Files:**
- Modify: `backend/tests/test_generate_embeddings_endpoint.py`

- [ ] **Step 1: Обновить FAKE_VECTOR и мок в тесте**

В `backend/tests/test_generate_embeddings_endpoint.py` найти:
```python
FAKE_VECTOR = [0.1] * 1536
```
Заменить на:
```python
FAKE_VECTOR = [0.1] * 1024
```

Затем найти все `patch` на `generate_embeddings_batch` или `_get_openai_client` — убедиться что они мокируют на уровне `embedding_service.generate_embeddings_batch`, а не через OpenAI клиент напрямую. Если там есть `_get_openai_client` — заменить на `_get_cohere_client`.

- [ ] **Step 2: Запустить endpoint-тест**

```bash
cd backend && python -m pytest tests/test_generate_embeddings_endpoint.py -v 2>&1 | tail -20
```

Ожидание: все тесты PASS.

- [ ] **Step 3: Запустить полный тест-сьют**

```bash
cd backend && python -m pytest --tb=short 2>&1 | tail -30
```

Ожидание: все тесты PASS (или те же тесты что были зелёными до начала работы).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_generate_embeddings_endpoint.py
git commit -m "test: обновить тесты endpoint под Cohere (DIM=1024)"
```

---

## Финальная проверка

- [ ] Убедиться что `.env` содержит `COHERE_API_KEY=...` (если есть ключ для локального запуска)
- [ ] Добавить `COHERE_API_KEY` в render.yaml secrets на Render.com
- [ ] После деплоя — нажать «Перегенерировать векторы» в Admin-панели (миграция 012 сбросит статус в pending)
