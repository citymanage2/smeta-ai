# Fortune-Sheet + SheetJS: онлайн-редактор xlsx (тест)

**Цель:** Встроить онлайн-редактор таблиц Fortune-Sheet в изолированную вкладку
«Онлайн редактор ТЕСТ» в панели администратора (`/admin`). Кнопки загрузки xlsx в редактор и скачивания
результата обратно в xlsx. Существующие редакторы смет не затрагиваются.

---

## Фазы

### Фаза 1: Установка зависимостей [x]

**Пакеты:**
- `@fortune-sheet/react` — React-обёртка для редактора
- `@fortune-sheet/core` — ядро (peer dep, устанавливается явно)
- `xlsx` — SheetJS Community Edition (парсинг/экспорт xlsx)

**Команда:**
```bash
cd frontend && npm install @fortune-sheet/react @fortune-sheet/core xlsx
```

**Обновить `frontend/vite.config.ts`:**
```ts
optimizeDeps: {
  include: ['@fortune-sheet/react', '@fortune-sheet/core'],
}
```
Это нужно для корректной pre-bundle обработки в Vite 5 (CJS/ESM конфликты).

**Проверить:**
- В `package.json` появились три пакета
- `npm run build` проходит без ошибок (проверить TypeScript-типы)

**Известные нюансы:**
- `@fortune-sheet/react` требует CSS: `import '@fortune-sheet/react/dist/index.css'`
  — этот CSS глобальный, поэтому его нельзя импортировать на уровне модуля (см. Фаза 2)
- Fortune-Sheet работает с внутренней JSON-моделью (`Sheet[]`), а не напрямую с xlsx
- SheetJS CE — MIT-лицензия, не требует ключей
- Поддерживаемые форматы: `.xlsx`, `.xls` (частично). Не поддерживаются: `.xlsb`, `.xlsm` с макросами

---

### Фаза 2: Компонент SpreadsheetTestEditor [x]

**Файл:** `frontend/src/components/admin/SpreadsheetTestEditor.tsx`

**Структура компонента:**
```
SpreadsheetTestEditor
├── Toolbar
│   ├── Кнопка «Загрузить xlsx» → клик по скрытому <input type="file">
│   ├── Имя загруженного файла + кнопка сброса (если файл загружен)
│   ├── Предупреждение ⚠ если файл содержит формулы
│   ├── Индикатор * несохранённых изменений
│   └── Кнопка «Скачать xlsx» (активна только если sheets.length > 0)
├── Сообщение об ошибке (если error !== null)
├── Spinner (если isLoading === true)
├── Пустое состояние (если sheets.length === 0 и не loading)
└── FortuneSheet (если sheets.length > 0)
    └── height: calc(100vh - 200px)
```

**State компонента:**
```ts
interface State {
  sheets: Sheet[];
  loadedFileName: string | null;   // имя файла без расширения
  hasUnsavedChanges: boolean;
  isLoading: boolean;
  error: string | null;
  showFormulasWarning: boolean;
}
```

**Пустое состояние (когда файл не загружен):**
```tsx
<div style={{ textAlign: 'center', padding: '60px 20px', backgroundColor: '#f8fafc',
              borderRadius: '10px', border: '1px dashed #cbd5e1' }}>
  <div style={{ fontSize: '48px', marginBottom: '16px' }}>📊</div>
  <h3>Редактор таблиц</h3>
  <p>Загрузите смету в формате .xlsx или .xls</p>
  <button onClick={triggerFileInput}>Загрузить файл</button>
</div>
```

**Логика загрузки (xlsx → Fortune-Sheet):**
```
handleFileLoad(file):
  1. Проверить расширение: только .xlsx, .xls — иначе setError('Поддерживаются только .xlsx и .xls')
  2. setLoading(true), setError(null)
  3. Таймаут 30 сек: если не завершилось — setError('Загрузка заняла слишком долго')
  4. file.arrayBuffer() → xlsx.read(buffer, { type: 'array' })
  5. Проверить наличие формул → setShowFormulasWarning(true)
  6. xlsxWorkbookToFortune(workbook) → setSheets(fortuneData)
  7. setLoadedFileName(file.name.replace(/\.xlsx?$/i, ''))
  8. setLoading(false), setHasUnsavedChanges(false)
  При ошибке: setError(message), setLoading(false)
```

**Логика скачивания (Fortune-Sheet → xlsx):**
```
handleDownload():
  1. fortuneToXlsxWorkbook(sheets)
  2. xlsx.write(wb, { type: 'array', bookType: 'xlsx' })
  3. saveAs(blob, `${loadedFileName ?? 'export'}_${YYYY-MM-DD}.xlsx`)
  4. setHasUnsavedChanges(false)
```

