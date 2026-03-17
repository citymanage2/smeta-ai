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
from app.services.excel_service import generate_list, generate_smeta, generate_smeta_detailed, generate_scan_result
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

PROMPT_SMETA_FROM_LIST = """Ты — снабженец/сметчик с опытом в строительстве. На основании предоставленного перечня работ и материалов составь полную смету для закупки/бюджетирования.

Прайс на работы: {price_list_works}

Прайс на материалы: {price_list_materials}

Текущая дата: {current_date}

Инструкции:

Шаг 1 — поиск в прайсах:

- Для каждой позиции ищи совпадение в соответствующем прайсе (нечёткий поиск по смыслу)

- Если найдено: запиши точное наименование из прайса в поле price_list_name, используй цену из прайса

- Если не найдено: переходи к Шагу 2

Шаг 2 — поиск цен в интернете (только для позиций не найденных в прайсе):

- Найди 3 актуальных цены на текущую дату в городе Екатеринбург, Свердловская область

- Используй нормальное качество: известные бренды, квалифицированные подрядчики с лицензиями/допусками СРО

- Без демпинга и сомнительных аналогов

- Поставь среднюю цену из трёх найденных

- Перечисли все 3 источника в поле sources

НДС для каждой позиции:

- Показывай три значения: цена без НДС / НДС / цена с НДС (ставка 22%)

- Для работ на УСН: НДС = 0, укажи это в notes

Верни результат СТРОГО в формате JSON без markdown блоков, без preamble текста, начиная с { :

{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование позиции",
      "unit": "Ед. изм.",
      "quantity": число,
      "work_price": число или null,
      "material_price": число или null,
      "price_list_name": "Точное наименование из прайса или null",
      "sources": "Источник 1: цена; Источник 2: цена; Источник 3: цена — или null если найдено в прайсе",
      "notes": "Примечание по НДС, УСН или другое"
    }
  ]
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до или после. Первый символ — {, последний — }"""

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


PROMPT_STAGE1_FROM_PROJECT = """Ты — опытный инженер-сметчик. Тебе предоставлена проектная документация.

Задача: составить подробный перечень всех работ и материалов, необходимых для реализации проекта.

Требования:
- Извлеки ВСЕ виды работ и материалов из документации
- Для каждой позиции определи единицу измерения и количество
- Разбей на категории: отдельно работы, отдельно материалы
- Если количество не определяется однозначно — укажи "?" и поясни в примечании
- Выводи строго в виде структурированного списка
- Язык вывода: русский

Формат каждой позиции:
[Тип: Работа/Материал] | [Наименование] | [Ед.изм.] | [Кол-во] | [Примечание]"""

PROMPT_STAGE1_FROM_EDC = """Ты — опытный инженер-сметчик. Тебе предоставлены два документа: проектная документация и ЭДЦ (элементные дефектные ведомости/ценники).

Задача: составить подробный перечень всех работ и материалов на основе ОБОИХ документов.

Требования:
- Сопоставь данные проекта и ЭДЦ
- Если позиция есть в обоих — объедини, укажи расхождение в примечании
- Если позиция только в проекте — пометь "только проект"
- Если позиция только в ЭДЦ — пометь "только ЭДЦ"
- Для каждой позиции определи единицу измерения и количество
- Если количество не определяется — укажи "?" и поясни
- Язык вывода: русский

Формат каждой позиции:
[Тип: Работа/Материал] | [Наименование] | [Ед.изм.] | [Кол-во] | [Источник: проект/ЭДЦ/оба] | [Примечание]"""

PROMPT_STAGE1_FROM_GRAND = """Ты — опытный инженер-сметчик. Тебе предоставлена смета в формате Гранд-Смета.

Задача: извлечь полный структурированный перечень всех работ и материалов из сметы Гранд.

Требования:
- Разбери структуру сметы Гранд: разделы, подразделы, позиции
- Для каждой позиции извлеки: наименование, единицу измерения, количество, расценку ГЭСН/ТЕР если указана
- Разбей на категории: работы и материалы
- Сохрани иерархию разделов сметы
- Язык вывода: русский

Формат каждой позиции:
[Раздел] | [Тип: Работа/Материал] | [Наименование] | [Код ГЭСН/ТЕР] | [Ед.изм.] | [Кол-во] | [Цена Гранд] | [Примечание]"""

