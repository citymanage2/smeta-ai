# Plan: Telegram-бот для обновления Obsidian через Claude API

**Создан:** 2026-05-04  
**Статус:** в работе

---

## Цель

Standalone Telegram-бот на Python.  
Пользователь скидывает текст итогов собрания → Claude извлекает задачи/изменения → бот показывает превью → после подтверждения обновляет недельный `.md` файл в Obsidian vault.

---

## Структура файлов

```
tg_bot/
├── bot.py              ← entry point, запуск polling
├── handlers/
│   ├── __init__.py
│   └── text.py         ← хендлер текста + FSM подтверждения
├── services/
│   ├── __init__.py
│   ├── claude.py       ← вызов Claude API, structured output
│   └── file_manager.py ← чтение/запись недельного .md
├── config.py           ← Settings pydantic
├── .env                ← BOT_TOKEN, ANTHROPIC_API_KEY, VAULT_PATH
└── requirements.txt
```

---

## Фазы

### Фаза 1: Скелет бота [x]

**Что делаем:**
- Создать директорию `tg_bot/`
- `requirements.txt` — aiogram, anthropic, python-dotenv
- `config.py` — Settings с полями BOT_TOKEN, ANTHROPIC_API_KEY, VAULT_PATH
- `.env` — шаблон (в .gitignore)
- `bot.py` — запуск polling, хендлер /start и /status

**Команды бота:**
- `/start` — приветствие + инструкция
- `/status` — показать путь к текущему недельному файлу и сколько задач в нём

**Acceptance criteria:**
- [ ] `python tg_bot/bot.py` запускается без ошибок
- [ ] Бот отвечает на /start в Telegram
- [ ] Бот отвечает на /status (даже если файла ещё нет)

---

### Фаза 2: Claude интеграция + превью [x]

**Что делаем:**
- `services/claude.py` — функция `extract_changes(current_file: str, meeting_notes: str) -> UpdateResult`
- Pydantic схема `UpdateResult(changes: List[str], updated_content: str)`
- `handlers/text.py` — принимает текст, вызывает Claude, показывает превью
- Inline keyboard: `[✅ Записать]` `[❌ Отмена]`
- FSM состояние `waiting_confirmation` — хранит `updated_content` до нажатия

**Claude промпт:**
```
Ты — ассистент для обновления рабочих задач.

Текущий файл задач на неделю:
{current_file}

Итоги собрания / новые инструкции:
{meeting_notes}

Обнови файл задач: добавь новые задачи, отметь выполненные [x], 
измени сроки и ответственных если упоминаются.
Сохраняй Obsidian markdown формат: [assignee:: Имя], 📅 YYYY-MM-DD

Верни:
- changes: список изменений на русском (что добавлено/изменено/закрыто)
- updated_content: полный обновлённый текст файла
```

**Acceptance criteria:**
- [ ] Бот принимает текст и отвечает превью изменений
- [ ] Показывает inline keyboard ✅/❌
- [ ] При ❌ — отменяет, ничего не пишет в файл
- [ ] FSM корректно хранит состояние ожидания

---

### Фаза 3: File manager + запись [x]

**Что делаем:**
- `services/file_manager.py`:
  - `get_weekly_path(vault_path)` → `vault_path/weekly/2026-W19-tasks.md`
  - `read_file(path)` → str (пустая строка если нет)
  - `write_file(path, content)` → атомарная запись (tmpfile + os.replace)
  - `create_weekly_template(week_str)` → базовый шаблон если файл новый
- При нажатии ✅ — `write_file()` → сообщение "Файл обновлён ✅"
- Папка `weekly/` создаётся автоматически если нет

**Шаблон нового недельного файла:**
```markdown
---
date: 2026-05-11
week: 2026-W19
---

# Задачи: 12–18 мая 2026
```

**Acceptance criteria:**
- [ ] При ✅ файл обновляется на диске
- [ ] Obsidian видит изменения (файл корректный markdown)
- [ ] Если файла не было — создаётся с шаблоном + добавляются задачи
- [ ] Папка `weekly/` создаётся автоматически

---

## Итог

- [x] Реализован целиком (2026-05-04)
- Осталось: настроить .env (BOT_TOKEN, ANTHROPIC_API_KEY, VAULT_PATH) и запустить
