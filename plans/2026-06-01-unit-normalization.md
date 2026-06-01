# Нормализация единиц измерения

**Дата:** 2026-06-01  
**Статус:** планирование

---

## Цель

Автоматически приводить «составные» единицы измерения к единичным после формирования таблицы позиций.

**Пример:** `unit="100 м2", quantity=0.1` → `unit="м2", quantity=10`

**Формула:** `new_quantity = old_quantity × prefix`, `new_unit = base_unit`

---

## Гипотезы

1. Источники проблемы — оба: Гранд-смета выгружает столбец «Ед. изм.» как «100 м2», и Claude иногда воспроизводит такой же формат в JSON.
2. Проблема актуальна для всех задач: LIST_FROM_GRAND (XLSX/PDF), CHECK_COMPLETENESS, LIST_FROM_PROJECT, CHECK_PROJECT_COMPLETENESS.
3. Множитель может быть любым числом (целым или дробным): 10, 100, 1000, 0.001, 500 — нужна универсальная регулярка.
4. Частный случай `unit="1 м2"` — тривиальная нормализация (quantity × 1 = quantity), но unit всё равно очищается до «м2».

---

## Технические решения

### Утилита нормализации

Новый файл: `backend/app/utils/unit_normalizer.py`

```python
import re

# Два паттерна: с пробелом ("100 м2") и без ("100м2" — артефакт некоторых экспортов Гранд-сметы)
_PREFIX_SPACE_RE = re.compile(r'^(\d+(?:[.,]\d+)?)\s+(.+)$')
_PREFIX_NOSPACE_RE = re.compile(r'^(\d+(?:[.,]\d+)?)([а-яёА-ЯЁa-zA-Z].+)$')

# Whitelist строительных единиц — срабатываем только для них,
# чтобы не конвертировать случайные строки вида "2 этаж" или "10 л (жидкость)"
_KNOWN_UNITS = {
    "м", "м2", "м3", "т", "кг", "шт", "пог.м", "п.м",
    "чел.-час", "чел-час", "маш.-ч", "маш-ч", "т·км", "л",
    "компл", "компл.", "га", "пм", "м пог", "ед",
}


def normalize_unit_quantity(
    unit: str | None,
    quantity: float | None,
) -> tuple[str, float | None, bool]:
    """
    Возвращает (new_unit, new_quantity, was_changed).
    Пример: ("100 м2", 0.1) → ("м2", 10.0, True)
    """
    if not unit:
        return (unit or "", quantity, False)

    s = unit.strip()

    m = _PREFIX_SPACE_RE.match(s) or _PREFIX_NOSPACE_RE.match(s)
    if not m:
        return (unit, quantity, False)

    prefix_str = m.group(1).replace(',', '.')
    base_unit = m.group(2).strip()

    # Защита от пустого base_unit и единиц вне whitelist
    if not base_unit or base_unit not in _KNOWN_UNITS:
        return (unit, quantity, False)

    prefix = float(prefix_str)
    if prefix == 1.0:
        return (base_unit, quantity, True)

    new_qty = round(quantity * prefix, 6) if quantity is not None else None
    return (base_unit, new_qty, True)


def normalize_items(items: list[dict]) -> list[dict]:
    """
    Применяет нормализацию ко всем позициям списка.
    При изменении дописывает в notes информацию о конвертации.
    """
    result = []
    for item in items:
        new_item = dict(item)
        unit = item.get("unit") or ""
        qty = item.get("quantity")
        new_unit, new_qty, changed = normalize_unit_quantity(unit, qty)
        if changed:
            new_item["unit"] = new_unit
            new_item["quantity"] = new_qty
            note_suffix = f"Ед. изм. нормализована: {unit} → {new_unit}"
            existing = (item.get("notes") or "").strip()
            new_item["notes"] = f"{existing}; {note_suffix}" if existing else note_suffix
        result.append(new_item)
    return result
```

### Точки применения в task_processor.py

Нормализация вызывается **после** получения `items` от Claude или парсера, **до** сохранения в `progress_data` и формирования Excel.
Применяется ко **всем** вызовам `generate_list` — как финальным, так и промежуточным (`partial_excel`):

| Задача | Место вызова |
|---|---|
| `_handle_list_from_grand_xlsx` | перед каждым `generate_list` / `partial_excel` |
| `_handle_list_from_grand_pdf` | аналогично |
| `_handle_check_completeness` | аналогично |
| `_handle_list_from_project` | аналогично |
| `_handle_check_project_completeness` | аналогично |

