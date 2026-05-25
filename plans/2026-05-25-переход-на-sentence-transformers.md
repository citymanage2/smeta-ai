# План перехода на sentence-transformers

**Дата:** 2026-05-25  
**Причина:** Cohere API trial закончился (1000 вызовов/месяц), матчинг материалов перестал работать.

---

## Текущее состояние

- `backend/app/services/embedding_service.py` — единственная точка интеграции с Cohere
- Модель: `embed-multilingual-v3.0`, размерность **1024**
- Используется в: `admin.py` (генерация при загрузке прайса), `prices_catalog.py` (поиск)
- Cohere `input_type`: `"search_document"` при индексации, `"search_query"` при поиске

---

## Фазы

### Фаза 1: Замена embedding_service.py [ ]

Меняем только `embedding_service.py`. Интерфейс функций остаётся идентичным — остальной код не трогаем.

**Выбор модели:**

| Модель | Размерность | RAM | Качество RU | Скорость CPU |
|---|---|---|---|---|
| `intfloat/multilingual-e5-large` | 1024 | ~1.5 GB | ★★★★★ | медленная |
| `intfloat/multilingual-e5-base` | 768 | ~500 MB | ★★★★ | средняя |
| `paraphrase-multilingual-MiniLM-L12-v2` | 384 | ~200 MB | ★★★ | быстрая |

**Рекомендация для Render:** начать с `multilingual-e5-base` (500 MB RAM, размерность 768).  
Если RAM не хватает — `MiniLM` (200 MB).

> ⚠️ При смене размерности (1024 → 768 или → 384) нужно пересоздать колонку `embedding` в БД и перегенерировать все векторы. Проверить текущий тип колонки в моделях.

**Новый embedding_service.py:**

```python
"""
Сервис для генерации embedding-векторов через sentence-transformers.
Модель загружается один раз при старте (singleton).
"""
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Менять здесь — автоматически применится везде
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
EMBEDDING_DIMENSION = 768  # зависит от модели
BATCH_SIZE = 64


class EmbeddingUnavailableError(Exception):
    """Модель не загружена или ошибка инференса."""


_model = None
_model_lock = threading.Lock()


def _get_model():
    """Загружает модель один раз, thread-safe."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
            _model = SentenceTransformer(EMBEDDING_MODEL)
            logger.info("Embedding model loaded successfully")
            return _model
        except Exception as e:
            raise EmbeddingUnavailableError(f"Не удалось загрузить модель: {e}") from e


def generate_embedding(text: str, input_type: str = "search_document") -> list[float]:
    """
    Генерирует embedding для одного текста.
    input_type игнорируется (совместимость с Cohere-интерфейсом).
    """
    return generate_embeddings_batch([text], input_type=input_type)[0]


def generate_embeddings_batch(
    texts: list[str],
    input_type: str = "search_document",
) -> list[list[float]]:
    """
    Генерирует embeddings для списка текстов.
    Автоматически разбивает на батчи по BATCH_SIZE.
    """
    if not texts:
        return []

    # multilingual-e5 требует префикс для лучшего качества
    if "e5" in EMBEDDING_MODEL:
        prefix = "passage: " if input_type == "search_document" else "query: "
        texts = [prefix + t for t in texts]

    try:
        model = _get_model()
        all_embeddings = []
        for i in range(0, len(texts), BATCH_SIZE):
            chunk = texts[i:i + BATCH_SIZE]
            vecs = model.encode(chunk, normalize_embeddings=True)
            all_embeddings.extend(vecs.tolist())
        return all_embeddings
    except EmbeddingUnavailableError:
        raise
    except Exception as e:
        logger.error("Ошибка embedding инференса: %s", e)
        raise EmbeddingUnavailableError(f"Ошибка инференса: {e}") from e
```

**Изменения в requirements.txt:**
```
# Убрать:
cohere>=5.0.0

# Добавить:
sentence-transformers>=3.0.0
```

