# Plan: Каталог расценок (Price Catalog)

Date: 2026-04-29  
Status: in_progress  
Research: `thoughts/research/2026-04-29-price-catalog.md`

## Goal
Визуальный редактор прайсов — «Каталог расценок» в левом сайдбаре.
Полный CRUD по работам и материалам, импорт/экспорт, поиск, фильтрация, пагинация, сортировка, эмбеддинг при добавлении/импорте.

## Acceptance Criteria
- [ ] В сайдбаре над «Корзиной» — пункт «Каталог расценок» с иконкой
- [ ] Страница `/catalog` с тремя вкладками: Все | Работы | Материалы
- [ ] Вкладка «Все»: колонки Название, Тип, Ед.изм., Цена, Дата; сортировка
- [ ] Вкладка «Работы»: Название, Ед.изм., Подрядчики, Мин.цена, Дата
- [ ] Вкладка «Материалы»: Название, Ед.изм., Цена, Дата
- [ ] Пагинация: 20/50/100 строк, дефолт 20; клиентская (фронт получает всё или серверная)
- [ ] Поиск по названию (debounce 300ms)
- [ ] Кнопка фильтрации (по типу, ед.изм.)
- [ ] Сортировка по умолчанию А-Я, переключаемая
- [ ] Кнопки Импорт / Экспорт / Шаблон
- [ ] Добавить вручную: модальное окно, поле Тип/Название/Ед.изм./Цена
- [ ] Редактирование каждой позиции (карандаш → модалка)
- [ ] Удаление позиции с подтверждением
- [ ] При ручном добавлении и импорте через каталог — генерируется эмбеддинг
- [ ] После любого изменения — кэш price_service перезагружается

## Phases

### Phase 1: Backend — CRUD API [x]

**Файлы:**
- `backend/app/routers/prices_catalog.py` (новый)
- `backend/app/main.py` (подключить роутер)

**Эндпоинты:**

```
GET  /prices/catalog
     ?tab=all|works|materials
     &search=<str>
     &sort=name_asc|name_desc|price_asc|price_desc|date_asc|date_desc
     &page=1&page_size=20
     → { items: [...], total: int }

POST /prices/catalog/works
     body: { name, unit?, prices? }
     → созданный объект + эмбеддинг + reload_cache

POST /prices/catalog/materials
     body: { name, unit?, price? }
     → созданный объект + эмбеддинг + reload_cache

PUT  /prices/catalog/works/{id}
     body: { name?, unit?, prices? }
     → обновлённый + reload_cache

PUT  /prices/catalog/materials/{id}
     body: { name?, unit?, price? }
     → обновлённый + reload_cache

DELETE /prices/catalog/works/{id}     → 204 + reload_cache
DELETE /prices/catalog/materials/{id} → 204 + reload_cache

GET  /prices/catalog/export?tab=all|works|materials
     → xlsx-файл

GET  /prices/catalog/template?type=works|materials
     → xlsx-шаблон для импорта
```

**Логика GET /prices/catalog:**
- Запрашивает PriceWork и/или PriceMaterial в зависимости от tab
- Фильтрует по search (ILIKE %name%)
- Сортирует в Python/SQL
- Возвращает унифицированные объекты:
  ```json
  {
    "id": 1,
    "kind": "work",          // "work" | "material"
    "name": "...",
    "unit": "м²",
    "price": 1200.0,         // min_price для работ, price для материалов
    "prices": {"ИП Иванов": 1200},  // только для работ
    "updated_at": "2026-04-29T..."
  }
  ```

**Шаблоны Excel:**
- Работы: колонки Наименование | Ед.изм. | Подрядчик1 | Подрядчик2
- Материалы: колонки Наименование | Ед.изм. | Цена

### Phase 2: Frontend — страница PriceCatalog [x]

**Файлы:**
- `frontend/src/pages/PriceCatalog.tsx` (новый)
- `frontend/src/api/catalog.ts` (новый)

**Структура компонента:**
```
PriceCatalog
├── Header: заголовок + кнопки [Добавить] [Импорт] [Экспорт] [Шаблон]
├── Controls: SearchInput | FilterButton | SortSelect
├── Tabs: Все | Работы | Материалы
├── Table
│   ├── thead (колонки по вкладке)
│   └── tbody (строки с Редактировать/Удалить)
├── Pagination: [Строк: 20/50/100] [← 1 2 3 →]
├── AddModal
└── EditModal
```

**API-модуль `catalog.ts`:**
```typescript
getCatalog(params): Promise<CatalogResponse>
createWork(data): Promise<CatalogItem>
createMaterial(data): Promise<CatalogItem>
updateWork(id, data): Promise<CatalogItem>
updateMaterial(id, data): Promise<CatalogItem>
deleteWork(id): Promise<void>
deleteMaterial(id): Promise<void>
exportCatalog(tab): Promise<void>
downloadTemplate(type): Promise<void>
```

**Типы:**
```typescript
type CatalogItem = {
  id: number
  kind: 'work' | 'material'
  name: string
  unit: string | null
  price: number | null
  prices: Record<string, number> | null  // только для работ
  updated_at: string
}
type CatalogResponse = { items: CatalogItem[], total: number }
```

### Phase 3: Frontend — сайдбар + роутер [x]

**Файлы:**
- `frontend/src/components/ProjectsSidebar.tsx` (изменить)
- `frontend/src/App.tsx` (изменить)

**Изменения в сайдбаре:**
- Добавить секцию «Каталог расценок» между проектами и корзиной
- Иконка: `BookOpen` из lucide-react
- Ссылка на `/catalog`
- Стиль: такой же как «Корзина» (серый, по наведению — синий)
- В collapsed-режиме — только иконка с tooltip

**Изменения в App.tsx:**
- Добавить `<Route path="/catalog" element={<ProtectedRoute><PriceCatalog /></ProtectedRoute>} />`
- Импортировать `PriceCatalog`

### Phase 4: Эмбеддинг при ручном добавлении и импорте [x]

**Файлы:**
- `backend/app/routers/prices_catalog.py` (уже в Phase 1)

**Логика:**
- POST /prices/catalog/works|materials → после сохранения в БД:
  1. `emb = generate_embedding(normalize_name(name), "search_document")`
  2. UPDATE row.embedding = emb
  3. `await load_cache(db)`
- PUT → то же самое при изменении name
- DELETE → только `await load_cache(db)`
- Импорт через `/admin/price-lists/{type}` уже генерирует эмбеддинги (не трогаем)

## Edge Cases
- Пустой каталог: пустая таблица с текстом «Нет позиций. Загрузите прайс или добавьте вручную»
- Поиск без результатов: «Ничего не найдено по запросу "..."»
- Удаление: confirm «Удалить позицию "{name}"? Это действие необратимо»
- Ошибка при генерации эмбеддинга: позиция сохраняется без эмбеддинга, кэш обновляется
- Цена 0 или null: показывать «—»
- Очень длинное название: text-overflow ellipsis

## Non-Goals
- Не переделывать существующий /admin/price-lists upload (он работает)
- Не добавлять историю изменений
- Не делать batch-edit

## Notes
- Роутер prices_catalog.py подключать в main.py с prefix="/prices"
- Все эндпоинты требуют авторизацию (get_current_user)
- При DELETE позиция удаляется из price_works/price_materials, не из price_lists (файл остаётся)
- Статус embedded/not-embedded — не показывать пользователю, это внутренняя деталь
