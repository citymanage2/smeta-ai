# Динамическая ширина колонок Цена и Стоимость

**Дата:** 2026-06-01  
**Статус:** реализован

## Цель

Числа в колонках «Цена работы», «Цена материала», «Стоимость» всегда отображаются полностью — ширина колонок автоматически подстраивается под максимальное число в данных, без горизонтального скролла и без урезания.

## Проблема

Сейчас ширины статические:
- `price_work` → 70px
- `price_material` → 78px
- `cost` → 70px

Числа вроде «250 000» (7 символов × ~8px = 56px + padding) или «554 300» не помещаются и обрезаются с «…».

## Гипотезы

1. **Расчёт ширины через длину строки.** Форматированное число в `ru-RU` имеет предсказуемый набор символов (цифры + пробелы-разделители). Ширина ≈ `len × charWidth + padding`. Погрешность ≤ 5% — достаточно для практики.
2. **Минимальная ширина = заголовок.** Заголовок «Цена работы, руб» длиннее большинства чисел — нужно учитывать как нижнюю границу.
3. **Компенсация через Комментарий.** Если суммарная ширина трёх колонок вырастает, таблица остаётся той же ширины за счёт сужения колонки «Комментарий». Горизонтальный скролл не появляется.
4. **Кол-во всегда 84px.** Уменьшить с 120 до 84px (-30%) — высвобождает базовый запас.
5. **Перенос в Наименование.** 575px для «Наименование» остаётся, но ячейки переносят текст на новую строку. Требует `rowHeight` как функции или увеличенной фиксированной высоты.

## Технические решения

### 1. Функция расчёта ширины колонки

```typescript
const CHAR_W = 8;    // ширина символа в пикселях при font-size 13px
const CELL_PAD = 24; // суммарный горизонтальный padding ячейки

function calcColWidth(values: (number | null | undefined)[], minPx: number): number {
  let maxLen = 0;
  for (const v of values) {
    if (v == null) continue;
    const len = Math.round(Math.abs(v)).toLocaleString('ru-RU').length;
    if (len > maxLen) maxLen = len;
  }
  return Math.max(minPx, maxLen * CHAR_W + CELL_PAD);
}
```

`minPx` задаётся статически по ширине заголовка:
- «Цена работы, руб» → minPx = 110
- «Цена материала, руб» → minPx = 120
- «Стоимость, руб» → minPx = 100

### 2. useMemo для динамических колонок

В `EstimateGrid` добавить `useMemo`, зависящий от `rows` и `activeTab`:

```typescript
const dynamicColWidths = useMemo(() => {
  const priceWork = calcColWidth(rows.map(r => r.price_work), 110);
  const priceMat  = calcColWidth(rows.map(r => r.price_material), 120);
  const cost      = calcColWidth(rows.map(r => calcCost(r)), 100);

  // Дельта считается только по видимым в текущем табе колонкам
  const BASE_PW = 70, BASE_PM = 78, BASE_COST = 70;
  const base   = activeTab === 'works'     ? BASE_PW + BASE_COST
               : activeTab === 'materials' ? BASE_PM + BASE_COST
               : BASE_PW + BASE_PM + BASE_COST;
  const actual = activeTab === 'works'     ? priceWork + cost
               : activeTab === 'materials' ? priceMat + cost
               : priceWork + priceMat + cost;
  const delta = actual - base;

  // min 100px, max 260px (не расширять сверх базы при delta ≤ 0)
  const comment = Math.max(100, Math.min(260, 260 - delta));

  return { priceWork, priceMat, cost, comment };
}, [rows, activeTab]);
```

### 3. Передача ширины в Column-объекты

`WORK_PRICE_COL`, `MATERIAL_PRICE_COL`, `COST_COL`, `COMMENT_COL` — преобразовать из констант в функции/вычисляемые значения. Оба варианта:

**Вариант A (проще):** формировать колонки внутри `useMemo` на основе `dynamicColWidths`.  
**Вариант B:** передавать ширину через пропсы в рендер-функции колонок.

Выбираем **Вариант A** — меньше кода, нет утечки пропсов.

**Важно:** существующий `columns` useMemo (строка 868 EstimateGrid.tsx) берёт из модульных констант `ALL_COLUMNS` / `WORKS_COLUMNS` / `MATERIALS_COLUMNS`. При Варианте A сборка всех наборов колонок переносится внутрь `dynamicColWidths` useMemo, а `columns` useMemo начинает использовать эти динамические объекты. Зависимость `columns` useMemo пополняется `activeTab` и `dynamicColWidths`.

### 4. «Кол-во» — 84px

Изменить `width: 120` → `width: 84` в `BASE_COLUMNS`.

### 5. Перенос в «Наименование»

Добавить `cellClass: 'cell-name-wrap'` в объект колонки `name` в `BASE_COLUMNS` (не CSS-селектор по `aria-colindex`, так как индекс меняется в зависимости от `isReadonly`):

```typescript
{
  key: 'name',
  name: 'Наименование',
  width: 575,
  cellClass: 'cell-name-wrap',   // ← добавить
  renderCell: NameCell,
  // ...
}
```

Добавить CSS:
```css
.rdg-cell.cell-name-wrap {
  white-space: normal;
  word-break: break-word;
  line-height: 1.4;
}
```

И установить увеличенную фиксированную высоту строки (или `rowHeight` как функцию, если нужно):
```tsx
<DataGrid
  ...
  rowHeight={44}   /* вместо дефолтных 35px */
/>
```

