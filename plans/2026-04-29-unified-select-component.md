# Единый Select-компонент

Дата: 2026-04-29

## Задача

Заменить все нативные `<select>` в проекте на единый Radix UI компонент в стиле из промпта пользователя.

## Фазы

- [x] Фаза 1: Установка зависимости `@radix-ui/react-select`
- [x] Фаза 2: Создание компонента `frontend/src/components/ui/Select.tsx` + `Select.css`
- [x] Фаза 3: Замена нативных select во всех файлах
  - [x] `TaskTypeSelector.tsx`
  - [x] `PriceCatalog.tsx` (4 вхождения)
  - [x] `TaskCreate.tsx` (2 вхождения, включая optgroup → SelectGroup/SelectLabel)
  - [x] `TaskStatus.tsx`
  - [x] `Admin.tsx` (2 вхождения)
  - [x] `Calculator.tsx`
- [x] Фаза 4: TypeScript-проверка (0 ошибок)

## Итог

Реализован целиком. Все 9 нативных `<select>` заменены на `AppSelect`-компонент (Radix UI + CSS, без Tailwind).
