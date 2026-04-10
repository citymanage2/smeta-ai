# Правило: изменения моделей БД

При любом изменении `backend/app/models/*.py` — сразу создать файл миграции в `backend/alembic/versions/0NN_описание.py` (следующий номер по порядку, сейчас последняя — `011`).

Всегда использовать `op.execute("ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...")` — IF NOT EXISTS обязателен.

Шаблон: смотри любой существующий файл в `backend/alembic/versions/`, например `011_add_task_progress_data.py`.

Коммит и пуш — только после создания миграции.