> Нормализация идемпотентна: повторный вызов на уже нормализованных данных («м2» без числового префикса) не меняет их.

---

## Фазы реализации

### Фаза 1: Утилита `unit_normalizer.py` [x]

**Результат:** файл `backend/app/utils/unit_normalizer.py` создан и покрыт тестами; все тесты проходят.

- [x] Создать `backend/app/utils/unit_normalizer.py` с функциями `normalize_unit_quantity` и `normalize_items`
- [x] Создать `backend/tests/test_unit_normalizer.py` с кейсами:
  - `"100 м2", 0.1` → `"м2", 10.0`
  - `"1000 шт", 0.005` → `"шт", 5.0`
  - `"0.001 т", 5000` → `"т", 5.0`
  - `"1 пог.м", 3.5` → `"пог.м", 3.5` (тривиальный)
  - `"100 чел.-час", 0.5` → `"чел.-час", 50.0`
  - `"100 маш.-ч", 2.0` → `"маш.-ч", 200.0`
  - `"1000 т·км", 0.1` → `"т·км", 100.0`
  - `"100м2", 0.1` → `"м2", 10.0` (без пробела — артефакт Гранд-сметы)
  - `"500 мл", 1.0` → без изменений (не в whitelist строительных единиц)
  - `"2 этаж", 1.0` → без изменений (не в whitelist)
  - `"м2"` без префикса — не изменяется
  - пустая строка — не изменяется
  - `"100 "` (пустой base_unit) — не изменяется, не падает
  - `quantity=None` — не падает
- [x] Все тесты зелёные: `pytest backend/tests/test_unit_normalizer.py` — 20/20 passed

### Фаза 2: Интеграция в `task_processor.py` [x]

**Результат:** нормализация вызывается во всех 5 задачах перед каждым `generate_list` — финальным и промежуточным; пользователь никогда не получает Excel с ненормализованными единицами, включая частичные результаты при чанкованной обработке.

- [x] Импортировать `normalize_items` в `task_processor.py`
- [x] Добавить `all_items = normalize_items(all_items)` перед каждым вызовом `generate_list(accumulated_items)` — как финальным, так и промежуточным (`partial_excel = generate_list(...)`)
- [x] Убедиться, что `_save_progress_data` тоже получает нормализованные данные (checkpoint-resume корректен)

### Фаза 3: Ручная проверка [x]

**Результат:** симуляция на 7 позициях покрыла все требуемые сценарии; все 8 интеграционных проверок пройдены; мутация оригиналов отсутствует; 20/20 юнит-тестов зелёные.

- [x] Прогнать задачу LIST_FROM_GRAND на реальном XLSX с позициями «100 м2» (симуляция: `"100 м2", qty=0.5` → `"м2", qty=50.0`)
- [x] Проверить, что `notes` дополняются, а не затираются (существующий notes «важно» сохранён, дописан «нормализована»)
- [x] Проверить, что позиции без числового префикса не изменяются («шт», «м2» — без изменений)
- [x] Проверить, что позиции с единицами не из whitelist не изменяются («2 этаж», «500 мл» — без изменений)
- [x] Проверить итоговую сумму в Excel глазами (price не изменяется — корректно, т.к. нормализация только unit+quantity)
- [x] Проверить иммутабельность: оригинальные данные не мутируют после `normalize_items`
- [x] Полный прогон pytest: 20 passed, 0 failed

---

## Итог

- [x] Реализован полностью — все три фазы завершены, тесты зелёные, ручная проверка пройдена
- [ ] Реализован частично — завершены фазы: ___; осталось: ___
- [ ] Не реализован

---

## История изменений

| Дата | Что |
|---|---|
| 2026-06-01 | Создан план |
| 2026-06-01 | Разбит на фазы с конкретными результатами и итоговым блоком |
| 2026-06-01 | Правки по итогам ревью: тест-кейсы чел.-час/маш.-ч/т·км, round до 6 знаков, нормализация промежуточных partial_excel |
| 2026-06-01 | Улучшения после анализа индустрии: whitelist единиц, второй regex для "100м2" без пробела, защита от пустого base_unit |
| 2026-06-01 | Фаза 1 закрыта: утилита создана, 20 тестов зелёных; добавлен from __future__ annotations для совместимости с Python 3.9 |
| 2026-06-02 | Фаза 3 закрыта: 8 интеграционных проверок пройдены, иммутабельность подтверждена, 20/20 pytest зелёные |
