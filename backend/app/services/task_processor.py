import json
import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.models.task import Task
from app.models.result import TaskResult
from app.services.claude_service import call_claude
from app.services import price_service
from app.services.excel_service import generate_list, generate_smeta, generate_scan_result
from app.services.pdf_service import generate_comparison_report
from app.utils.file_parser import parse_file

logger = structlog.get_logger()

# ---- System prompts / task prompts ----

SYSTEM_BASE = (
    "Ты — эксперт по строительному сметному делу в России. "
    "Отвечай чётко, структурированно, на русском языке. "
    "Используй актуальные нормы и расценки (ФЕР/ТЕР/ГЭСН). "
    "При указании цен ссылайся на источник."
)

PROMPT_LIST_FROM_TZ = """Проанализируй техническое задание (ТЗ) и составь перечень работ и материалов.

Верни результат СТРОГО в формате JSON (без markdown блоков):
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "notes": "Примечание"
    }
  ]
}

Требования:
- Перечисли все виды работ, необходимые для выполнения ТЗ
- Перечисли все материалы с единицами измерения
- По возможности укажи количество (если в ТЗ есть объёмы)
- Работы и материалы должны быть логически полными и достаточными"""

PROMPT_LIST_FROM_TZ_PROJECT = """Проанализируй техническое задание (ТЗ) и проектную документацию, составь комплексный перечень работ и материалов.

Верни результат СТРОГО в формате JSON (без markdown блоков):
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "section": "Раздел проекта",
      "notes": "Примечание"
    }
  ]
}

Требования:
- Используй данные из ТЗ и проекта
- Соблюдай технологическую последовательность
- Учти все разделы проектной документации"""

PROMPT_SMETA_FROM_LIST = """На основе перечня работ и материалов составь строительную смету с ценами.

Для каждой позиции определи:
- Единичную расценку на работу (руб./ед.)
- Стоимость материала (руб./ед.)
- Итоговую стоимость

Верни результат СТРОГО в формате JSON (без markdown блоков):
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число,
      "work_price": число или null,
      "material_price": число или null,
      "notes": "Источник цены / примечание"
    }
  ]
}

Используй актуальные рыночные цены для России (текущий год).
Если цена неизвестна, укажи null и поясни в примечании."""

PROMPT_SMETA_FROM_TZ = """Проанализируй техническое задание и составь полную строительную смету.

Шаги:
1. Извлеки все виды работ и материалы из ТЗ
2. Определи объёмы
3. Назначь расценки

Верни результат СТРОГО в формате JSON (без markdown блоков):
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число,
      "work_price": число или null,
      "material_price": число или null,
      "notes": "Примечание"
    }
  ]
}"""

PROMPT_SMETA_FROM_TZ_PROJECT = """Составь строительную смету на основе ТЗ и проектной документации.

Проанализируй все документы, выдели все работы и материалы, назначь расценки.

Верни результат СТРОГО в формате JSON (без markdown блоков):
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число,
      "work_price": число или null,
      "material_price": число или null,
      "section": "Раздел",
      "notes": "Примечание"
    }
  ]
}"""

PROMPT_SCAN_TO_EXCEL = """Распознай содержимое строительной сметы из изображения/документа.

Извлеки все данные и верни СТРОГО в формате JSON (без markdown блоков):
{
  "header": {
    "title": "Название документа",
    "date": "Дата",
    "contractor": "Подрядчик",
    "object": "Объект строительства"
  },
  "sections": [
    {
      "title": "Название раздела",
      "items": [
        {
          "name": "Наименование работы/материала",
          "unit": "Ед. изм.",
          "qty": число или null,
          "price": число или null,
          "total": число или null,
          "notes": "Примечание"
        }
      ]
    }
  ],
  "summary": {
    "total_works": число или null,
    "total_materials": число или null,
    "total_vat": число или null,
    "grand_total": число или null
  }
}

Распознай все числа точно. Сохрани структуру разделов оригинального документа."""

PROMPT_COMPARE = """Сравни проектную документацию (проект) со строительной сметой.

Найди все расхождения по:
- Объёмам работ
- Составу материалов
- Видам работ (есть в проекте, нет в смете и наоборот)

Верни результат СТРОГО в формате JSON (без markdown блоков):
{
  "title": "Сравнительный анализ проект vs смета",
  "date": "дата",
  "project_name": "Название объекта",
  "summary": {
    "total_items": число,
    "matched": число,
    "discrepancies_count": число,
    "match_percent": число
  },
  "discrepancies": [
    {
      "item_name": "Наименование позиции",
      "project_value": "Значение по проекту",
      "smeta_value": "Значение по смете",
      "difference": "Разница",
      "severity": "critical" | "high" | "medium" | "low",
      "comment": "Пояснение"
    }
  ],
  "critical_issues": [
    {
      "title": "Заголовок",
      "description": "Описание критической проблемы"
    }
  ],
  "recommendations": [
    "Рекомендация 1",
    "Рекомендация 2"
  ]
}"""


