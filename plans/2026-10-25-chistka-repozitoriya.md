# План: очистка репозитория

**Статус:** in progress
**Связан:** `plans/2026-10-25-chistka-testov.md` (тесты чистятся отдельно)

## Зачем

Перед расширением системы (управление стройпроектами) убрать из репозитория то,
что к smeta-ai не относится или осталось от прошлых эпох: инструменты, деплой на
Render, разовые скрипты, снимки данных.

## Фазы

### Фаза 1: Obsidian
- **Статус:** [x] (25.10.2026, коммит c5d2368)
- Удалены `.obsidian/` и пустой `Без названия.base`; `.obsidian/` в `.gitignore`.

### Фаза 2: Кандидаты
- **Статус:** частично (25.10.2026). Render погашен (подтвердил пользователь) —
  удалены его остатки и тест `test_spa_routing.py`, проверявший `render.yaml`.
  Удалены `skills/`, `progress/`, флаер, снимки прайсов, разовые скрипты. Хук
  `.git/hooks/post-push` удалён локально. `docs/` не тронут (инструкция
  пользователя). `tg_bot/` удалён — пользователь им не пользуется.

### Фаза 2б: Функция «Перевод смет»
- **Статус:** [x] 25.10.2026, решение пользователя
- Разовый перевод смет выполнен 04.08.2026 (`plans/2026-08-03-migraciya-smet-iz-adminki.md`).
  Кнопка «взять из расчёта» после этого затирала бы ручные правки сметы выводом ИИ
  (правило №1: `progress_data['items']` заморожен как ответ модели).
- Удалены: эндпоинты `/admin/estimates/migration*` (`routers/admin.py`),
  `services/estimate_migration.py`, `scripts/migrate_estimate_items.py`, вкладка
  и `EstimateMigrationPanel.tsx`, функции в `api/admin.ts`, тесты
  `test_estimate_migration_api.py`, `test_migrate_estimate_items.py`,
  `estimateMigrationPanel.test.tsx`.
- Оставлено: `estimate_rows.items_total` — им пользуется сверка раздела сводной
  со сметой; два теста «итог по позициям = итог файла» перенесены в
  `test_estimate_single_source.py::TestTotalsMatchFile`. Записи истории
  `estimate_migration` в БД остаются как есть.
- Попутно: неиспользуемый импорт в `services/kp_pricing.py` (ruff по `app/` зелёный).

| Что | Что это | Предложение |
|---|---|---|
| `skills/` | 17 навыков, скопированных из anthropics/skills 16.03.2026. Claude Code берёт навыки только из `.claude/skills/`, код на папку не ссылается | удалить |
| `tg_bot/` | личный Telegram-бот, пишет заметки в Obsidian-хранилище через Claude API; к smeta-ai не относится | удалить или вынести в свой репозиторий |
| `render.yaml`, `scripts/watch-render-deploy.sh`, `scripts/install-hooks.sh`, `backend/nixpacks.toml`, `backend/scripts/fix_production_db.py`, `backend/tests/E2E_CHECKLIST.md` | деплой на Render; прод на Timeweb (`Dockerfile` + `docker-compose.yml`). Хук `post-push` в `.git/hooks` не срабатывает никогда — такого хука в git нет | удалить, если сервисы Render погашены |
| `flyer-citymanage.html` | рекламный флаер, апрель | удалить |
| `прайс_работ.xlsx`, `прайс_материалов.xlsx` | снимок прайсов, апрель; тест ссылается на них только комментарием | удалить |
| `progress/` | 3 передаточные записки июля–августа, содержание есть в `plans/` | удалить |
| `docs/` | `instruction/` — инструкция пользователя; остальное — разовые анализы мая | инструкцию оставить, анализы → `thoughts/research/` |
| `backend/scripts/backfill_files_to_s3.py`, `migrate_tasks_to_kanban.py` | разовые миграции, выполнены | удалить |

Не трогаем: `Сводная РЖД Техническая 87.xlsx`, `пример.xlsx` — рабочие файлы
пользователя вне git.

### Фаза 3: Найденное в коде
- **Статус:** частично
- [x] Фронт при сборке без `VITE_API_BASE_URL` ходил на `smeta-ai-backend.onrender.com`
  (5 мест) → общая `API_BASE_URL` в `api/client.ts`, по умолчанию тот же адрес,
  с которого открыта страница.
- `.claude/skills/bulletproof` записан в git ссылкой на чужой репозиторий
  (gitlink) без `.gitmodules`: в свежем клоне папка пустая, а навык обязателен по
  CLAUDE.md → положить файлами или оформить подмодулем.
- [x] CLAUDE.md: `render.yaml` убран из карты, прод — Timeweb.

## Итог

Реализован почти целиком: фазы 1, 2, 2б. Осталось: `.claude/skills/bulletproof`
(gitlink без `.gitmodules`).