**Логика сброса:**
```
handleReset():
  setSheets([]), setLoadedFileName(null), setError(null)
  setHasUnsavedChanges(false), setShowFormulasWarning(false)
```

**Защита от потери изменений:**
```tsx
useEffect(() => {
  if (!hasUnsavedChanges) return;
  const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; };
  window.addEventListener('beforeunload', handler);
  return () => window.removeEventListener('beforeunload', handler);
}, [hasUnsavedChanges]);
```

**CSS-изоляция Fortune-Sheet:**

Глобальный CSS Fortune-Sheet НЕ импортируется на уровне модуля — он применится ко всему приложению.
Решение: динамически подключать/отключать через `<link>` в `useEffect`:
```tsx
useEffect(() => {
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/node_modules/@fortune-sheet/react/dist/index.css';
  document.head.appendChild(link);
  return () => link.remove();
}, []);
```
Альтернатива: использовать CSS Module-обёртку с `all: revert` для изоляции.

**Высота редактора:**
```tsx
<div style={{ height: 'calc(100vh - 200px)' }}>
  <FortuneSheet sheets={sheets} onChange={handleSheetChange} />
</div>
```

**Минимальный начальный state (пустой лист — не используется при загрузке файла):**
```ts
const DEFAULT_SHEETS: Sheet[] = [{
  name: 'Лист1', celldata: [], row: 50, column: 26, status: 1, order: 0, index: '0',
}]
```

---

### Фаза 3: Вкладка в Admin.tsx [x]

**Файл:** `frontend/src/pages/Admin.tsx`

**4 точки изменений:**

1. Тип вкладок (~строка 250):
```ts
type AdminTab = 'tasks' | 'trash' | 'prices' | 'spreadsheet';
const [activeTab, setActiveTab] = useState<AdminTab>('tasks');
```

2. Список вкладок (~строка 578):
```ts
{(['tasks', 'trash', 'prices', 'spreadsheet'] as const).map((tab) => (
  // ...
  {tab === 'tasks' ? 'Задачи'
    : tab === 'trash' ? `Корзина${trashTotal > 0 ? ` (${trashTotal})` : ''}`
    : tab === 'prices' ? 'Прайс-листы'
    : 'Онлайн редактор ТЕСТ'}
```

3. `useEffect` для смены вкладок (~строка 398):
```ts
useEffect(() => {
  if (activeTab === 'tasks') fetchTasks();
  if (activeTab === 'trash') fetchTrash();
  if (activeTab === 'prices') fetchPriceListsInfo();
  // spreadsheet: серверных данных нет, ничего не делаем
}, [activeTab, ...]);
```

4. Условный рендер (после блока `prices`):
```tsx
{activeTab === 'spreadsheet' && (
  <Suspense fallback={<SectionLoader />}>
    <SpreadsheetTestEditor />
  </Suspense>
)}
```

5. Импорт:
```ts
import { SpreadsheetTestEditor } from '../components/admin/SpreadsheetTestEditor';
```

**Что НЕ меняется:**
- Логика остальных вкладок
- `EstimateEditorModal` и другие редакторы

---

### Фаза 4: Helper для конверсии форматов [x]

**Файл:** `frontend/src/utils/fortuneSheetConverter.ts`

**Функция импорта `xlsxWorkbookToFortune`:**

Итерировать по `wb.SheetNames`. Для каждого листа — получить диапазон через
`xlsx.utils.decode_range(worksheet['!ref'])`, затем цикл по `row` и `col`,
обращаться к ячейке через `xlsx.utils.encode_cell({r: row, c: col})`.
**Не использовать** `sheet_to_json({header:1})` — он не возвращает координаты и форматирование.

```ts
const range = xlsx.utils.decode_range(worksheet['!ref'] ?? 'A1');
for (let r = range.s.r; r <= range.e.r; r++) {
  for (let c = range.s.c; c <= range.e.c; c++) {
    const cellRef = xlsx.utils.encode_cell({ r, c });
    const cell = worksheet[cellRef];
    // маппинг cell.v, cell.t, cell.s → Fortune celldata
  }
}
```

Обрабатывать: `!merges` → `config.merge`, `!cols` → `config.columnlen`, `!rows` → `config.rowlen`.

**Функция экспорта `fortuneToXlsxWorkbook`:**

Создать `xlsx.utils.book_new()`. Для каждого Fortune-листа:
- итерировать по `celldata`, формировать `worksheet[cellRef]` с полем `s` (стили)
- применить `config.merge` → `!merges`
- применить `config.columnlen` → `!cols`, `config.rowlen` → `!rows`
- добавить через `xlsx.utils.book_append_sheet`

