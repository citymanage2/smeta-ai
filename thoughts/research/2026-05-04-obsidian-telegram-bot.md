# Research: Telegram-бот для обновления Obsidian через Claude API

**Дата:** 2026-05-04  
**Задача:** Бот принимает текст собрания → Claude извлекает задачи → обновляет .md файл в Obsidian vault

---

## Контекст задачи

- Пользователь: руководитель, работает с файлом один
- Ввод: текст (транскрибация/итоги собрания)
- Выход: обновлённый недельный .md файл в Obsidian vault
- Подтверждение: бот показывает изменения → пользователь нажимает ✅ → файл пишется
- Vault: ~/Desktop (или другая папка, задаётся в конфиге)

---

## Стек (финальный выбор)

| Компонент | Решение | Причина |
|---|---|---|
| Telegram бот | aiogram 3.x, polling mode | Локальный Mac, webhook не нужен |
| Claude API | anthropic SDK (уже в проекте) | ANTHROPIC_API_KEY уже в .env |
| Модель | claude-sonnet-4-6 | Та же что в smeta-ai |
| Структурный вывод | Pydantic + `messages.parse()` | Гарантированный JSON |
| Запись файла | asyncio.Lock + os.replace() | Атомарная запись, один процесс |
| Голос | Не нужен | Пользователь выбрал текст only |

---

## Существующий проект (smeta-ai)

- Claude клиент: `AsyncAnthropic` в `backend/app/services/claude_service.py`
- Модель: `claude-sonnet-4-6`
- Конфиг: pydantic BaseSettings, `.env` файл
- Зависимости: `anthropic>=0.55.0`, `httpx`, `aiofiles`

**Бот создаётся как standalone** в папке `tg_bot/` — не интегрируется в FastAPI.  
Переиспользует только `ANTHROPIC_API_KEY` из того же `.env`.

---

## Архитектура бота

```
tg_bot/
├── bot.py              # entry point, dp.start_polling()
├── handlers/
│   ├── __init__.py
│   └── text.py         # хендлер текста + FSM подтверждения
├── services/
│   ├── __init__.py
│   ├── claude.py       # extract_changes() → structured JSON
│   └── file_manager.py # read_weekly_file(), write_weekly_file()
├── config.py           # Settings: BOT_TOKEN, ANTHROPIC_API_KEY, VAULT_PATH
├── .env                # секреты (не в git)
└── requirements.txt
```

---

## Логика работы

```
Пользователь отправляет текст
        ↓
Claude читает: текущий .md файл + текст собрания
        ↓
Возвращает structured JSON:
  - changes: список изменений (для превью)
  - updated_content: полный обновлённый .md файл
        ↓
Бот показывает превью изменений + inline keyboard [✅ Записать] [❌ Отмена]
        ↓
Пользователь нажимает ✅
        ↓
Атомарная запись файла (tmpfile + os.replace)
        ↓
Obsidian автоматически подхватывает изменения
```

---

## Недельный файл

```python
from datetime import datetime

def get_weekly_file_path(vault_path: Path) -> Path:
    # ISO week: 2026-W19
    week = datetime.now().strftime("%G-W%V")
    return vault_path / "weekly" / f"{week}-tasks.md"
```

Если файл не существует — создаётся с базовым шаблоном.

---

## Claude промпт (стратегия)

Один вызов Claude, получаем:
1. `changes` — список строк: что добавлено/изменено/закрыто (для превью)
2. `updated_content` — полный текст обновлённого файла

Pydantic схема:
```python
class UpdateResult(BaseModel):
    changes: List[str]        # ["+ Иванов: кровля Ленина 45 до 14.05", ...]
    updated_content: str      # полный .md файл
```

---

## FSM состояния (aiogram)

```
None → (получен текст) → waiting_confirmation
waiting_confirmation → (✅) → None + файл записан
waiting_confirmation → (❌) → None
```

---

## Ключевые паттерны aiogram 3

```python
# polling (не webhook)
await dp.start_polling(bot, drop_pending_updates=True)

# asyncio.to_thread для блокирующих вызовов
result = await asyncio.to_thread(claude_call, text)

# inline keyboard для подтверждения
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
kb = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="✅ Записать", callback_data="confirm"),
    InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
]])
```

---

## Зависимости бота

```
aiogram>=3.7.0
anthropic>=0.55.0
python-dotenv>=1.0.0
```

---

## Рекомендация

**Реализовать в 3 фазы:**
1. Скелет бота (запускается, отвечает на /start, /status)
2. Claude интеграция (text → JSON preview)
3. File manager + подтверждение + запись

**Решение оптимальное** — минимум зависимостей, надёжная атомарная запись,  
полная совместимость с существующим .env проекта.
