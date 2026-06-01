# Уведомления о завершении задач

**Дата:** 2026-06-01  
**Статус:** В работе

---

## Цель

Пользователь запускает задачу (обработка сметы — занимает от 30 сек до нескольких минут) и переходит заниматься другим. Сейчас он вынужден сам возвращаться на страницу задачи чтобы узнать результат. Нужно уведомить его автоматически в момент завершения — звуком и всплывающим сообщением.

**Триггеры:** статус задачи меняется на `completed` или `failed`.  
**Охват:** глобальный — работает на любой странице приложения.  
**Формат уведомления:**  
- Успех: `"✓ Завершено · {Проект} · {Название задачи}"`  
- Ошибка: `"✗ Ошибка: {текст} · {Задача}"`

---

## Совместимость с браузерами

Целевые браузеры: **Google Chrome**, **Яндекс.Браузер**, **Safari (macOS)**.

| Функция | Chrome | Яндекс.Браузер | Safari macOS |
|---|---|---|---|
| Web Audio API / AudioContext | ✓ | ✓ (Chromium) | ✓ |
| AudioContext — стартует в `suspended` | да, всегда | да, всегда | да, всегда |
| Notifications API | ✓ | ✓ | ✓ (v6+) |
| `Notification.requestPermission()` → Promise | ✓ | ✓ | ✓ |
| sonner (CSS-анимации) | ✓ | ✓ | ✓ |
| Fetch / setInterval / Zustand | ✓ | ✓ | ✓ |

**Яндекс.Браузер** — основан на Chromium (Blink), поведение идентично Chrome. Отдельной обработки не требует.

**Safari macOS** — все используемые API поддерживаются. AudioContext стартует в `suspended` во всех браузерах (не только в Safari) — обрабатываем единым кодом.

**iOS Safari** — в план не входит. Приложение десктопное, внутренний инструмент. На iOS Notifications API работает только в PWA-режиме (установлено на рабочий стол), что нерелевантно.

---

## Гипотезы

1. Самый простой путь — глобальный Zustand-стор с polling'ом, смонтированный в `Layout.tsx`. Не нужны WebSocket/Service Worker.
2. Web Audio API даёт синтетический звук без аудиофайлов. AudioContext **обязан** быть инициализирован при первом пользовательском жесте (клик), иначе Chrome/Safari блокируют воспроизведение.
3. Toast-уведомления реализуются через библиотеку `sonner` (9KB) — быстрее и надёжнее кастомного компонента.
4. Браузер не показывает `Notification` если вкладка в фокусе → всегда показываем toast; браузерное уведомление — дополнительно при неактивной вкладке.

---

## Технические решения

### Архитектура

```
Layout.tsx
  ├── <Toaster />                 — sonner toast-контейнер
  └── useGlobalTaskPoller()       — невидимый хук, 1 штука на всё приложение
        ├── читает notificationStore.trackedTasks (через store.getState(), не хук — избегаем stale closure)
        ├── каждые 5с делает getTaskStatus() для задач, которые НЕ на текущей странице
        └── при смене статуса → notify() → removeTask()

notificationStore (Zustand)
  ├── trackedTasks: Map<taskId, TaskMeta>   — задачи под наблюдением
  ├── addTask(id, meta)
  └── removeTask(id)

notify(type, taskInfo)
  ├── playSound(type)              — Web Audio API (AudioContext pre-init)
  ├── toast.success(...) / toast.error(...)   — sonner
  └── new Notification(...)        — если разрешение дано
```

### Компоненты и файлы

| Файл | Что делает |
|---|---|
| `frontend/src/stores/notificationStore.ts` | Zustand-стор: tracked tasks, экшены `addTask / removeTask` |
| `frontend/src/hooks/useGlobalTaskPoller.ts` | Polling-хук, смонтированный в Layout |
| `frontend/src/utils/notify.ts` | Единая функция уведомления (sound + sonner toast + browser) |
| `frontend/src/utils/notificationSound.ts` | Web Audio API синтез звука, AudioContext pre-init |
| Изменения в `frontend/src/components/Layout.tsx` | Монтируем хук и `<Toaster />` из sonner |
| Изменения в `frontend/src/pages/TaskStatus.tsx` | При монтировании — НЕ добавлять задачу в store (пользователь уже видит статус) |
| Изменения в `frontend/src/pages/TaskCreate.tsx` | После создания задачи → `addTask(id, { projectName, taskName })` |

