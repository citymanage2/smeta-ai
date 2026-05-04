# Дашборд «Система» — главный экран

**Дата:** 2026-05-04  
**Статус:** в планировании

## Цель

Реализовать главный экран «Система», который даёт оперативную картину работы сервиса: что в работе, где ошибки, какие проекты активны, насколько свежи прайсы, как распределена нагрузка по типам задач.

Экран предназначен для двух аудиторий: менеджер (операционный контроль) и разработчик (технический мониторинг).

---

## Архитектурные решения

- Новый роут фронтенда: `/system`
- Новый API-эндпоинт: `GET /dashboard/stats` — возвращает все агрегаты одним запросом
- Все данные этапа 1 берутся из существующих таблиц без изменений схемы БД
- Этап 2 требует новой таблицы `api_call_log` для трекинга стоимости Claude API
- Обновление данных: polling каждые 30 секунд для блоков с активной очередью

---

## Фазы

### Фаза 1. Бэкенд: эндпоинт `/dashboard/stats`

- [x] Создать роутер `backend/app/routers/dashboard.py`
- [x] Реализовать `GET /dashboard/stats` — агрегирует данные для всех блоков одним вызовом:
  - Счётчики задач за сегодня по статусам (pending / processing / completed / failed)
  - Список активных задач (status IN pending, processing) с полями: id, task_type, status, progress_message, created_at, project_id, project_name
  - Список failed-задач за последние 7 дней: id, task_type, error_message, created_at — сгруппированные по паттерну ошибки
  - Воронка качества за 30 дней: completed count, estimated count, manually_edited count → human_edit_rate
  - Карточки проектов: id, name, created_at, total_cost, дата последней запущенной задачи, разбивка задач по task_type внутри проекта
  - Orphan tasks count (задачи без проекта)
  - Статистика по типам задач: за последние 10 дней по дням — количество созданных по каждому task_type (для графика)
  - Прайс-листы: дата последнего обновления works / materials, embedding_status, count позиций
- [x] Подключить роутер в `backend/app/main.py`
- [x] Покрыть SQL-запросы индексами (проверить, что `created_at` проиндексирован) — ix_tasks_created_at, ix_tasks_status, ix_tasks_deleted_at уже существуют

### Фаза 2. Фронтенд: страница `/system`

- [ ] Создать страницу `frontend/src/pages/System.tsx`
- [ ] Добавить маршрут `/system` в `App.tsx` (защищённый, доступен всем ролям)
- [ ] Сделать `/system` страницей по умолчанию после логина: изменить редирект после успешного `POST /auth/login` с текущего (предположительно `/admin` или `/projects`) на `/system`
- [ ] Корневой маршрут `/` — редирект на `/system` для авторизованных пользователей
- [ ] Страница `/admin` остаётся без изменений, доступна через сайдбар как отдельная вкладка «Администрирование»
- [ ] Добавить ссылку «Система» в `ProjectsSidebar.tsx` первым пунктом навигации
- [ ] Создать API-клиент `frontend/src/api/dashboard.ts` с функцией `getDashboardStats()`
- [ ] Создать хук `useDashboardStats()` с polling каждые 30 секунд

#### Блок 1 — «Пульс сегодня»

- [ ] Компонент `DashboardPulse.tsx` — 4 KPI-карточки в ряд
  - Создано сегодня
  - В обработке прямо сейчас
  - Завершено сегодня
  - С ошибкой сегодня (красный если > 0)

#### Блок 2 — «Активная очередь»

- [ ] Компонент `DashboardQueue.tsx` — таблица активных задач
  - Колонки: тип задачи (человекочитаемый), проект, время в очереди (elapsed), прогресс-сообщение, статус
  - Алерт: processing > 15 мин → жёлтая строка; > 30 мин → красная строка
  - Алерт: pending > 5 мин → жёлтая строка
  - Кнопка «Отменить» для каждой задачи (вызов `POST /tasks/{id}/cancel`)

#### Блок 3 — «Журнал ошибок»

- [ ] Компонент `DashboardErrors.tsx` — таблица с группировкой по паттерну ошибки
  - Группировка: паттерн ошибки, тип задачи, количество, дата последней
  - Раскрытие группы: список конкретных задач с полным error_message
  - Кнопка «Перезапустить» → `POST /tasks/{id}/resume`
  - Кнопка «Скопировать ошибку» → копирует error_message в буфер
  - Переключатель периода: 1 день / 7 дней / 30 дней

#### Блок 4 — «Воронка качества»

