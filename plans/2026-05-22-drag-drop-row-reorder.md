# Drag-and-drop перемещение строк в редакторе сметы

## Статус

- [x] Реализовано

## Цель

Заменить кнопки ▲/▼ для перемещения строк в таблице EstimateGrid на drag-and-drop — как в Google Sheets. Убрать колонку со стрелками, добавить иконку-ручку (⠿) для захвата строки.

## Фазы

### Фаза 1: Рефакторинг EstimateGrid.tsx [x]

- Удалить `MoveCell`, `handleMoveRow`, `onMoveRow` из GridContextValue
- Добавить `DragHandleCell` с SVG-иконкой (6 точек)
- Добавить `onDragRowStart`, `onDragRowEnd` в GridContextValue
- Заменить `MOVE_COL` (52px) на `DRAG_COL` (32px)
- Добавить drag state: `draggingId`, `dropTarget: { id, above } | null`
- Реализовать `handleDragRowStart`, `handleDragRowEnd`, `handleContainerDragOver`, `handleContainerDrop`
- Обновить `rowClass`: добавить `row-dragging`, `row-drop-above`, `row-drop-below`
- Обернуть DataGrid в div с onDragOver/onDrop/onDragLeave

### Фаза 2: CSS [x]

- Удалить `.move-cell`, `.move-btn`, `.move-btn:hover`
- Добавить `.drag-handle-cell` (cursor: grab, цвет #cbd5e1)
- Добавить `.row-dragging` (opacity 0.35)
- Добавить `.row-drop-above` (box-shadow сверху, синяя линия)
- Добавить `.row-drop-below` (box-shadow снизу, синяя линия)

## Техническое решение

Использован HTML5 Drag and Drop API (без dnd-kit, несмотря на его наличие в проекте):
- `draggable` на иконке handle в DragHandleCell
- `document.elementFromPoint(x, y)` для определения целевой строки по aria-rowindex
- Кастомный ghost-образ (прозрачный div) чтобы не показывать стандартный ghost браузера
- Визуальная обратная связь через CSS box-shadow на целевой строке

## Итог

Реализовано полностью. Строки перемещаются захватом ручки (⠿), с синей линией-индикатором позиции вставки. TypeScript — 0 ошибок.