### Звук

Используем Web Audio API (без аудиофайлов):
- **Успех**: два тона вверх (C5 → E5, 80мс + 150мс)
- **Ошибка**: один низкий затухающий тон (B3, 400мс)

**Обязательно:** `AudioContext` создаётся один раз при первом `click` по `document` и хранится в module-level переменной. Не создавать контекст в момент вызова `playSound()` — Chrome/Safari заблокируют без user gesture.

```ts
let ctx: AudioContext | null = null;
document.addEventListener('click', () => {
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === 'suspended') ctx.resume(); // вызываем resume() при каждом клике — Safari/Chrome могут снова перевести в suspended после паузы
}, { once: false });
```

> `ctx.resume()` вызывается при каждом клике (не только при создании) — браузер может перевести контекст обратно в `suspended` после длительной неактивности. `{ once: false }` — намеренно.

### Toast

Используем **sonner**: `npm install sonner`.

```tsx
// Layout.tsx
import { Toaster } from 'sonner';
// ...
<Toaster position="bottom-right" richColors />

// notify.ts
import { toast } from 'sonner';
toast.success(`✓ Завершено · ${projectName} · ${taskName}`, { duration: 6000 });
toast.error(`✗ Ошибка: ${errorText} · ${taskName}`, { duration: 6000 });
```

Клик по toast → навигация на страницу задачи через `onClick` в `toast.success({ action: ... })`.

**Важно:** `notify.ts` — это утилита вне React-компонента. `navigate` из `useNavigate()` нельзя вызвать из обычной функции. Сигнатура `notify()` принимает `navigate` как параметр:

```ts
// notify.ts
import { NavigateFunction } from 'react-router-dom';

export function notify(
  type: 'success' | 'error',
  taskInfo: { taskId: string; projectName: string; taskName: string; errorText?: string },
  navigate?: NavigateFunction,
) {
  // ...
  toast.success(`✓ Завершено · ${taskInfo.projectName} · ${taskInfo.taskName}`, {
    duration: 6000,
    action: navigate
      ? { label: 'Открыть', onClick: () => navigate(`/tasks/${taskInfo.taskId}/status`) }
      : undefined,
  });
}
```

`navigate` передаётся из `useGlobalTaskPoller`, который имеет доступ к `useNavigate()`.

### Разрешение браузера

- Запрашиваем разрешение один раз при первой завершённой задаче (не в момент входа).
- Если пользователь отказал — работает только toast + звук.

### Known limitations

- **Page refresh:** store in-memory. Если пользователь создал задачу, перешёл на другую страницу и обновил её — задача выйдет из отслеживания и уведомление не придёт. Это ожидаемое поведение для MVP, не баг.
- **Несколько вкладок:** каждая вкладка ведёт собственный polling и пришлёт своё уведомление. Ожидаемо.
- **Upgrade path:** если в будущем вырастет нагрузка — polling заменяется на SSE (`EventSource`) без изменения логики notify/store. SSE — однонаправленный стриминг, меньше HTTP-overhead, подходит для уведомлений. WebSocket избыточен (двусторонний канал).

---

## Фазы реализации

### Фаза 1 — Стор и утилиты [x]

**Результат:** три новых файла, приложение собирается без ошибок.

- [x] `npm install sonner` — добавить зависимость
- [x] Создать `frontend/src/stores/notificationStore.ts` — Zustand-стор с `trackedTasks` (Map), экшены `addTask / removeTask`
- [x] Создать `frontend/src/utils/notificationSound.ts` — Web Audio API; AudioContext инициализируется при первом `click` на `document` (module-level listener), не в момент воспроизведения; экспортирует `playSuccess()` и `playError()`
- [x] Создать `frontend/src/utils/notify.ts` — вызывает `playSound`, `toast.success/error` из sonner, `new Notification(...)` (с запросом разрешения при первом вызове)

---

### Фаза 2 — Toast через sonner [x]

**Результат:** тосты отображаются в правом нижнем углу на любой странице, исчезают через 6 секунд, закрываются кнопкой, клик ведёт на страницу задачи.

- [x] Добавить `<Toaster position="bottom-right" richColors />` в `frontend/src/components/Layout.tsx`
- [x] В `notify.ts` реализовать toast через `toast.success(...)` и `toast.error(...)` с `action: { label: 'Открыть', onClick: () => navigate(...) }`