- [ ] Компонент `DashboardFunnel.tsx` — funnel-диаграмма + KPI
  - Шаги: Создано → Завершено → Смета рассчитана → Правили вручную
  - KPI: Human Edit Rate (%) с цветовой индикацией (< 20% зелёный, 20-40% жёлтый, > 40% красный)
  - Период: последние 30 дней

#### Блок 5 — «Проекты»

- [ ] Компонент `DashboardProjects.tsx` — список карточек проектов
  - Каждая карточка проекта содержит:
    - Название проекта
    - Дата создания проекта
    - Дата последней запущенной задачи
    - Суммарная стоимость сформированных смет (сумма cost по задачам)
    - Разбивка задач по task_type: перечней из Гранд / перечней из проекта / проверок полноты / смет из перечня / оптимизаций
    - Индикатор: задачи в работе (синяя точка) / задачи с ошибкой (красная точка)
  - Сортировка: сначала проекты с активными задачами или ошибками
  - Счётчик orphan tasks со ссылкой на `/projects/unassigned`
  - Клик по карточке → переход на `/projects/{id}`

#### Блок 6 — «График задач за 10 дней»

- [ ] Компонент `DashboardChart.tsx` — stacked bar chart по дням
  - Ось X: последние 10 дней (даты)
  - Ось Y: количество созданных задач
  - Стеки по типам (5 цветов):
    - Перечень из Гранд (LIST_FROM_GRAND)
    - Перечень из проекта (LIST_FROM_PROJECT)
    - Проверка полноты по ГЭСН (CHECK_LIST_COMPLETENESS + CHECK_PROJECT_COMPLETENESS)
    - Смета из перечня (ESTIMATE_FROM_LIST)
    - Оптимизация (ESTIMATE_OPTIMIZATION)
  - Легенда под графиком
  - Библиотека: recharts (уже в проекте или добавить)

#### Блок 7 — «Прайс-листы»

- [ ] Компонент `DashboardPriceLists.tsx` — 2 карточки статуса
  - Карточка «Работы»: дата последнего обновления, количество позиций, статус эмбеддингов
  - Карточка «Материалы»: то же самое
  - Алерт красный: embedding_status = 'failed'
  - Алерт жёлтый: обновлено > 30 дней назад
  - Кнопка «Перейти в настройки» → `/admin`

### Фаза 3. Бэкенд: таблица `api_call_log` (стоимость Claude API)

- [ ] Создать миграцию `backend/alembic/versions/0NN_add_api_call_log.py`
  ```sql
  CREATE TABLE IF NOT EXISTS api_call_log (
    id SERIAL PRIMARY KEY,
    task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    model VARCHAR(50),
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd DECIMAL(10, 6) NOT NULL DEFAULT 0,
    called_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS ix_api_call_log_task_id ON api_call_log(task_id);
  CREATE INDEX IF NOT EXISTS ix_api_call_log_called_at ON api_call_log(called_at);
  ```
- [ ] Создать модель `ApiCallLog` в `backend/app/models/`
- [ ] Изменить `backend/app/services/claude_service.py` — после каждого вызова Claude писать запись в `api_call_log` (input_tokens, output_tokens, cache_read_tokens, cost_usd)
- [ ] Добавить в `GET /dashboard/stats` агрегаты стоимости

### Фаза 4. Фронтенд: Блок 8 — «Стоимость Claude API»

- [ ] Компонент `DashboardCosts.tsx` — KPI + мини-график
  - Потрачено сегодня / за неделю / за месяц (USD)
  - Стоимость по типу задачи (breakdown)
  - Cache hit rate = cache_read_tokens / total_input_tokens × 100%
  - Прогноз до конца месяца при текущем темпе
  - Сравнение с прошлым месяцем (+/- %)

---

## Человекочитаемые названия типов задач

Для отображения в UI:

| task_type | Отображаемое название |
|---|---|
| LIST_FROM_GRAND | Перечень из Гранд-сметы |
| LIST_FROM_PROJECT | Перечень из проекта |
| CHECK_LIST_COMPLETENESS | Проверка полноты (Гранд) |
| CHECK_PROJECT_COMPLETENESS | Проверка полноты (проект) |
| ESTIMATE_FROM_LIST | Смета из перечня |
| ESTIMATE_OPTIMIZATION | Оптимизация сметы |

---

## Итог

- [x] Фаза 1 завершена
- [ ] Фаза 2 завершена
- [ ] Фаза 3 завершена
- [ ] Фаза 4 завершена

**Реализовано целиком:** нет  
**Что осталось:** Фазы 2, 3, 4 (фронтенд, api_call_log, блок стоимости Claude API)