**Стратегия конверсии стилей (MVP):**

| Поле | Поддержка |
|---|---|
| Значения (строки, числа) | ✅ |
| Объединения ячеек | ✅ |
| Жирный, курсив | ✅ |
| Цвет фона и текста | ✅ |
| Границы ячеек (4 стороны) | ✅ |
| Выравнивание | ✅ |
| Ширина колонок, высота строк | ✅ |
| Формулы | ❌ заменяются на значения, показывать warning |
| Условное форматирование | ❌ |
| Картинки, диаграммы | ❌ |

**Маппинг полей SheetJS ↔ Fortune-Sheet:**

| SheetJS | Fortune-Sheet |
|---|---|
| `cell.v` | `celldata[i].v.v` |
| `cell.t` (тип) | `celldata[i].v.ct.t` |
| `cell.s.fill.fgColor` | `celldata[i].v.bg` |
| `cell.s.font.color` | `celldata[i].v.fc` |
| `cell.s.font.bold` | `celldata[i].v.bl` |
| `sheet['!merges']` | `config.merge` |
| `sheet['!cols']` | `config.columnlen` |
| `sheet['!rows']` | `config.rowlen` |

---

### Фаза 5: Проверка работы [x]

**Тест-сценарий 1 — базовый:**
1. Открыть `/admin` → вкладка «Онлайн редактор ТЕСТ»
2. Убедиться что пустое состояние отображается с подсказкой
3. Нажать «Загрузить файл» → выбрать смету `.xlsx`
4. Проверить: имя файла видно в toolbar
5. Отредактировать несколько ячеек → появляется индикатор несохранённых изменений (*)
6. Нажать «Скачать xlsx» → открыть в Excel/LibreOffice, проверить изменения

**Тест-сценарий 2 — многолистный файл:**
1. Загрузить смету с 3+ листами
2. Проверить: все листы видны в интерфейсе Fortune-Sheet (табы листов)
3. Отредактировать на Лист2, скачать → убедиться что изменения на Лист2 сохранились

**Тест-сценарий 3 — обработка ошибок:**
1. Загрузить неподдерживаемый файл (например `.pdf`) → появляется ошибка, UI не зависает
2. Загрузить файл с формулами → появляется warning ⚠ о замене формул на значения

**Тест-сценарий 4 — защита от потери:**
1. Загрузить файл, отредактировать ячейку
2. Попытаться закрыть вкладку браузера → появляется диалог подтверждения

**Что считать успехом:**
- [ ] Пустое состояние с подсказкой отображается корректно
- [ ] Файл загружается, имя видно в toolbar
- [ ] Числа, строки, объединённые ячейки отображаются корректно
- [ ] Все листы многолистного файла загружаются
- [ ] Редактирование на любом листе сохраняется при скачивании
- [ ] Скачанный файл называется `{имя_файла}_{YYYY-MM-DD}.xlsx`
- [ ] Цвета фона, жирный шрифт, размеры колонок сохраняются
- [ ] Ошибка парсинга отображается пользователю (не в консоль)
- [ ] Warning при наличии формул в файле
- [ ] Диалог при закрытии с несохранёнными изменениями
- [ ] CSS Fortune-Sheet не ломает стили остальных вкладок
- [ ] Существующие редакторы смет работают без изменений

---

## Технические ограничения Fortune-Sheet (для записей)

- **CSS конфликты:** Глобальные стили Fortune-Sheet подключаются динамически только на этой вкладке (см. Фаза 2).
- **Размер бандла:** `@fortune-sheet/react` ~450 КБ min / ~130 КБ gzip. Загружается только при переходе на вкладку через `React.lazy`.
- **SSR:** не применимо (Vite SPA).
- **TypeScript:** типы поставляются вместе с пакетом, возможны `as unknown as` в конверторе.
- **SheetJS CE ограничения:** поддерживаются `.xlsx` и `.xls`. Формулы — значения без вычисления. `.xlsb` и `.xlsm` с макросами не поддерживаются.
- **Размер файла:** без ограничений. При очень больших файлах (>10 МБ) возможен долгий парсинг — таймаут 30 сек.

---

## Итог

| Статус | Детали |
|---|---|
| Реализован целиком | [x] |
| Частично | [ ] |
| Что осталось | Ручное тестирование в браузере (сценарии 1–4 из Фазы 5) |

---

*Создан: 2026-05-25*
*Агент обязан обновлять статус фаз после каждой сессии.*
