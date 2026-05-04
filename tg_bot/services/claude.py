import asyncio
from typing import List
from pydantic import BaseModel
from anthropic import Anthropic
from config import settings

_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """Ты — ассистент для ведения рабочих задач в Obsidian markdown.
Твоя задача: обновить файл задач на основе итогов собрания.

Правила форматирования:
- Незакрытая задача: - [ ] Описание 📅 YYYY-MM-DD [assignee:: Имя]
- Закрытая задача: - [x] Описание
- Подзадачи: отступ 2 пробела перед - [ ]
- Объект в заголовке раздела: ## Объект: [[Название объекта]]
- Приоритет: ⏫ (высокий) 🔼 (средний)

Если в итогах собрания упоминается что задача выполнена — отмечай [x].
Если упоминается новый срок — обновляй 📅.
Если новый ответственный — обновляй [assignee::].
Новые задачи добавляй в соответствующий раздел объекта."""


class UpdateResult(BaseModel):
    changes: List[str]
    updated_content: str


def _call_claude(current_file: str, meeting_notes: str) -> UpdateResult:
    file_section = current_file if current_file.strip() else "(файл пустой — создай структуру с нуля)"

    response = _client.messages.create(
        model=MODEL,
        max_tokens=8096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Текущий файл задач:\n```\n{file_section}\n```\n\n"
                    f"Итоги собрания / новые инструкции:\n{meeting_notes}\n\n"
                    "Верни ответ строго в JSON:\n"
                    '{"changes": ["список изменений на русском"], "updated_content": "полный обновлённый markdown файл"}'
                ),
            }
        ],
    )

    raw = response.content[0].text.strip()

    # Извлекаем JSON из ответа (Claude иногда оборачивает в ```json)
    import json, re
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError(f"Claude не вернул JSON: {raw[:200]}")
    data = json.loads(match.group())
    return UpdateResult(**data)


async def extract_changes(current_file: str, meeting_notes: str) -> UpdateResult:
    return await asyncio.to_thread(_call_claude, current_file, meeting_notes)
