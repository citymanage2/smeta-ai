# Итерация 2 — Экспорт проекта в xlsx/PDF

**Дата:** 2026-03-26
**Стек:** FastAPI + openpyxl + weasyprint / React + TypeScript + fetch API

---

## Контекст

Итерация 1 добавила сущность Project с задачами, файловыми слотами (source/estimate/optimized) и статусами смет. Итерация 2 добавляет экспорт проекта в xlsx или PDF — кнопки на странице ProjectDetail и в карточках Projects.

---

## Новые endpoint-ы

### `GET /projects/{project_id}/export`

**Query params:** `format=xlsx|pdf`

**Auth:** `get_current_user`

**Поведение:**
- Собирает данные проекта: name, description, список задач (task_type, estimation_status, cost, created_at), TaskResult по слотам (source/estimate/optimized) для каждой задачи
- Генерирует файл через соответствующий утилитный модуль
- Возвращает `StreamingResponse` с заголовками:
  - xlsx: `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
  - PDF: `Content-Type: application/pdf`
  - `Content-Disposition: attachment; filename="{project_name}.{ext}"`
- 400 если `format` не `xlsx` или `pdf`
- 404 если проект не найден

### `GET /tasks/{task_id}/files/{slot}/download`

**Auth:** `get_current_user`

**Поведение:**
- Ищет `TaskResult` по `task_id` и `slot`
- Возвращает `StreamingResponse` с байтами файла и `Content-Disposition: attachment; filename="{file_name}"`
- 404 если слот пуст

---

## Утилиты

### `backend/app/utils/xlsx_exporter.py`

```python
def generate_project_xlsx(project: Project, tasks: list[Task], slot_results: dict[str, list[tuple[Task, TaskResult]]]) -> bytes:
    """
    Генерирует xlsx файл в памяти.
    slot_results: {'source': [(task, result), ...], 'estimate': [...], 'optimized': [...]}
    Возвращает bytes.
    """
```

**Лист 1 — «Задачи»:**

| Тип задачи | Статус сметы | Стоимость (₽) | Дата создания |
|---|---|---|---|
| Составление сметы | Рассчитано | 1 500 000 | 26.03.2026 |
| ... | | | |
| **ИТОГО** | не рассчитано: N / рассчитано: N / оптимизировано: N | SUM | |

Стиль:
- Заголовочная строка: жирный шрифт, серый фон (`#D9D9D9`)
- Итоговая строка: жирный шрифт, голубой фон (`#BDD7EE`)
- Числовой формат для «Стоимость»: `#,##0.00`
- Ширины колонок: Тип задачи=35, Статус сметы=20, Стоимость=18, Дата создания=20

**Листы 2-4 — «Исходные файлы», «Расчёты», «Оптимизированные»:**

| Тип задачи | Имя файла | Ссылка |
|---|---|---|
| Составление сметы | smeta.xlsx | =HYPERLINK("https://...") |

Ссылка формируется как `{BACKEND_URL}/tasks/{task_id}/files/{slot}/download`.

`BACKEND_URL` передаётся как параметр в функцию (берётся из `settings.BACKEND_URL` или строится из request).

Если для слота нет файлов — лист всё равно создаётся с заголовком и строкой «Файлы отсутствуют».

### `backend/app/utils/pdf_exporter.py`

```python
def generate_project_pdf(project: Project, tasks: list[Task], slot_results: dict[str, list[tuple[Task, TaskResult]]], base_url: str) -> bytes:
    """
    Генерирует PDF из HTML-строки через weasyprint.
    Возвращает bytes.
    """
```

**Структура HTML:**

1. **Заголовок:** название проекта (h1), описание (p, если есть), дата экспорта
2. **Таблица задач:**
   - Колонки: Тип задачи · Статус сметы · Стоимость · Дата создания
   - Итоговая строка (жирный)
3. **Три секции** (h2): «Исходные файлы», «Расчёты», «Оптимизированные»
   - Список: `<a href="{base_url}/tasks/{task_id}/files/{slot}/download">{file_name}</a>`
   - Если нет файлов: «Файлы отсутствуют»

Стилизация: встроенный CSS (таблица с границами, чередование строк, шрифт sans-serif).

---

## Константы

В `backend/app/constants.py` добавляется:

```python
TASK_TYPE_LABELS: dict[str, str] = {
    "SMETA_FROM_LIST": "Смета из ТЗ",
    "SMETA_FROM_PROJECT": "Смета из проекта",
    "SMETA_FROM_EDC_PROJECT": "Смета из EDC-проекта",
    "SMETA_FROM_GRAND_PROJECT": "Смета из GRAND-проекта",
    "SCAN_TO_EXCEL": "Сканирование в Excel",
    "LIST_FROM_TZ": "Список из ТЗ",
    "LIST_FROM_TZ_PROJECT": "Список из ТЗ проекта",
    "LIST_FROM_PROJECT": "Список из проекта",
    "RESEARCH_PROJECT": "Исследование проекта",
    "COMPARE_PROJECT_SMETA": "Сравнение сметы",
}

ESTIMATION_STATUS_LABELS: dict[str, str] = {
    "unestimated": "Не рассчитано",
    "estimated": "Рассчитано",
    "optimized": "Оптимизировано",
    "not_applicable": "—",
}
```

---

## Настройки

`base_url` для гиперссылок формируется из объекта `Request`:

```python
base_url = str(request.base_url).rstrip('/')
# например: "https://smeta-ai-backend.onrender.com"
```

Это не требует env var и работает корректно на любом окружении (локальном и продакшн).

---

## Frontend

### `frontend/src/api/projects.ts`

Добавляется функция:

```typescript
export async function exportProject(projectId: string, format: 'xlsx' | 'pdf'): Promise<void> {
  const response = await apiClient.get(`/projects/${projectId}/export`, {
    params: { format },
    responseType: 'blob',
  });
  const ext = format === 'xlsx' ? 'xlsx' : 'pdf';
  const contentDisposition = response.headers['content-disposition'] ?? '';
  const match = contentDisposition.match(/filename="?([^"]+)"?/);
  const fileName = match ? match[1] : `project.${ext}`;
  const url = URL.createObjectURL(response.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}
```

### `frontend/src/pages/ProjectDetail.tsx`

В шапке проекта (рядом с «Изменить» / «Удалить») добавляются две кнопки:

```tsx
const [exporting, setExporting] = useState<'xlsx' | 'pdf' | null>(null);

async function handleExport(format: 'xlsx' | 'pdf') {
  if (!projectId) return;
  setExporting(format);
  try {
    await exportProject(projectId, format);
  } catch {
    setError('Ошибка при экспорте');
  } finally {
    setExporting(null);
  }
}
```

Кнопки:
```
[↓ xlsx]  [↓ PDF]  [Изменить]  [Удалить — admin]
```

Во время загрузки кнопка соответствующего формата показывает «...» и становится `disabled`.

### `frontend/src/pages/Projects.tsx`

В каждую карточку проекта добавляется строка с кнопками экспорта внизу (после badges):

```tsx
<div style={{ display: 'flex', gap: '8px', marginTop: '12px', borderTop: '1px solid #f1f5f9', paddingTop: '12px' }}
     onClick={(e) => e.stopPropagation()}>
  <ExportButton projectId={p.id} format="xlsx" />
  <ExportButton projectId={p.id} format="pdf" />
</div>
```

`onClick stopPropagation` — чтобы клик по кнопкам не переходил на страницу проекта. Кнопки рендерятся inline внутри карточки (не выносятся в отдельный компонент).

---

## Обработка ошибок

| Ситуация | Поведение |
|---|---|
| `format` не xlsx/pdf | 400 Bad Request |
| Проект не найден | 404 Not Found |
| Слот пуст (download) | 404 Not Found |
| Ошибка weasyprint | 500, лог ошибки |
| Ошибка клиента | `setError('Ошибка при экспорте')` |

---

## Тесты

`backend/tests/test_export.py`:

1. `test_export_xlsx_returns_bytes` — POST project, GET export?format=xlsx → 200, content-type xlsx
2. `test_export_pdf_returns_bytes` — GET export?format=pdf → 200, content-type pdf
3. `test_export_invalid_format` — GET export?format=docx → 400
4. `test_export_project_not_found` — GET export?format=xlsx на несуществующий ID → 404
5. `test_slot_download_returns_file` — загрузить файл в слот, GET download → 200, bytes
6. `test_slot_download_empty_slot` — GET download пустого слота → 404

---

## Не входит в Итерацию 2

- Кастомный шаблон (логотип, брендинг)
- Экспорт списка всех проектов
- Сравнение версий смет (Итерация 3)