PROMPT_STAGE2_SMETA = """Ты — снабженец/сметчик с опытом в строительстве.

На основании полученного перечня работ и материалов подготовь полную смету для закупки/бюджетирования.

Прайс на работы:
{price_list_works}

Прайс на материалы:
{price_list_materials}

Инструкции по ценообразованию:
1. Найди каждую позицию в соответствующем прайсе (нечёткий поиск — ищи по смыслу, не только по точному совпадению)
2. Если позиция найдена в прайсе — используй цену из прайса, в поле "price_list_name" запиши точное название из прайса
3. Если позиции нет в прайсе — найди актуальную цену в интернете:
   Регион: Россия, г. Екатеринбург, Свердловская область
   Период: актуальный на сегодня ({current_date})
   Класс: нормальные бренды, квалифицированные подрядчики с лицензиями/допусками СРО
   В поле "notes" укажи источник цены
4. Все цены указывай БЕЗ НДС (НДС будет рассчитан автоматически по ставке 22%)
5. Для работ подрядчика на УСН (если очевидно): usn=true, тогда НДС=0
6. Если количество не определено ("?") — оставь quantity=null, в notes поясни

Верни результат СТРОГО в формате JSON (без markdown блоков):
{{
  "items": [
    {{
      "type": "Работа" или "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "work_price": число или null,
      "mat_price": число или null,
      "usn": false,
      "price_list_name": "Точное название из прайса или источника" или null,
      "notes": "Примечание / источник цены"
    }}
  ]
}}

Язык: русский."""