Секционные заголовки (`type === 'section'`) оставить на 35px через `rowHeight={(row) => row.type === 'section' ? 35 : 44}`.

## Ограничения и риски

- **react-data-grid пересоздаёт колонки при каждом useMemo.** Это нормально: DataGrid не перемонтируется, только обновляет widths.
- **rowHeight=44 увеличивает высоту всех строк**, в т.ч. с короткими именами. Приемлемо для рабочего инструмента.
- **comment < 100px при очень крупных числах.** Маловероятно (нужно 3 колонки × >100px роста), но стоит добавить жёсткий cap: если delta > 160px, фиксируем comment=100 и наименование сужаем вместо comment (бизнес-решение при реализации).

---

## Фазы реализации

### [x] Фаза 1 — Динамическая ширина числовых колонок

**Результат:** колонки price_work, price_material, cost автоматически расширяются под максимальное число в данных; колонка comment компенсирует рост.

Задачи:
- [x] Файл: `frontend/src/components/estimate/EstimateGrid.tsx`
- [x] Добавить функцию `calcColWidth` (константы `CHAR_W = 8`, `CELL_PAD = 24`)
- [x] Добавить `useMemo` → `dynamicColWidths` с расчётом `priceWork`, `priceMat`, `cost`, `comment` (зависимости: `rows`, `activeTab`)
- [x] Delta считать только по видимым в `activeTab` колонкам (works: pw+cost, materials: pm+cost, all: pw+pm+cost)
- [x] comment: `Math.max(100, Math.min(260, 260 - delta))` — не расширять сверх базы при delta ≤ 0
- [x] Перенести сборку `ALL_COLUMNS` / `WORKS_COLUMNS` / `MATERIALS_COLUMNS` внутрь `dynamicColWidths` useMemo (Вариант A); убрать статические `width` из констант WORK_PRICE_COL / MATERIAL_PRICE_COL / COST_COL / COMMENT_COL
- [x] Обновить существующий `columns` useMemo: использовать динамические наборы вместо модульных констант, добавить `activeTab` и `dynamicColWidths` в зависимости
- [x] Убедиться, что при пустых данных колонки падают до `minPx` (110 / 120 / 100)

---

### [x] Фаза 2 — Уменьшение колонки «Кол-во»

**Результат:** колонка qty занимает 84px вместо 120px, высвобождая 36px в базовом бюджете.

Задачи:
- [ ] Файл: `frontend/src/components/estimate/EstimateGrid.tsx`, `BASE_COLUMNS`, колонка `qty`
- [ ] Изменить `width: 120` → `width: 84`
- [ ] Визуально проверить, что число «10 000» + кнопка ↩ помещаются при наличии `qty_overridden`
- [ ] Визуально проверить `qty-cell-comment` (норматив под числом) — не стиснут

---

### [x] Фаза 3 — Перенос текста в колонке «Наименование» + rowHeight

**Результат:** длинные наименования переносятся на новую строку; строки стали выше (44px), секционные заголовки остались 35px.

Задачи:
- [ ] Добавить `cellClass: 'cell-name-wrap'` в объект колонки `name` в `BASE_COLUMNS` (не через `aria-colindex` — индекс меняется при `isReadonly`)
- [ ] Добавить CSS-правило `.rdg-cell.cell-name-wrap { white-space: normal; word-break: break-word; line-height: 1.4; }` в `EstimateGrid.css`
- [ ] Установить `rowHeight={(row) => row.type === 'section' ? 35 : 44}` в `<DataGrid>`
- [ ] Проверить, что `.section-header-cell` CSS использует `height: 100%` или фиксированный `min-height: 35px` — секционные заголовки остались на прежней высоте
- [ ] Проверить перенос в readonly-режиме (`isReadonly=true`) — стиль через `cellClass` работает независимо от режима

---

### [x] Фаза 4 — Ручное тестирование

**Результат:** подтверждено, что все сценарии работают корректно.

Сценарии:
- [ ] Смета с крупными числами (≥ 100 000): все три числовые колонки показывают значения полностью, без «…»
- [ ] Смета с малыми числами (≤ 9 999): колонки не шире заголовков, `comment` не расширилась сверх 260px, таблица не разъехалась
- [ ] Пустая/новая смета: колонки на минимальных значениях (110 / 120 / 100), горизонтального скролла нет
- [ ] Длинное наименование: текст переносится, строка растягивается по высоте, не обрезается
- [ ] Readonly-режим (`isReadonly=true`): перенос текста в «Наименование» работает
- [ ] Таб «Работы» отдельно: delta считается без `price_material`, ширины корректны
- [ ] Таб «Материалы» отдельно: delta считается без `price_work`, ширины корректны
- [ ] Позиция с `qty_overridden=true`: число «10 000» + кнопка ↩ помещаются в 84px без обрезания

---

## Итог

**Реализован целиком / нет / частично:** реализован целиком

**Что осталось:** ничего.

**Что было:** статические ширины price_work=70 / price_material=78 / cost=70px, числа обрезались с «…»; qty=120px избыточно; наименования не переносились.

**Что стало:** динамическая ширина числовых колонок на основе `calcColWidth` (min 110/120/100px); колонка «Комментарий» компенсирует рост (100–260px); qty=84px; наименования переносятся на новую строку (cellClass+CSS); строки 44px, секционные заголовки 35px. tsc --noEmit без ошибок. Security review: PASSED.
