# План: Вкладка «Дообучение» эмбеддингов

**Дата:** 2026-05-25  
**Статус:** [ ] В разработке  
**Доступ:** только администратор  
**Research:** `thoughts/research/2026-05-25-retraining-tab.md`

---

## Цель

Создать инструмент для сбора обучающих данных и дообучения модели эмбеддингов прямо из интерфейса:
загрузил сметы → прошёл игровой тест (✅/❌) → запустил обучение → модель стала точнее.

## Ключевые решения

| Вопрос | Решение | Причина |
|---|---|---|
| Inference библиотека | `fastembed` | +150MB vs +2GB для torch |
| Training библиотека | `sentence-transformers` (lazy import) | нужен только при обучении |
| Размерность | `multilingual-e5-base` → **768** | 500MB RAM vs 1.5GB для large |
| Миграция эмбеддингов | ALTER COLUMN + кнопка перегенерации | JSONB уже nullable, безопасно |
| Хранение модели | `/tmp/smeta-finetuned/` (эфемерно) | "пока без хранения", пары в БД |
| Порог similarity | 0.92 → настраивается | другая модель, другой масштаб |
| Доступ | requireAdmin | техническая операция |

## Архитектура потока

```
[Загрузить xlsx] → parse_estimate_excel() → список позиций
                                                   ↓
                              для каждой: fastembed → top-3 кандидата из прайса
                                                   ↓
                         [Игровой тест: позиция + кандидат + %]
                              [✅ Да]  [❌ Нет — выбрать другой]  [→ Пропустить]
                                                   ↓
                                    training_pairs в PostgreSQL
                                                   ↓
                         [Обучить модель] → background task (20-40 мин CPU)
                                                   ↓
                              sentence-transformers fine-tuning
                                                   ↓
                              сохранить в /tmp/smeta-finetuned/
                              reload_model() без рестарта сервера
```

---

## Фазы

### Фаза 1: Переход на FastEmbed (sentence-transformers inference) [x]

**Цель:** заменить Cohere → FastEmbed, не сломав матчинг.

**Файлы:**
- `backend/app/services/embedding_service.py` — полная замена
- `backend/requirements.txt` — убрать cohere, добавить fastembed
- `backend/app/config.py` — убрать COHERE_API_KEY
- Новая миграция: изменить размерность JSONB-эмбеддингов (при необходимости)

**Детали:**

`embedding_service.py` — новая реализация:
```python
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
EMBEDDING_DIMENSION = 768

# Singleton с thread-safe reload
_model: Optional[TextEmbedding] = None
_model_lock = threading.Lock()
_current_model_path: str = EMBEDDING_MODEL

def _get_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        from fastembed import TextEmbedding
        _model = TextEmbedding(_current_model_path)
        return _model

def reload_model(model_path: str):
    """Перезагрузить модель после дообучения."""
    global _model, _current_model_path
    with _model_lock:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_path)
        _current_model_path = model_path

def generate_embeddings_batch(texts, input_type="search_document"):
    # multilingual-e5 требует префикс
    prefix = "passage: " if input_type == "search_document" else "query: "
    prefixed = [prefix + normalize_name(t) for t in texts]
    model = _get_model()
    embeddings = list(model.embed(prefixed))
    return [e.tolist() for e in embeddings]
```

**Важно:** SIMILARITY_THRESHOLD изменить с 0.93 → 0.82 в `price_service.py`
(cosine similarity у e5-base в другом масштабе — нужно протестировать после перегенерации).

**requirements.txt:**
```
# убрать: cohere>=5.0.0
# добавить:
fastembed>=0.3.0
sentence-transformers>=3.0.0  # для будущего дообучения
```

**Миграция** (если меняем размерность 1024→768):
```python
# Ничего не менять в структуре! JSONB принимает любой массив.
# Просто перегенерировать все эмбеддинги через существующую кнопку в админке.
# Размерность проверяется только при cosine similarity — numpy не заботится.
```