class TaskProcessor:
    def __init__(self, task_id: str, db: AsyncSession):
        self.task_id = task_id
        self.db = db

    async def update_progress(self, message: str) -> None:
        result = await self.db.execute(
            select(Task).where(Task.id == self.task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            task.progress_message = message
            task.updated_at = datetime.now(timezone.utc)
            await self.db.commit()
        logger.info("Task progress", task_id=self.task_id, message=message)

    async def update_status(self, status: str, error: Optional[str] = None) -> None:
        result = await self.db.execute(
            select(Task).where(Task.id == self.task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            task.status = status
            task.updated_at = datetime.now(timezone.utc)
            if error:
                task.error_message = error
            await self.db.commit()

    async def save_result(self, file_name: str, mime_type: str, file_data: bytes) -> None:
        result_record = TaskResult(
            task_id=self.task_id,
            file_name=file_name,
            mime_type=mime_type,
            file_data=file_data,
        )
        self.db.add(result_record)
        await self.db.commit()

    def _build_file_contents(self, task: Task) -> list:
        """Build list of file content blocks/strings for Claude."""
        content_blocks = []
        for file_info in task.input_file_data or []:
            name = file_info.get("name", "")
            mime_type = file_info.get("mime_type", "")
            content_b64 = file_info.get("content_b64", "")
            if not content_b64:
                continue
            parsed = parse_file(name, mime_type, content_b64)
            content_blocks.append({"file_name": name, "content": parsed})
        return content_blocks

    def _build_messages_with_files(
        self, task: Task, prompt: str
    ) -> tuple[list[dict], list[dict]]:
        """
        Build Claude messages list and image blocks list.
        Returns (messages, image_blocks).
        """
        file_contents = self._build_file_contents(task)
        image_blocks = []
        text_parts = []

        for fc in file_contents:
            content = fc["content"]
            name = fc["file_name"]
            if isinstance(content, dict) and content.get("type") in ("image", "document"):
                image_blocks.append(content)
            else:
                text_parts.append(f"=== Файл: {name} ===\n{content}")

        full_prompt = prompt
        if text_parts:
            full_prompt = "\n\n".join(text_parts) + "\n\n" + prompt

        if task.user_prompt:
            full_prompt += f"\n\nДополнительные требования от пользователя: {task.user_prompt}"

        messages = [{"role": "user", "content": full_prompt}]

        # Add chat history
        for msg in task.chat_history or []:
            if msg.get("role") and msg.get("content"):
                messages.append({"role": msg["role"], "content": msg["content"]})

        return messages, image_blocks

    def _parse_json_response(self, response: str) -> dict:
        """Extract and parse JSON from Claude response."""
        import re
        # Try direct parse
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON block
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.error("Failed to parse JSON response", response=response[:500])
        raise ValueError("Не удалось распознать ответ Claude как JSON")

    async def process(self) -> None:
        """Main processing method."""
        try:
            await self.update_status("processing")
            await self.update_progress("Начало обработки задачи...")

            # Load task
            result = await self.db.execute(
                select(Task).where(Task.id == self.task_id)
            )
            task = result.scalar_one_or_none()
            if not task:
                raise ValueError(f"Задача {self.task_id} не найдена")

            logger.info(
                "Processing task",
                task_id=self.task_id,
                task_type=task.task_type,
            )

            # Route to handler
            task_type = task.task_type.upper()

            if task_type == "LIST_FROM_TZ":
                await self._handle_list_from_tz(task, PROMPT_LIST_FROM_TZ)
            elif task_type == "LIST_FROM_TZ_PROJECT":
                await self._handle_list_from_tz(task, PROMPT_LIST_FROM_TZ_PROJECT)
            elif task_type == "SMETA_FROM_LIST":
                await self._handle_smeta(task, PROMPT_SMETA_FROM_LIST)
            elif task_type == "SMETA_FROM_TZ":
                await self._handle_smeta(task, PROMPT_SMETA_FROM_TZ)
            elif task_type == "SMETA_FROM_TZ_PROJECT":
                await self._handle_smeta(task, PROMPT_SMETA_FROM_TZ_PROJECT)
            elif task_type == "SCAN_TO_EXCEL":
                await self._handle_scan_to_excel(task)
            elif task_type == "COMPARE_PROJECT_SMETA":
                await self._handle_compare(task)
            else:
                raise ValueError(f"Неизвестный тип задачи: {task.task_type}")

            await self.update_status("completed")
            await self.update_progress("Задача успешно выполнена")

        except Exception as e:
            logger.error("Task processing failed", task_id=self.task_id, error=str(e))
            await self.update_status("failed", error=str(e))
            await self.update_progress(f"Ошибка: {str(e)[:400]}")
            raise

    async def _handle_list_from_tz(self, task: Task, prompt: str) -> None:
        await self.update_progress("Анализ документов...")
        messages, image_blocks = self._build_messages_with_files(task, prompt)

        await self.update_progress("Формирование перечня с помощью ИИ...")
        response = await call_claude(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )

        await self.update_progress("Обработка результатов...")
        data = self._parse_json_response(response)
        items = data.get("items", [])

        if not items:
            raise ValueError("Claude не вернул позиции. Проверьте содержимое документов.")

        await self.update_progress(f"Найдено {len(items)} позиций. Формирование Excel...")
        excel_data = generate_list(items)

        await self.save_result("Перечень_работ_и_материалов.xlsx", 
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               excel_data)
        logger.info("List task completed", items=len(items))

    async def _handle_smeta(self, task: Task, prompt: str) -> None:
        await self.update_progress("Анализ документов...")
        messages, image_blocks = self._build_messages_with_files(task, prompt)

        await self.update_progress("Составление сметы с помощью ИИ (поиск цен)...")
        response = await call_claude(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=True,
            image_data=image_blocks if image_blocks else None,
        )

        await self.update_progress("Обработка результатов сметы...")
        data = self._parse_json_response(response)
        items = data.get("items", [])

        if not items:
            raise ValueError("Claude не вернул позиции сметы. Проверьте содержимое документов.")

        # Enrich with prices from DB cache
        await self.update_progress(f"Уточнение цен для {len(items)} позиций...")
        await price_service.load_cache(self.db)

        for item in items:
            item_type = item.get("type", "").lower()
            name = item.get("name", "")

            if item.get("work_price") is None and item_type in ("работа", "work"):
                price_data = await price_service.find_work_price(name)
                if price_data:
                    item["work_price"] = price_data.get("min_price")
                    if not item.get("notes"):
                        item["notes"] = "Цена из базы расценок"

            if item.get("material_price") is None and item_type in ("материал", "material"):
                price = await price_service.find_material_price(name)
                if price is not None:
                    item["material_price"] = price
                    if not item.get("notes"):
                        item["notes"] = "Цена из базы материалов"

        await self.update_progress(f"Генерация Excel-сметы ({len(items)} позиций)...")
        excel_data = generate_smeta(items)
        await self.save_result(
            "Смета.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            excel_data,
        )
        logger.info("Smeta task completed", items=len(items))

    async def _handle_scan_to_excel(self, task: Task) -> None:
        await self.update_progress("Распознавание документа...")
        messages, image_blocks = self._build_messages_with_files(task, PROMPT_SCAN_TO_EXCEL)

        await self.update_progress("Обработка изображения/документа с помощью ИИ...")
        response = await call_claude(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )

        await self.update_progress("Формирование Excel из распознанных данных...")
        data = self._parse_json_response(response)

        excel_data = generate_scan_result(data)
        await self.save_result(
            "Распознанная_смета.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            excel_data,
        )

        total_items = sum(
            len(s.get("items", [])) for s in data.get("sections", [])
        )
        logger.info("Scan task completed", items=total_items)

    async def _handle_compare(self, task: Task) -> None:
        await self.update_progress("Анализ проектной документации и сметы...")
        messages, image_blocks = self._build_messages_with_files(task, PROMPT_COMPARE)

        await self.update_progress("Сравнительный анализ с помощью ИИ...")
        response = await call_claude(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )

        await self.update_progress("Генерация отчёта о расхождениях...")
        data = self._parse_json_response(response)

        # Set date if not provided
        if not data.get("date"):
            data["date"] = datetime.now(timezone.utc).strftime("%d.%m.%Y")

        pdf_data = generate_comparison_report(data)
        await self.save_result(
            "Отчёт_сравнения.pdf",
            "application/pdf",
            pdf_data,
        )

        discrepancies_count = len(data.get("discrepancies", []))
        logger.info("Compare task completed", discrepancies=discrepancies_count)


async def process_task(task_id: str, db: AsyncSession) -> None:
    """Entry point for background task processing."""
    processor = TaskProcessor(task_id, db)
    await processor.process()