**Изменения в config.py:**
```python
# Убрать:
COHERE_API_KEY: str = ""
```

### Фаза 2: Проверка размерности в БД [ ]

Найти модели где хранится `embedding` колонка и проверить тип:

```bash
grep -rn "embedding" backend/app/models/ --include="*.py"
```

Если размерность изменится (например с 1024 на 768) — создать миграцию:

```python
# alembic/versions/0NN_update_embedding_dimension.py
def upgrade():
    op.alter_column('price_list_materials', 'embedding',
        type_=postgresql.ARRAY(sa.Float()),  # или Vector(768)
        existing_nullable=True)
    # То же для price_list_works
```

### Фаза 3: Перегенерация эмбеддингов [ ]

После деплоя — через админку нажать "Перегенерировать эмбеддинги" для всех прайс-листов.  
Это уже есть в `admin.py` — `generate_embeddings_batch`.

### Фаза 4: Тест качества матчинга [ ]

Проверить несколько запросов через каталог цен и убедиться что похожие материалы находятся корректно.

---

## Итог

- [ ] Фаза 1: замена embedding_service.py
- [ ] Фаза 2: миграция если изменилась размерность  
- [ ] Фаза 3: перегенерация эмбеддингов в проде
- [ ] Фаза 4: тест качества

---

---

# Как обучать модель похожести на своём корпусе смет

> Отдельный раздел — к реализации после накопления данных (~500+ пар).

## Зачем это нужно

Стандартная модель обучена на общем тексте интернета. Она не знает:
- Что "ГВЛ Кнауф 12мм" = "гипсоволокнистый лист 12" = "ГВЛВ 12мм Knauf"
- Что "демонтаж стяжки" ≠ "устройство стяжки" (противоположные операции)
- Специфические аббревиатуры: ж/б, НКТ, ТМЦ, ЛМК и т.д.

После дообучения модель начнёт понимать вашу предметную область.

---

## Шаг 1: Сбор обучающих данных

Нужны пары текстов с меткой "похоже" / "непохоже". Три источника:

### Источник А: Из истории матчинга (автоматически)

Каждый раз когда Claude успешно матчит материал из сметы с позицией прайса — это уже готовая обучающая пара:

```python
# Положительная пара (anchor, positive) — одно и то же
("кирпич керамический полнотелый М150", "кирпич М150 рядовой полнотелый")

# Эти данные уже есть в вашей БД после каждой обработанной сметы
```

### Источник Б: Ручная разметка через интерфейс

Добавить в админку простую форму: показываем пару "запрос из сметы → найденный материал", пользователь нажимает ✅ (верно) или ❌ (неверно).

```
Запрос: "арматура А500 D12 6м"
Найдено: "арматура рифлёная 12мм А500С"
[✅ Верно] [❌ Неверно — показать правильный вариант]
```

### Источник В: Синтетические пары через Claude

Для старта, когда данных мало — попросить Claude сгенерировать синонимы:

```python
prompt = """
Для каждого названия стройматериала дай 3-4 синонима/сокращения:

Кирпич керамический полнотелый М150 →
- кирпич М-150 рядовой
- кирпич полнотелый красный 150
- к.к. М150 пустотелый

Продолжай для: {материал}
"""
```

---

## Шаг 2: Формат датасета

sentence-transformers принимает несколько форматов. Лучший для вашей задачи — **triplets**:

```python
from sentence_transformers import InputExample

# Триплет: (anchor, positive, negative)
# anchor — запрос из сметы
# positive — правильный матч из прайса
# negative — неправильный похожий матч

training_examples = [
    InputExample(texts=[
        "арматура А500 D12",          # anchor
        "арматура рифлёная 12мм А500С",  # positive (правильный)
        "арматура А240 D12",            # negative (похожий, но другая марка!)
    ]),
    InputExample(texts=[
        "демонтаж цементной стяжки",   # anchor
        "разборка стяжки пола",         # positive
        "устройство цементной стяжки",  # negative (противоположная операция)
    ]),
    # ... 500+ примеров
]
```