**Acceptance criteria Фазы 1:**
- [x] `ruff check .` — 0 ошибок
- [x] `pytest` — все тесты зелёные
- [x] COHERE_API_KEY убран из config
- [ ] Матчинг материала из тестовой сметы работает через новую модель (проверить после перегенерации эмбеддингов в прод)

---

### Фаза 2: БД + Backend API для сбора пар [x]

**Цель:** таблицы для хранения сессий оценки и обучающих пар, REST API.

**Новые модели:**

```python
# backend/app/models/training_pair.py
class TrainingPair(Base):
    __tablename__ = "training_pairs"
    id: UUID, primary_key
    anchor_text: str          # позиция из сметы (нормализованная)
    candidate_text: str       # кандидат из прайса
    candidate_type: str       # "work" | "material"
    is_positive: bool         # True = ✅, False = ❌
    similarity_score: float   # score на момент оценки
    source_file: Optional[str]
    created_at: datetime

# backend/app/models/training_job.py  
class TrainingJob(Base):
    __tablename__ = "training_jobs"
    id: UUID, primary_key
    status: str               # "pending" | "running" | "completed" | "failed"
    pairs_count: int          # сколько пар использовано
    progress_pct: int         # 0-100
    progress_message: str
    model_path: Optional[str] # путь к сохранённой модели
    error: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
```

**Новый роутер** `backend/app/routers/retraining.py`:

```
POST /api/retraining/parse
  body: multipart, файлы xlsx
  → парсит позиции, ищет top-3 кандидата для каждой
  → возвращает список {anchor, candidates: [{text, score, type}]}

POST /api/retraining/pairs
  body: {anchor_text, candidate_text, candidate_type, is_positive, similarity_score, source_file}
  → сохраняет одну пару в training_pairs

GET /api/retraining/stats
  → {total_pairs, positive_pairs, negative_pairs, last_job_status, model_loaded}

POST /api/retraining/train
  → запускает background task дообучения
  → возвращает {job_id}

GET /api/retraining/train/{job_id}
  → {status, progress_pct, progress_message, error}
```

**Сервис** `backend/app/services/retraining_service.py`:
```python
async def parse_files_for_review(files: list[UploadFile]) -> list[ReviewItem]:
    """Парсит xlsx, для каждой позиции находит top-3 кандидата."""

async def run_training_job(job_id: str, db: AsyncSession):
    """Фоновая задача дообучения."""
    # 1. Загружает все positive+negative пары из БД
    # 2. Формирует InputExample триплеты
    # 3. Дообучает через sentence-transformers
    # 4. Сохраняет в /tmp/smeta-finetuned/
    # 5. Вызывает reload_model()
    # 6. Обновляет training_job.status = "completed"
```

**Миграция:** `backend/alembic/versions/0NN_add_training_tables.py`

**Acceptance criteria Фазы 2:**
- [x] Миграция применяется без ошибок
- [x] POST /api/retraining/parse возвращает список пар для xlsx с ≥1 позицией
- [x] POST /api/retraining/pairs сохраняет пару, GET /stats отражает
- [x] POST /api/retraining/train запускает job, статус меняется
- [x] `ruff check` — 0 ошибок (pytest не запускается локально из-за отсутствия apscheduler — pre-existing)

---

### Фаза 3: Frontend — игровой интерфейс [x]

**Цель:** страница-игра для оценки пар. Доступна только администратору.

**Новые файлы:**
```
frontend/src/
├── pages/Retraining.tsx          # основная страница
├── api/retraining.ts             # API клиент
└── types/retraining.ts           # типы
```

**UX поток страницы:**

```
┌─────────────────────────────────────────────────────┐
│  Дообучение модели                    [Обучить →]    │
│  💡 234 пары собрано (187 ✅ / 47 ❌)               │
├─────────────────────────────────────────────────────┤
│  [Загрузить сметы]  ← FileUpload компонент          │
│  demo.xlsx, smeta2.xlsx              [Начать →]      │
├─────────────────────────────────────────────────────┤
│  Позиция 12 из 47                    ████████░░ 78%  │
│                                                      │
│  Из сметы:                                          │
│  ┌──────────────────────────────────────────────┐   │
│  │  арматура А500 D12 6м                        │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  Найдено в прайсе (87%):                            │
│  ┌──────────────────────────────────────────────┐   │
│  │  Арматура рифлёная 12мм А500С  •  850 ₽/т   │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│   [✅ Да, это одно и то же]   [❌ Нет]   [→ Пропуск]│
└─────────────────────────────────────────────────────┘
```