> Кастомный `ToastContainer.tsx` не создаётся — используем sonner.

---

### Фаза 3 — Глобальный поллер [x]

**Результат:** фоновый процесс опрашивает бэкенд каждые 5 сек и при изменении статуса вызывает `notify()`.

- [x] Создать `frontend/src/hooks/useGlobalTaskPoller.ts`:
  - Интервал 5 сек, cleanup через `return () => clearInterval(id)` в useEffect (обязательно — иначе memory leak)
  - Читать `trackedTasks` через `useNotificationStore.getState().trackedTasks` внутри callback, не через хук — избегаем stale closure
  - Перед каждым poll проверять: если пользователь на странице задачи — пропустить её (пользователь уже видит статус, иначе двойные запросы: `TaskStatus.tsx` сам опрашивает каждые 3 сек). Использовать `window.location.pathname` (не `useLocation()` — устареет в closure):
    ```ts
    if (window.location.pathname.startsWith(`/tasks/${taskId}`)) continue;
    ```
    > Путь в приложении: `/tasks/${taskId}/status`, не `/task/${taskId}`. Проверка через `startsWith` покрывает все суффиксы (`/status`, `/estimate`).
  - Передавать `navigate` (из `useNavigate()`) в `notify()` для кнопки «Открыть» в toast
  - При `completed` / `failed` → `notify(type, taskInfo, navigate)` → `removeTask()`
  - Ошибки API: логировать в console, не бросать исключение — поллер должен продолжить работу
- [x] Смонтировать хук в `Layout.tsx` (один экземпляр на всё приложение)

---

### Фаза 4 — Регистрация задач [x]

**Результат:** новые задачи автоматически попадают в стор и отслеживаются.

- [x] В `frontend/src/pages/TaskCreate.tsx`: после успешного `createTask()` → `addTask(id, { projectName, taskName })`. Убедиться что `projectName` доступен в момент регистрации (читать из формы или из текущего контекста проекта, не из ответа API).
- [x] В `frontend/src/pages/TaskStatus.tsx`: **не** добавлять задачу в `notificationStore` при монтировании — пользователь уже на странице задачи, уведомление избыточно. Когда пользователь уходит со страницы (если статус ещё активный) — добавить в store через `useEffect` cleanup (не `beforeunload` — в SPA React Router `beforeunload` не срабатывает при навигации между страницами).

> Двойная регистрация (TaskCreate → redirect → TaskStatus) не проблема: Map деплицирует по ID.

---

### Фаза 5 — Ручное тестирование [ ]

**Результат:** все сценарии проверены вручную, баги исправлены.

- [ ] Запустить задачу → перейти на другую страницу → дождаться завершения → проверить toast и звук
- [ ] Toast исчезает через 6 сек автоматически
- [ ] Клик по toast ведёт на страницу задачи
- [ ] При первом уведомлении браузер запрашивает разрешение на Notifications
- [ ] Если задача завершилась с ошибкой — toast с ошибкой, звук ошибки
- [ ] Несколько одновременных задач → несколько toast'ов стекаются корректно
- [ ] **Звук:** перед запуском задачи кликнуть по странице — проверить что AudioContext инициализирован и звук воспроизводится
- [ ] **Refresh:** создать задачу → уйти → обновить страницу → уведомление НЕ приходит (ожидаемо, known limitation)
- [ ] **TaskStatus:** открыть страницу задачи пока она processing → убедиться что глобальный поллер не дублирует запросы (проверить Network tab в DevTools): должен быть только один запрос каждые 3 сек (от TaskStatus), не два
- [ ] **Нет уведомления на TaskStatus:** создать задачу → остаться на странице TaskStatus → дождаться завершения → уведомление **не** должно прийти (пользователь уже видит результат на экране)
- [ ] **Несколько вкладок:** открыть приложение в двух вкладках → каждая вкладка пришлёт своё уведомление (ожидаемо)

---

## Итог

- [ ] Реализован целиком
- [x] Фаза 1 завершена
- [x] Фаза 2 завершена
- [x] Фаза 3 завершена
- [x] Фаза 4 завершена
- [ ] Фаза 5 завершена (ручное тестирование — выполняется пользователем)

**Что осталось:** Фаза 5 — ручное тестирование сценариев пользователем.