Если негативов нет — можно использовать **pairs** с меткой схожести:

```python
from sentence_transformers import InputExample

training_examples = [
    InputExample(texts=["ГВЛ Кнауф 12мм", "гипсоволокнистый лист 12"], label=1.0),  # одно и то же
    InputExample(texts=["ГВЛ 12мм", "ГКЛ 12мм Кнауф"], label=0.3),  # похоже, но разные материалы
    InputExample(texts=["демонтаж стяжки", "устройство стяжки"], label=0.0),  # противоположное
]
```

---

## Шаг 3: Код обучения

```python
# train_embedding_model.py
# Запускать локально (не на Render), нужен GPU или мощный CPU

from sentence_transformers import SentenceTransformer, losses
from sentence_transformers import InputExample
from torch.utils.data import DataLoader
import json

# 1. Загружаем базовую модель
model = SentenceTransformer("intfloat/multilingual-e5-base")

# 2. Загружаем обучающие данные
with open("training_data.json") as f:
    raw = json.load(f)

# Формат JSON:
# [{"anchor": "...", "positive": "...", "negative": "..."}, ...]

train_examples = [
    InputExample(texts=[d["anchor"], d["positive"], d["negative"]])
    for d in raw
]

# 3. DataLoader
train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=16)

# 4. Loss функция — TripletLoss для триплетов
# Учит: anchor должен быть ближе к positive, чем к negative
train_loss = losses.TripletLoss(model=model)

# Альтернатива если используете pairs с метками:
# train_loss = losses.CosineSimilarityLoss(model=model)

# 5. Обучение
model.fit(
    train_objectives=[(train_dataloader, train_loss)],
    epochs=3,                    # обычно 3-5 эпох достаточно
    warmup_steps=100,
    output_path="./smeta-embedding-model",
    show_progress_bar=True,
)

print("Модель сохранена в ./smeta-embedding-model")
```

---

## Шаг 4: Оценка качества

Перед деплоем проверяем что модель стала лучше:

```python
from sentence_transformers import SentenceTransformer
from sentence_transformers.evaluation import TripletEvaluator

# Тестовые триплеты (отдельно от обучающих!)
test_examples = [
    InputExample(texts=["кирпич М150", "кирпич керамический 150", "кирпич М200"]),
    # ...
]

# Оцениваем базовую модель
base_model = SentenceTransformer("intfloat/multilingual-e5-base")
finetuned_model = SentenceTransformer("./smeta-embedding-model")

evaluator = TripletEvaluator.from_input_examples(test_examples)

base_score = evaluator(base_model)
finetuned_score = evaluator(finetuned_model)

print(f"Базовая модель: {base_score:.3f}")
print(f"Дообученная:    {finetuned_score:.3f}")
# Ожидаем рост на 5-15% при хорошем датасете
```

---

## Шаг 5: Деплой дообученной модели

```python
# В embedding_service.py поменять одну строчку:

# Было:
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"

# Стало (путь к локальной модели или HuggingFace Hub):
EMBEDDING_MODEL = "./smeta-embedding-model"
# или загрузить на HuggingFace Hub и использовать как обычную модель
```

После деплоя — перегенерировать все эмбеддинги через админку.

---

## Когда начинать дообучение

| Условие | Стоит начинать? |
|---|---|
| < 100 пар | Нет, слишком мало |
| 100–500 пар | Можно попробовать, результат нестабильный |
| 500–2000 пар | ✅ Хороший старт |
| 2000+ пар | ✅✅ Уверенный прирост качества |

**Практический ориентир:** после обработки ~50-100 смет у вас накопится достаточно данных для первого дообучения.

---

## Итоговая архитектура после дообучения

```
Новая смета (xlsx)
       ↓
  normalize_name()
       ↓
  query embedding (дообученная модель)
       ↓
  cosine similarity с прайсом
       ↓
  top-3 кандидата → Claude выбирает лучший
```