PROMPT_STAGE2_GRAND = """Ты — снабженец/сметчик с опытом в строительстве.

На основании перечня из сметы Гранд подготовь рыночную смету для закупки/бюджетирования.

Прайс на работы:
{price_list_works}

Прайс на материалы:
{price_list_materials}

Инструкции по ценообразованию:
1. Для каждой позиции найди рыночную цену (не нормативную цену Гранд)
2. Сначала ищи в прайсах (нечёткий поиск по смыслу)
3. Если не найдено — ищи актуальную рыночную цену в интернете:
   Регион: Россия, г. Екатеринбург, Свердловская область
   Период: актуальный на сегодня ({current_date})
   Класс: нормальные бренды, квалифицированные подрядчики с лицензиями/допусками СРО
4. В поле "price_list_name" — точное название из прайса или источника
5. В поле "notes" — для позиций из Гранд укажи исходную цену Гранд для сравнения
6. Все цены указывай БЕЗ НДС (НДС будет рассчитан автоматически по ставке 22%)
7. Для работ подрядчика на УСН: usn=true

Верни результат СТРОГО в формате JSON (без markdown блоков):
{{
  "items": [
    {{
      "type": "Работа" или "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "work_price": число или null,
      "mat_price": число или null,
      "usn": false,
      "price_list_name": "Точное название из прайса или источника" или null,
      "notes": "Примечание / источник цены / цена Гранд"
    }}
  ]
}}

Язык: русский."""


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
        """Extract and parse JSON from Claude response, stripping preamble and fences."""
        import re

        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        stripped = re.sub(r'```(?:json)?\s*', '', response).strip()

        # Try direct parse after stripping fences
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        # Find the outermost JSON object (skip any text preamble)
        start = stripped.find('{')
        end = stripped.rfind('}')
        if start != -1 and end != -1 and end > start:
            candidate = stripped[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        logger.error("Failed to parse JSON response", response=response[:500])
        raise ValueError("Не удалось распознать ответ Claude как JSON")

    async def _call_claude_json(
        self,
        messages: list[dict],
        system_prompt: str,
        use_web_search: bool = False,
        image_data: Optional[list] = None,
    ) -> dict:
        """Call Claude and parse the JSON response, retrying once if parsing fails."""
        response = await call_claude(
            messages,
            system_prompt=system_prompt,
            use_web_search=use_web_search,
            image_data=image_data,
        )
        try:
            return self._parse_json_response(response)
        except ValueError:
            logger.warning("JSON parse failed on first attempt, retrying with explicit instruction", task_id=self.task_id)
            retry_messages = list(messages) + [
                {"role": "assistant", "content": response},
                {"role": "user", "content": "Ответь ТОЛЬКО валидным JSON, без преамбулы, без markdown, начиная с { и заканчивая }."},
            ]
            retry_response = await call_claude(
                retry_messages,
                system_prompt=system_prompt,
                use_web_search=False,
            )
            return self._parse_json_response(retry_response)

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
            elif task_type == "SMETA_FROM_PROJECT":
                await self._handle_smeta_from_project(task)
            elif task_type == "SMETA_FROM_EDC_PROJECT":
                await self._handle_smeta_from_edc(task)
            elif task_type == "SMETA_FROM_GRAND_PROJECT":
                await self._handle_smeta_from_grand(task)
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
        data = await self._call_claude_json(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )

        await self.update_progress("Обработка результатов...")
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

        # Inject price lists and current date if prompt uses template vars
        if "{price_list_works}" in prompt:
            from datetime import date
            await self.update_progress("Загрузка базы расценок...")
            await price_service.load_cache(self.db)
            works_text, mats_text = self._format_price_list_text()
            current_date = date.today().strftime("%d.%m.%Y")
            prompt = (
                prompt
                .replace("{price_list_works}", works_text)
                .replace("{price_list_materials}", mats_text)
                .replace("{current_date}", current_date)
            )

        messages, image_blocks = self._build_messages_with_files(task, prompt)

        await self.update_progress("Составление сметы с помощью ИИ (поиск цен)...")
        data = await self._call_claude_json(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=True,
            image_data=image_blocks if image_blocks else None,
        )

        await self.update_progress("Обработка результатов сметы...")
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
        data = await self._call_claude_json(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )

        await self.update_progress("Формирование Excel из распознанных данных...")

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
        data = await self._call_claude_json(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )

        await self.update_progress("Генерация отчёта о расхождениях...")

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


    def _format_price_list_text(self) -> tuple[str, str]:
        """Format DB price caches as text for use in Stage 2 prompt."""
        works_lines = []
        for w in price_service._works_cache[:300]:
            price = w.get("min_price") or ""
            unit = w.get("unit") or ""
            works_lines.append(f"- {w['name']} | {unit} | {price} руб.")
        works_text = "\n".join(works_lines) if works_lines else "(прайс пуст)"

        mats_lines = []
        for m in price_service._materials_cache[:300]:
            price = m.get("price") or ""
            unit = m.get("unit") or ""
            mats_lines.append(f"- {m['name']} | {unit} | {price} руб.")
        mats_text = "\n".join(mats_lines) if mats_lines else "(прайс пуст)"

        return works_text, mats_text

    async def _handle_two_stage_smeta(
        self,
        task: Task,
        stage1_prompt: str,
        stage2_prompt_template: str,
        file_suffix: str,
    ) -> None:
        """Common two-stage handler: extract list → build priced estimate."""
        from datetime import date

        # Stage 1: extract list
        await self.update_progress("Этап 1: извлечение перечня работ и материалов...")
        messages, image_blocks = self._build_messages_with_files(task, stage1_prompt)
        stage1_response = await call_claude(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )
        logger.info("Stage 1 complete", task_id=self.task_id, length=len(stage1_response))

        # Load price cache
        await self.update_progress("Загрузка базы расценок...")
        await price_service.load_cache(self.db)
        works_text, mats_text = self._format_price_list_text()

        # Stage 2: build priced estimate
        await self.update_progress("Этап 2: составление сметы с ценами (поиск по прайсу и интернету)...")
        current_date = date.today().strftime("%d.%m.%Y")
        # Use chained replace() instead of .format() to avoid KeyError when
        # price list entries contain literal { } characters.
        stage2_prompt = (
            stage2_prompt_template
            .replace("{price_list_works}", works_text)
            .replace("{price_list_materials}", mats_text)
            .replace("{current_date}", current_date)
            .replace("{{", "{")
            .replace("}}", "}")
        )
        stage2_messages = [
            {"role": "user", "content": f"Перечень работ и материалов:\n\n{stage1_response}\n\n{stage2_prompt}"}
        ]
        if task.user_prompt:
            stage2_messages[0]["content"] += f"\n\nДополнительные требования: {task.user_prompt}"

        data = await self._call_claude_json(
            stage2_messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=True,
        )

        await self.update_progress("Обработка результатов сметы...")
        items = data.get("items", [])
        if not items:
            raise ValueError("Claude не вернул позиции сметы. Проверьте содержимое документов.")

        await self.update_progress(f"Формирование Excel ({len(items)} позиций)...")
        excel_data = generate_smeta_detailed(items)
        file_name = f"{file_suffix}_{date.today().strftime('%Y-%m-%d')}.xlsx"
        await self.save_result(
            file_name,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            excel_data,
        )
        logger.info("Two-stage smeta completed", task_id=self.task_id, items=len(items))

    async def _handle_smeta_from_project(self, task: Task) -> None:
        await self._handle_two_stage_smeta(
            task,
            stage1_prompt=PROMPT_STAGE1_FROM_PROJECT,
            stage2_prompt_template=PROMPT_STAGE2_SMETA,
            file_suffix="SMETA_FROM_PROJECT",
        )

    async def _handle_smeta_from_edc(self, task: Task) -> None:
        await self._handle_two_stage_smeta(
            task,
            stage1_prompt=PROMPT_STAGE1_FROM_EDC,
            stage2_prompt_template=PROMPT_STAGE2_SMETA,
            file_suffix="SMETA_FROM_EDC_PROJECT",
        )

    async def _handle_smeta_from_grand(self, task: Task) -> None:
        await self._handle_two_stage_smeta(
            task,
            stage1_prompt=PROMPT_STAGE1_FROM_GRAND,
            stage2_prompt_template=PROMPT_STAGE2_GRAND,
            file_suffix="SMETA_FROM_GRAND_PROJECT",
        )


async def process_task(task_id: str, db: AsyncSession) -> None:
    """Entry point for background task processing."""
    processor = TaskProcessor(task_id, db)
    await processor.process()