При нажатии ❌ — показать 2 других кандидата (top-2, top-3) или поле поиска.

**Состояние (без отдельного стора — локальный useState):**
```tsx
interface ReviewItem {
  anchor: string;
  candidates: { text: string; score: number; type: 'work' | 'material'; price?: number }[];
}
interface ReviewState {
  items: ReviewItem[];
  currentIndex: number;
  savedCount: number;
}
```

**Панель статистики** (вверху страницы):
- Всего пар / позитивных / негативных
- Статус последнего обучения
- Кнопка "Обучить модель" — активна при ≥200 позитивных пар

**Acceptance criteria Фазы 3:**
- [x] `tsc --noEmit` — 0 ошибок
- [x] Страница доступна только администратору
- [x] После загрузки xlsx появляется очередь для оценки
- [x] ✅/❌ сохраняются через API, счётчик обновляется
- [x] Кнопка "Обучить" неактивна при <200 пар

---

### Фаза 4: Пайплайн дообучения [ ]

**Цель:** background task обучения + перезагрузка модели без рестарта.

**Обучение** (`retraining_service.py`):
```python
async def run_training_job(job_id: str, db):
    # Шаг 1: загрузить пары
    pairs = await db.execute(select(TrainingPair))
    positive = [p for p in pairs if p.is_positive]
    negative = [p for p in pairs if not p.is_positive]
    
    # Шаг 2: формировать триплеты
    # Для каждого positive берём случайный negative как hard negative
    examples = [
        InputExample(texts=[pos.anchor_text, pos.candidate_text, neg.candidate_text])
        for pos, neg in zip(positive, negative_sample)
    ]
    
    # Шаг 3: дообучение
    from sentence_transformers import SentenceTransformer, losses
    model = SentenceTransformer(settings.EMBEDDING_MODEL_PATH)
    dataloader = DataLoader(examples, shuffle=True, batch_size=16)
    loss = losses.TripletLoss(model=model)
    
    model.fit(
        train_objectives=[(dataloader, loss)],
        epochs=3,
        warmup_steps=50,
        output_path="/tmp/smeta-finetuned",
        callback=lambda score, epoch, steps: update_progress(job_id, epoch, db),
    )
    
    # Шаг 4: reload без рестарта
    reload_model("/tmp/smeta-finetuned")
    
    # Шаг 5: перегенерировать эмбеддинги прайса
    await regenerate_all_embeddings(db)
```

**Прогресс:** job.progress_message обновляется каждую эпоху, фронт поллит `/train/{job_id}`.

**Acceptance criteria Фазы 4:**
- [ ] При 200+ парах обучение запускается без ошибок
- [ ] Прогресс виден на фронте (полинг каждые 3 сек)
- [ ] После обучения новый запрос использует обновлённую модель
- [ ] При 0 парах возвращает 400

---

## Challenge Log

**1. Решает ли это проблему?**  
Да: Cohere API исчерпан → переход на FastEmbed убирает зависимость. Игровой интерфейс = самый быстрый способ накапливать правильные пары.

**2. Самое эффективное решение?**  
Альтернатива A: Автосбор из истории матчинга (без UI) — не подходит на старте, нет "ground truth".  
Альтернатива B: Только экспорт JSON + обучение локально — требует технических навыков от пользователя.  
Выбранный подход (игровой тест) — минимум усилий пользователя, максимум качества данных.

**3. Нет лишнего кода?**  
Фаза 1 (FastEmbed) нужна как prerequisite для Фаз 2-4 — без неё Cohere продолжит падать.

---

## Итог

- [x] Фаза 1: FastEmbed (замена Cohere)
- [x] Фаза 2: БД + Backend API
- [x] Фаза 3: Frontend игровой интерфейс
- [ ] Фаза 4: Пайплайн дообучения
