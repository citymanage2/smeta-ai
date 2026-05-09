import asyncio
import base64
import json
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.models.task import Task
from app.models.result import TaskResult
from app.models.task_input_file import TaskInputFile
from app.models.estimate_version import EstimateVersion
from app.services.claude_service import call_claude
from app.services.excel_service import generate_list
from app.services.estimate_parser import parse_estimate_excel
from app.constants import ESTIMATE_TASK_TYPES
from app.utils.xlsx_cost_parser import extract_total_cost, parse_list_sheet
from app.utils.file_parser import parse_file, parse_xlsx_grand, chunk_rows, rows_to_text
from app.utils.pdf_text_extractor import chunk_project_pdf
from app.utils.pdf_ocr_extractor import extract_pdf_with_ocr, chunk_pdf_pages
from app.utils.json_utils import extract_json
from app.utils.xlsx_exporter import generate_estimate_xlsx
from app.services import price_service as _price_svc

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# System prompt — базовый для всех типов задач
# ---------------------------------------------------------------------------

SYSTEM_BASE = (
    "IMPORTANT: When the task requires JSON output, return ONLY raw JSON without any "
    "markdown formatting, code blocks, backticks, or explanations. "
    "Start your response directly with { or [ and end with } or ]. "
    "Do not wrap JSON in ```json ... ``` or any other markup. "
    "\n\n"
    "Ты — эксперт по строительному сметному делу в России. "
    "Отвечай чётко, структурированно, на русском языке. "
    "Используй актуальные нормы и расценки (ФЕР/ТЕР/ГЭСН). "
    "При указании цен ссылайся на источник."
)

# ---------------------------------------------------------------------------
# Задача 1: Перечень из Гранд-сметы
# ---------------------------------------------------------------------------

PROMPT_LIST_FROM_GRAND = """Ты — опытный инженер-сметчик.

Задача: составить перечень работ и материалов на основании гранд-сметы.

Извлеки из гранд-сметы все позиции — работы и материалы — точно так, как они указаны в файле. Ничего не добавляй от себя, не дополняй по нормативам, не изменяй наименования.

ПОРЯДОК СТРОК В ПЕРЕЧНЕ — строго соблюдать:
Работа 1
  Материал 1 к Работе 1
  Материал 2 к Работе 1
  ...
Работа 2
  Материал 1 к Работе 2
  ...

Каждый вид работы должен идти ПЕРВОЙ строкой, затем сразу все материалы к этой работе.

Верни результат СТРОГО в формате JSON, без markdown блоков, без preamble текста, первый символ {, последний }:
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "notes": ""
    }
  ]
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }."""

PROMPT_LIST_FROM_GRAND_PDF = """Ты — опытный инженер-сметчик.

Тебе передан текст, распознанный из PDF-скана гранд-сметы. Текст может содержать артефакты OCR (лишние символы, разрывы строк, перепутанные символы). Восстанавливай смысл по контексту.

Задача: извлечь все позиции — работы и материалы — точно как в документе. Ничего не добавляй от себя.

ПРОПУСКАЙ строки:
- итого, всего, НДС, сметная прибыль, накладные расходы, непредвиденные затраты
- коэффициенты и поправки
- шифры расценок (ТЕР-xx-xx-xx, ФЕРр-xx, ГЭСН-xx и т.д.) если они стоят отдельной строкой без наименования работы
- заголовки разделов и глав

ПОРЯДОК: Работа 1 → её Материалы → Работа 2 → её Материалы → ...

Верни результат СТРОГО в формате JSON, без markdown блоков, без preamble текста, первый символ {, последний }:
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "notes": ""
    }
  ]
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }."""

PROMPT_CHECK_COMPLETENESS = """Ты — опытный инженер-сметчик со знанием нормативной базы РФ (ГЭСН-2017/ФСНБ-2022, ФЕР/ТЕР по Свердловской области, СП, ГОСТ).

Задача: проверить полноту учтённых материалов для каждой работы в перечне.

Тебе передан готовый перечень работ и материалов. Для каждой работы:
1. Проверь, все ли необходимые материалы учтены согласно нормативной базе ГЭСН/ФСНБ-2022.
2. Если материал есть, но объём не указан или явно некорректен — рассчитай объём по нормам ГЭСН исходя из объёма работ.
3. Если нормативно необходимый материал отсутствует — добавь его.
4. Если материал и объём корректны — оставь без изменений.

В поле notes для каждой изменённой или добавленной позиции указывай обоснование:
- "Добавлено по ГЭСН XX-XX-XXX: [обоснование]"
- "Объём скорректирован: в перечне [X] [ед], скорректировано на [Y] [ед] по норме ГЭСН [норма]"
- "Соответствует норме" — если позиция корректна

После проверки добавь поле "changes_summary" — краткий текст с перечнем всех добавленных и скорректированных позиций.

Верни результат СТРОГО в формате JSON, без markdown блоков, без preamble текста, первый символ {, последний }:
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "notes": "Обоснование"
    }
  ],
  "changes_summary": "Краткое резюме всех изменений"
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }."""


PROMPT_LIST_FROM_PROJECT = """Ты — опытный инженер-сметчик и специалист по чтению проектной документации.

Задача: составить перечень работ и материалов СТРОГО на основании проектной документации. Ничего не добавляй от себя по нормативам — только то, что следует из проекта.

ЧТО ИЗВЛЕКАТЬ:
1. Все виды работ — из спецификаций, ведомостей, пояснительной записки, а также логически следующие из состава проекта (демонтаж, подготовка основания, подключение и т.п.), если они явно подразумеваются.
2. Все материалы к каждой работе — из спецификаций и ведомостей.

ПОРЯДОК СТРОК — строго соблюдать:
Работа 1
  Материал 1 к Работе 1
  Материал 2 к Работе 1
  ...
Работа 2
  Материал 1 к Работе 2
  ...

РАЗДЕЛЫ: если есть явные разделы (АР, КР, ОВиК, ЭОМ, ВК и т.п.) — указывай раздел в поле notes каждой позиции.

ОБЪЁМЫ — определяй по приоритету:

  1. Явно указан в спецификации / ведомости → используй как есть, notes оставь с разделом.

  2. Не указан явно, но можно вычислить по чертежам / схемам / планам / экспликациям
     (сложить площади помещений, измерить длину по плану, посчитать элементы и т.п.) →
     ОБЯЗАТЕЛЬНО: выполни расчёт, итоговое число запиши в quantity (не null!),
     в notes укажи: "Объём определён по чертежу: [формула и источник, напр. 2.36+2.94+33.45=38.75 м² по экспликации АС лист 9]"

  3. Определить невозможно ни из спецификации, ни из чертежей →
     quantity = null,
     в notes ОБЯЗАТЕЛЬНО укажи: "Объём не определён: [причина]. Для расчёта необходимо: [откуда взять — напр. план этажа с размерами / ведомость помещений / разрез с отметками]"

КРИТИЧЕСКИ ВАЖНО: если ты произвёл расчёт и получил число — это число ДОЛЖНО быть в поле quantity. Поле quantity не может быть null, если ты написал расчёт в notes.

Верни результат СТРОГО в формате JSON, без markdown блоков, без preamble текста, первый символ {, последний }:
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм. или пустая строка",
      "quantity": число или null,
      "notes": "Раздел документа / обоснование объёма"
    }
  ]
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }."""

PROMPT_LIST_FROM_PROJECT_PASS2 = """Ты — опытный инженер-сметчик. Из проектной документации уже составлен перечень, но для некоторых позиций объём остался незаполненным (quantity = null).

Тебе снова предоставлен тот же PDF. Твоя ЕДИНСТВЕННАЯ задача — найти числа и посчитать.

АЛГОРИТМ для каждой позиции:

1. Прочитай поле notes — там уже указано, на каком листе / в какой таблице искать.
2. Открой этот лист в PDF и выполни подсчёт:
   - Если нужно посчитать количество элементов (гильзы, отверстия, опоры, колонны и т.п.) — пересчитай каждый элемент на чертеже вручную.
   - Если нужно сложить площади или длины из таблицы — сложи все строки.
   - Если нужно перемножить размеры — найди размеры и перемножь.
3. Итоговое число запиши в quantity.
4. В notes напиши: что нашёл, на каком листе, формулу и результат.
   Пример: "Подсчитано по плану вентиляции лист 4: 12 проходов через стены + 6 через перегородки = 18 шт."

АБСОЛЮТНЫЙ ЗАПРЕТ:
- Если в notes написано на каком листе / плане смотреть — quantity НЕ МОЖЕТ быть null. Открой этот лист и посчитай.
- Нельзя писать "требуется подсчёт по...", "необходимо посчитать по..." — ты должен сам это сделать прямо сейчас.
- Нельзя писать "объём не определён" если ты знаешь где данные находятся.
- КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО придумывать, угадывать или приблизительно оценивать quantity. Число в quantity — только то, что явно следует из документа: подсчитано на чертеже, прочитано из таблицы, вычислено по размерам из документа. Любое "примерно", "ориентировочно", "типично для таких объектов" — это фальсификация сметы, недопустимо.

Оставить quantity = null разрешено ТОЛЬКО если документ реально не содержит нужных данных (не тот раздел проекта, отсутствует лист). В notes — только что именно отсутствует.

КРИТИЧЕСКИ ВАЖНО: верни РОВНО столько позиций, сколько получил, в том же порядке.

Верни СТРОГО в формате JSON, без markdown, первый символ {, последний }:
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "notes": "Обоснование"
    }
  ]
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }."""

PROMPT_CHECK_PROJECT_COMPLETENESS = """Ты — опытный инженер-сметчик со знанием нормативной базы РФ (ГЭСН-2017/ФСНБ-2022, ФЕР/ТЕР по Свердловской области, СП, ГОСТ).

Задача: проверить полноту учтённых материалов для каждой работы в перечне.

Тебе передан готовый перечень работ и материалов из проектной документации. Для каждой работы:
1. Проверь, все ли необходимые материалы учтены согласно нормативной базе ГЭСН/ФСНБ-2022.
2. Если материал есть, но объём не указан или явно некорректен — рассчитай объём по нормам ГЭСН исходя из объёма работ.
3. Если нормативно необходимый материал отсутствует — добавь его.
4. Если материал и объём корректны — оставь без изменений.

В поле notes для каждой изменённой или добавленной позиции указывай обоснование:
- "Добавлено по ГЭСН XX-XX-XXX: [обоснование]"
- "Объём скорректирован: в перечне [X] [ед], скорректировано на [Y] [ед] по норме ГЭСН [норма]"
- "Соответствует норме" — если позиция корректна

После проверки добавь поле "changes_summary" — краткий текст с перечнем всех добавленных и скорректированных позиций.

Верни результат СТРОГО в формате JSON, без markdown блоков, без preamble текста, первый символ {, последний }:
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "notes": "Обоснование"
    }
  ],
  "changes_summary": "Краткое резюме всех изменений"
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }."""

PROMPT_ESTIMATE_FROM_LIST = """Ты — эксперт по строительному сметному делу в России.

Тебе переданы позиции перечня работ и материалов, для которых НЕ
найдено совпадений в корпоративном прайсе. Твоя задача — определить
рыночную цену для каждой позиции.

Текущая дата: {current_date}
Регион: г. Екатеринбург, Свердловская область

Для каждой позиции:
1. Найди 3 актуальных рыночных цены (г. Екатеринбург)
   - Для работ: квалифицированные подрядчики с лицензиями/допусками СРО
   - Для материалов: известные поставщики, нормальное качество
2. Поставь среднюю из трёх найденных цен
3. Укажи все 3 источника с ценами в поле sources
4. Цена работ → в поле work_price (если тип "Работа")
5. Цена материалов → в поле material_price (если тип "Материал")

НДС (22%): для каждой позиции укажи в notes:
  "Цена без НДС: X / НДС: Y / Цена с НДС: Z"
  Для работ на УСН: НДС = 0, указать "УСН, НДС не облагается"

КРИТИЧЕСКИ ВАЖНО: каждая входная позиция имеет числовое поле "id".
Ты ОБЯЗАН вернуть результат для КАЖДОЙ позиции из списка, сохранив то же самое
значение "id" без изменений. Пропуск любой позиции недопустим.

Позиции для оценки:
{unmatched_items_json}

Верни результат СТРОГО в формате JSON, без markdown, первый символ {{,
последний }}:
{{
  "items": [
    {{
      "id": число (то же, что во входных данных — не менять!),
      "type": "Работа" | "Материал",
      "name": "Наименование позиции",
      "unit": "Ед. изм.",
      "quantity": число,
      "work_price": число или null,
      "material_price": число или null,
      "price_list_name": null,
      "sources": "Источник 1: цена; Источник 2: цена; Источник 3: цена",
      "notes": "Примечание по НДС"
    }}
  ]
}}"""


def _chunk_by_work_boundaries(items: list, max_chunk_size: int = 200) -> list:
    """Split items into chunks, always starting a new chunk at a 'Работа' boundary."""
    if not items:
        return []
    chunks = []
    current_chunk: list = []
    for item in items:
        is_work = item.get("type", "").strip() == "Работа"
        if is_work and current_chunk and len(current_chunk) >= max_chunk_size:
            chunks.append(current_chunk)
            current_chunk = []
        current_chunk.append(item)
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


class TaskCancelledError(Exception):
    """Raised when a task has been cancelled by the user."""


class TaskProcessor:
    def __init__(self, task_id: str, db: AsyncSession):
        self.task_id = task_id
        self.db = db
        self._input_files_cache: list[dict] | None = None

    async def _load_input_files(self, task: Task) -> list[dict]:
        """Return input files with content_b64, loading from task_input_files table.

        Falls back to task.input_file_data for old tasks that still store content_b64 inline.
        Result is cached so repeated calls within one processor run are cheap.
        """
        if self._input_files_cache is not None:
            return self._input_files_cache

        # New tasks: content stored in task_input_files, not in the JSON column
        result = await self.db.execute(
            select(TaskInputFile)
            .where(TaskInputFile.task_id == self.task_id)
            .order_by(TaskInputFile.file_index)
        )
        rows = result.scalars().all()
        if rows:
            self._input_files_cache = [
                {
                    "name": r.file_name,
                    "mime_type": r.mime_type,
                    "size_bytes": r.size_bytes,
                    "content_b64": base64.b64encode(r.content).decode("utf-8"),
                }
                for r in rows
            ]
            return self._input_files_cache

        # Old tasks: content_b64 stored directly in input_file_data JSON column
        self._input_files_cache = task.input_file_data or []
        return self._input_files_cache

    async def _check_cancelled(self) -> None:
        """Raise TaskCancelledError if the task status is 'cancelled' in the DB."""
        result = await self.db.execute(
            select(Task).where(Task.id == self.task_id)
        )
        task = result.scalar_one_or_none()
        if task and task.status == "cancelled":
            raise TaskCancelledError("Задача остановлена пользователем")

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
            if status == "completed":
                task.progress_message = None
            if error:
                task.error_message = error
            await self.db.commit()

    @staticmethod
    def _result_filename(task: Task, fallback: str) -> str:
        """Return sanitized task name + .xlsx, or fallback if name is empty."""
        import re
        name = (task.name or "").strip()
        if not name:
            return fallback
        safe = re.sub(r'[\\/:*?"<>|]', "_", name)
        safe = re.sub(r"\s+", "_", safe)
        safe = safe[:100]
        return f"{safe}.xlsx"

    async def save_result(self, file_name: str, mime_type: str, file_data: bytes, slot: str = "result") -> None:
        result_record = TaskResult(
            task_id=self.task_id,
            file_name=file_name,
            mime_type=mime_type,
            file_data=file_data,
            size_bytes=len(file_data),
            slot=slot,
        )
        self.db.add(result_record)
        await self.db.commit()

    async def _create_initial_generic_version(self, file_data: bytes, task_type: str) -> None:
        """Create V0 EstimateVersion for LIST/COMPLETENESS tasks (idempotent)."""
        import uuid as _uuid
        from app.models.estimate_version import EstimateVersion
        from app.utils.xlsx_generic import parse_xlsx_to_generic_rows

        existing = await self.db.execute(
            select(EstimateVersion).where(
                EstimateVersion.task_id == self.task_id,
                EstimateVersion.file_slot == "result",
            ).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            return

        rows = parse_xlsx_to_generic_rows(file_data)
        version = EstimateVersion(
            id=str(_uuid.uuid4()),
            task_id=self.task_id,
            version_number=0,
            version_label="original",
            version_display_name="V0 — Оригинал",
            rows=rows,
            file_slot="result",
            task_type=task_type,
        )
        self.db.add(version)
        await self.db.commit()

    async def _save_progress_data(self, data: dict) -> None:
        result = await self.db.execute(select(Task).where(Task.id == self.task_id))
        task = result.scalar_one_or_none()
        if task:
            task.progress_data = data
            task.updated_at = datetime.now(timezone.utc)
            await self.db.commit()

    async def _auto_fill_estimate_slot(self) -> None:
        """Promote slot='result' → 'estimate' and set estimation_status after task completes.

        Called automatically when an ESTIMATE_TASK_TYPE (except OPTIMIZE_SMETA, which
        manages its own slots) transitions to 'completed'.
        """
        task_res = await self.db.execute(select(Task).where(Task.id == self.task_id))
        task = task_res.scalar_one_or_none()
        if not task or task.task_type not in ESTIMATE_TASK_TYPES or task.task_type == "OPTIMIZE_SMETA":
            return

        result_res = await self.db.execute(
            select(TaskResult)
            .where(TaskResult.task_id == self.task_id, TaskResult.slot == "result")
            .order_by(TaskResult.created_at.desc())
            .limit(1)
        )
        result_row = result_res.scalar_one_or_none()

        if not result_row:
            task.estimation_status = "unestimated"
            task.updated_at = datetime.now(timezone.utc)
            await self.db.commit()
            return

        result_row.slot = "estimate"

        cost = None
        xlsx_mimes = {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
        }
        if result_row.mime_type in xlsx_mimes:
            try:
                cost = extract_total_cost(result_row.file_data)
            except Exception:
                pass

        task.estimation_status = "estimated"
        task.cost = cost
        task.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        logger.info("Auto-filled estimate slot", task_id=self.task_id, cost=cost)

    async def _build_file_contents(self, task: Task) -> list:
        """Build list of file content blocks/strings for Claude."""
        files = await self._load_input_files(task)
        content_blocks = []
        for file_info in files:
            name = file_info.get("name", "")
            mime_type = file_info.get("mime_type", "")
            content_b64 = file_info.get("content_b64", "")
            if not content_b64:
                continue
            parsed = parse_file(name, mime_type, content_b64)
            content_blocks.append({"file_name": name, "content": parsed})
        return content_blocks

    async def _build_messages_with_files(
        self, task: Task, prompt: str
    ) -> tuple[list[dict], list[dict]]:
        """
        Build Claude messages list and image blocks list.
        Returns (messages, image_blocks).
        """
        file_contents = await self._build_file_contents(task)
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
        """Delegate to shared extract_json utility."""
        try:
            return extract_json(response)
        except ValueError:
            logger.error("Failed to parse JSON response", response=response[:500])
            raise ValueError("Не удалось распознать ответ Claude как JSON")

    async def _interruptible_claude_json(
        self,
        messages: list[dict],
        system_prompt: str,
        use_web_search: bool = False,
        image_data: Optional[list] = None,
        processing_timeout: Optional[float] = None,
        cancel_check_interval: float = 30.0,
        max_tokens: int = 32000,
    ) -> dict:
        """Like _call_claude_json but checks for task cancellation every cancel_check_interval seconds.

        Wraps _call_claude_json in an asyncio Task and polls for cancellation while it runs.
        If the task is cancelled in the DB, the API call is cancelled and TaskCancelledError is raised.
        """
        api_task = asyncio.create_task(
            self._call_claude_json(
                messages,
                system_prompt=system_prompt,
                use_web_search=use_web_search,
                image_data=image_data,
                processing_timeout=processing_timeout,
                max_tokens=max_tokens,
            )
        )
        try:
            while True:
                done, _ = await asyncio.wait({api_task}, timeout=cancel_check_interval)
                if done:
                    # Completed (success or exception) — re-raise any exception
                    return api_task.result()
                # Still running — check if cancelled in DB
                await self._check_cancelled()
        except TaskCancelledError:
            api_task.cancel()
            try:
                await api_task
            except (asyncio.CancelledError, Exception):
                pass
            raise

    async def _call_claude_json(
        self,
        messages: list[dict],
        system_prompt: str,
        use_web_search: bool = False,
        image_data: Optional[list] = None,
        processing_timeout: Optional[float] = None,
        max_tokens: int = 32000,
    ) -> dict:
        """Call Claude and parse the JSON response, retrying once if parsing fails.

        processing_timeout — passed through to call_claude where it wraps only the
        actual _client.messages.create() call, NOT the rate-limit sleep.
        asyncio.TimeoutError propagates up if the API call itself is too slow.
        """
        response = await call_claude(
            messages,
            system_prompt=system_prompt,
            use_web_search=use_web_search,
            image_data=image_data,
            processing_timeout=processing_timeout,
            task_id=self.task_id,
            db=self.db,
            max_tokens=max_tokens,
        )
        try:
            return self._parse_json_response(response)
        except ValueError:
            logger.warning("JSON parse failed on first attempt, retrying with explicit instruction", task_id=self.task_id)
            retry_messages = list(messages) + [
                {"role": "assistant", "content": response},
                {
                    "role": "user",
                    "content": (
                        "Ответь ТОЛЬКО валидным JSON-объектом. "
                        "Никакого текста до или после. "
                        "Никаких markdown-блоков, никаких обратных кавычек, никаких символов ``` . "
                        "Первый символ ответа — {, последний символ — }."
                    ),
                },
            ]
            retry_response = await call_claude(
                retry_messages,
                system_prompt=system_prompt,
                use_web_search=False,
                processing_timeout=processing_timeout,
                task_id=self.task_id,
                db=self.db,
                max_tokens=max_tokens,
            )
            return self._parse_json_response(retry_response)

    async def _call_claude_json_with_retry(
        self,
        messages: list[dict],
        system_prompt: str,
        use_web_search: bool = False,
        image_data: Optional[list] = None,
        processing_timeout: Optional[float] = None,
        max_chunk_retries: int = 3,
        chunk_retry_delays: tuple = (5.0, 15.0, 30.0),
        max_tokens: int = 32000,
    ) -> dict:
        """_call_claude_json с retry для transient ошибок уровня чанка."""
        last_error: Optional[Exception] = None
        for attempt in range(max_chunk_retries):
            try:
                return await self._call_claude_json(
                    messages,
                    system_prompt=system_prompt,
                    use_web_search=use_web_search,
                    image_data=image_data,
                    processing_timeout=processing_timeout,
                    max_tokens=max_tokens,
                )
            except TaskCancelledError:
                raise
            except asyncio.TimeoutError:
                raise
            except Exception as e:
                last_error = e
                if attempt < max_chunk_retries - 1:
                    wait = chunk_retry_delays[attempt]
                    logger.warning(
                        "Chunk Claude call failed, retrying",
                        task_id=self.task_id,
                        attempt=attempt + 1,
                        max_retries=max_chunk_retries,
                        wait=wait,
                        error=str(e),
                    )
                    await asyncio.sleep(wait)
        raise last_error  # type: ignore[misc]

    async def _interruptible_claude_json_with_retry(
        self,
        messages: list[dict],
        system_prompt: str,
        use_web_search: bool = False,
        image_data: Optional[list] = None,
        processing_timeout: Optional[float] = None,
        max_chunk_retries: int = 3,
        chunk_retry_delays: tuple = (5.0, 15.0, 30.0),
        max_tokens: int = 32000,
    ) -> dict:
        """_interruptible_claude_json с retry для transient ошибок уровня чанка."""
        last_error: Optional[Exception] = None
        for attempt in range(max_chunk_retries):
            try:
                return await self._interruptible_claude_json(
                    messages,
                    system_prompt=system_prompt,
                    use_web_search=use_web_search,
                    image_data=image_data,
                    processing_timeout=processing_timeout,
                    max_tokens=max_tokens,
                )
            except TaskCancelledError:
                raise
            except asyncio.TimeoutError:
                raise
            except Exception as e:
                last_error = e
                if attempt < max_chunk_retries - 1:
                    wait = chunk_retry_delays[attempt]
                    logger.warning(
                        "Chunk interruptible Claude call failed, retrying",
                        task_id=self.task_id,
                        attempt=attempt + 1,
                        max_retries=max_chunk_retries,
                        wait=wait,
                        error=str(e),
                    )
                    await asyncio.sleep(wait)
        raise last_error  # type: ignore[misc]

    async def process(self) -> None:
        """Main processing method."""
        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat(stop_event)
        )
        try:
            await self.update_status("processing")
            await self.update_progress("Начало обработки задачи...")

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

            task_type = task.task_type.upper()

            if task_type == "LIST_FROM_GRAND":
                await self._handle_list_from_grand(task)
            elif task_type == "CHECK_LIST_COMPLETENESS":
                await self._handle_check_completeness(task)
            elif task_type == "LIST_FROM_PROJECT":
                await self._handle_list_from_project(task)
            elif task_type == "CHECK_PROJECT_COMPLETENESS":
                await self._handle_check_project_completeness(task)
            elif task_type == "ESTIMATE_FROM_LIST":
                await self._handle_estimate_from_list(task)
            elif task_type == "ESTIMATE_OPTIMIZATION":
                await self._handle_estimate_optimization(task)
            else:
                raise NotImplementedError(f"Тип задачи {task.task_type!r} ещё не настроен")

            await self._auto_fill_estimate_slot()
            await self.update_status("completed")

        except TaskCancelledError:
            logger.info("Task was cancelled by user", task_id=self.task_id)
        except Exception as e:
            logger.error("Task processing failed", task_id=self.task_id, error=str(e))
            await self.update_status("failed", error=str(e))
            await self.update_progress(f"Ошибка: {str(e)[:400]}")
        finally:
            stop_event.set()
            heartbeat_task.cancel()

    async def _save_partial(self, items: list, chunk_idx: int, total: int, prefix: str = "Частичная_проверка") -> None:
        """Save accumulated items as a partial Excel result."""
        excel_data = generate_list(items)
        await self.save_result(
            f"{prefix}_{chunk_idx}_из_{total}.xlsx",
            _XLSX_MIME,
            excel_data,
            slot=f"partial_{chunk_idx}",
        )

    async def _handle_list_from_grand(self, task: Task) -> None:
        await self.update_progress("Анализ файла гранд-сметы...")

        excel_bytes: Optional[bytes] = None
        pdf_bytes: Optional[bytes] = None

        for f in await self._load_input_files(task):
            mime = f.get("mime_type", "")
            if "spreadsheet" in mime or "excel" in mime or mime == _XLSX_MIME:
                excel_bytes = base64.b64decode(f["content_b64"])
            elif mime == "application/pdf":
                pdf_bytes = base64.b64decode(f["content_b64"])

        # E2: запретить оба одновременно
        if excel_bytes and pdf_bytes:
            raise ValueError("Загрузите один файл: либо .xlsx, либо .pdf, но не оба сразу")

        if excel_bytes:
            await self._handle_list_from_grand_xlsx(task, excel_bytes)
        elif pdf_bytes:
            await self._handle_list_from_grand_pdf(task, pdf_bytes)
        else:
            raise ValueError("Не найден файл (.xlsx или .pdf) во вложениях задачи")

    async def _handle_list_from_grand_xlsx(self, task: Task, excel_bytes: bytes) -> None:
        # --- Определяем, это resume или новый запуск ---
        progress_data = task.progress_data or {}
        start_chunk = progress_data.get("chunks_done", 0)
        accumulated_items: list = list(progress_data.get("items", []))
        partial_count: int = progress_data.get("partial_count", 0)

        # --- Парсим и разбиваем на чанки ---
        rows = parse_xlsx_grand(excel_bytes)
        if not rows:
            raise ValueError("Не удалось извлечь строки из Excel. Проверьте формат файла.")

        chunks = chunk_rows(rows)
        total_chunks = len(chunks)

        if start_chunk >= total_chunks:
            # Все чанки уже обработаны, просто генерируем финальный файл
            logger.info("All chunks already done, generating final Excel", task_id=self.task_id)
        else:
            if start_chunk > 0:
                await self.update_progress(
                    f"Возобновление с части {start_chunk + 1} из {total_chunks}..."
                )
            else:
                await self.update_progress(
                    f"Файл разбит на {total_chunks} частей. Начинаем обработку..."
                )

            for i in range(start_chunk, total_chunks):
                try:
                    await self._check_cancelled()
                except TaskCancelledError:
                    # Пользователь нажал «Стоп» — сохраняем накопленное если есть
                    if accumulated_items:
                        partial_count += 1
                        partial_excel = generate_list(accumulated_items)
                        await self.save_result(
                            f"Частичный_перечень_{i}_из_{total_chunks}.xlsx",
                            _XLSX_MIME,
                            partial_excel,
                            slot=f"partial_{partial_count}",
                        )
                        await self._save_progress_data({
                            "chunks_done": i,
                            "total_chunks": total_chunks,
                            "items": accumulated_items,
                            "partial_count": partial_count,
                        })
                        logger.info(
                            "Task cancelled by user, partial result saved",
                            task_id=self.task_id,
                            chunks_done=i,
                            total=total_chunks,
                        )
                    raise

                await self.update_progress(f"Обрабатывается часть {i + 1} из {total_chunks}...")

                chunk_text = rows_to_text(chunks[i])
                messages = [{"role": "user", "content": f"{chunk_text}\n\n{PROMPT_LIST_FROM_GRAND}"}]

                try:
                    data = await self._call_claude_json_with_retry(
                        messages,
                        system_prompt=SYSTEM_BASE,
                        use_web_search=False,
                    )
                    chunk_items = data.get("items", [])
                    accumulated_items.extend(chunk_items)

                    # Сохраняем прогресс после каждого успешного чанка
                    await self._save_progress_data({
                        "chunks_done": i + 1,
                        "total_chunks": total_chunks,
                        "items": accumulated_items,
                        "partial_count": partial_count,
                    })
                    logger.info("Chunk processed", task_id=self.task_id, chunk=i + 1, total=total_chunks, items=len(chunk_items))

                except TaskCancelledError:
                    raise

                except Exception as chunk_error:
                    # Ошибка Claude — сохраняем частичный Excel
                    if accumulated_items:
                        partial_count += 1
                        partial_excel = generate_list(accumulated_items)
                        await self.save_result(
                            f"Частичный_перечень_{i}_из_{total_chunks}.xlsx",
                            _XLSX_MIME,
                            partial_excel,
                            slot=f"partial_{partial_count}",
                        )
                        await self._save_progress_data({
                            "chunks_done": i,
                            "total_chunks": total_chunks,
                            "items": accumulated_items,
                            "partial_count": partial_count,
                        })
                        await self.update_progress(
                            f"Обработано {i} из {total_chunks} частей. Частичный результат сохранён."
                        )
                        logger.warning(
                            "Chunk failed, partial result saved",
                            task_id=self.task_id,
                            chunk=i + 1,
                            total=total_chunks,
                            error=str(chunk_error),
                        )
                    raise

        # --- Генерируем финальный Excel ---
        if not accumulated_items:
            raise ValueError("Claude не вернул ни одной позиции. Проверьте содержимое файла.")

        await self.update_progress(f"Найдено {len(accumulated_items)} позиций. Формирование Excel...")
        excel_data = generate_list(accumulated_items)
        await self.save_result(
            self._result_filename(task, "Перечень_из_Гранд-сметы.xlsx"),
            _XLSX_MIME,
            excel_data,
        )
        await self._create_initial_generic_version(excel_data, task.task_type)
        logger.info("List from Grand task completed", task_id=self.task_id, items=len(accumulated_items), chunks=total_chunks)

    async def _handle_list_from_grand_pdf(self, task: Task, pdf_bytes: bytes) -> None:
        progress_data = task.progress_data or {}
        start_chunk = progress_data.get("chunks_done", 0)
        accumulated_items: list = list(progress_data.get("items", []))
        partial_count: int = progress_data.get("partial_count", 0)

        # Если OCR уже выполнялся до рестарта — берём сохранённые страницы
        if "ocr_pages" in progress_data:
            pages = progress_data["ocr_pages"]
            await self.update_progress(
                f"OCR уже выполнен ({len(pages)} стр.), продолжаем обработку..."
            )
        else:
            await self.update_progress("Извлечение текста из PDF гранд-сметы...")
            # run_in_executor чтобы не блокировать event loop во время длительного OCR
            pages = await asyncio.to_thread(extract_pdf_with_ocr, pdf_bytes)
            # Сохраняем результат OCR в progress_data — при рестарте не придётся повторять
            await self._save_progress_data({**progress_data, "ocr_pages": pages})

        # A5: предупреждение о большом файле
        if len(pages) > 50:
            await self.update_progress(
                f"Большой файл: {len(pages)} страниц, обработка займёт несколько минут..."
            )

        chunks = chunk_pdf_pages(pages)
        total_chunks = len(chunks)

        if not chunks:
            raise ValueError("Не удалось извлечь текст из PDF. Проверьте качество скана или формат файла.")

        if start_chunk >= total_chunks:
            logger.info("All PDF chunks already done, generating final Excel", task_id=self.task_id)
        else:
            if start_chunk > 0:
                await self.update_progress(
                    f"Возобновление с части {start_chunk + 1} из {total_chunks}..."
                )
            else:
                await self.update_progress(
                    f"PDF разбит на {total_chunks} частей. Начинаем обработку..."
                )

            for i in range(start_chunk, total_chunks):
                try:
                    await self._check_cancelled()
                except TaskCancelledError:
                    if accumulated_items:
                        partial_count += 1
                        partial_excel = generate_list(accumulated_items)
                        await self.save_result(
                            f"Частичный_перечень_{i}_из_{total_chunks}.xlsx",
                            _XLSX_MIME,
                            partial_excel,
                            slot=f"partial_{partial_count}",
                        )
                        await self._save_progress_data({
                            "chunks_done": i,
                            "total_chunks": total_chunks,
                            "items": accumulated_items,
                            "partial_count": partial_count,
                        })
                        logger.info(
                            "PDF task cancelled by user, partial result saved",
                            task_id=self.task_id,
                            chunks_done=i,
                            total=total_chunks,
                        )
                    raise

                await self.update_progress(f"Обрабатывается часть {i + 1} из {total_chunks}...")

                chunk_text = chunks[i]
                messages = [{"role": "user", "content": f"{chunk_text}\n\n{PROMPT_LIST_FROM_GRAND_PDF}"}]

                try:
                    data = await self._call_claude_json_with_retry(
                        messages,
                        system_prompt=SYSTEM_BASE,
                        use_web_search=False,
                    )
                    chunk_items = data.get("items", [])
                    accumulated_items.extend(chunk_items)

                    await self._save_progress_data({
                        "chunks_done": i + 1,
                        "total_chunks": total_chunks,
                        "items": accumulated_items,
                        "partial_count": partial_count,
                    })
                    logger.info("PDF chunk processed", task_id=self.task_id, chunk=i + 1, total=total_chunks, items=len(chunk_items))

                except TaskCancelledError:
                    raise

                except Exception as chunk_error:
                    if accumulated_items:
                        partial_count += 1
                        partial_excel = generate_list(accumulated_items)
                        await self.save_result(
                            f"Частичный_перечень_{i}_из_{total_chunks}.xlsx",
                            _XLSX_MIME,
                            partial_excel,
                            slot=f"partial_{partial_count}",
                        )
                        await self._save_progress_data({
                            "chunks_done": i,
                            "total_chunks": total_chunks,
                            "items": accumulated_items,
                            "partial_count": partial_count,
                        })
                        await self.update_progress(
                            f"Обработано {i} из {total_chunks} частей. Частичный результат сохранён."
                        )
                        logger.warning(
                            "PDF chunk failed, partial result saved",
                            task_id=self.task_id,
                            chunk=i + 1,
                            total=total_chunks,
                            error=str(chunk_error),
                        )
                    raise

        # E1: если ни одной позиции не извлечено
        if not accumulated_items:
            raise ValueError("Не удалось извлечь позиции из PDF. Проверьте качество скана.")

        await self.update_progress(f"Найдено {len(accumulated_items)} позиций. Формирование Excel...")
        excel_data = generate_list(accumulated_items)
        await self.save_result(
            self._result_filename(task, "Перечень_из_Гранд-сметы.xlsx"),
            _XLSX_MIME,
            excel_data,
        )
        await self._create_initial_generic_version(excel_data, task.task_type)
        logger.info("List from Grand PDF task completed", task_id=self.task_id, items=len(accumulated_items), chunks=total_chunks)

    async def _handle_check_completeness(self, task: Task) -> None:
        source_task_id = (task.user_prompt or "").strip()
        if not source_task_id:
            raise ValueError("ID исходной задачи не указан")

        res = await self.db.execute(select(Task).where(Task.id == source_task_id))
        source_task = res.scalar_one_or_none()
        if not source_task:
            raise ValueError(f"Исходная задача {source_task_id!r} не найдена")
        if source_task.task_type.upper() != "LIST_FROM_GRAND":
            raise ValueError("Исходная задача должна быть типа LIST_FROM_GRAND")

        items = (source_task.progress_data or {}).get("items", [])
        if not items:
            raise ValueError("В исходной задаче нет перечня позиций")

        await self.update_progress(f"Загружено {len(items)} позиций. Начинаем проверку по ГЭСН...")

        progress_data = task.progress_data or {}
        start_chunk = progress_data.get("chunks_done", 0)
        all_items: list = list(progress_data.get("items", []))
        changes_summary_parts: list = list(progress_data.get("summaries", []))

        chunks = _chunk_by_work_boundaries(items, max_chunk_size=25)
        total_chunks = len(chunks)

        for i in range(start_chunk, total_chunks):
            try:
                await self._check_cancelled()
            except TaskCancelledError:
                if all_items:
                    await self._save_partial(all_items, i, total_chunks)
                    await self.update_progress(f"Остановлено на части {i} из {total_chunks}. Частичный результат сохранён.")
                raise

            if total_chunks > 1:
                await self.update_progress(f"Проверка части {i + 1} из {total_chunks}...")
            else:
                await self.update_progress("Проверяем полноту материалов по ГЭСН...")

            chunk_json = json.dumps({"items": chunks[i]}, ensure_ascii=False, indent=2)
            messages = [{"role": "user", "content": f"{chunk_json}\n\n{PROMPT_CHECK_COMPLETENESS}"}]

            try:
                data = await self._interruptible_claude_json_with_retry(messages, system_prompt=SYSTEM_BASE, processing_timeout=1200.0)
            except TaskCancelledError:
                if all_items:
                    await self._save_partial(all_items, i, total_chunks)
                    await self.update_progress(f"Остановлено на части {i + 1} из {total_chunks}. Частичный результат сохранён.")
                raise
            except Exception:
                if all_items:
                    await self._save_partial(all_items, i, total_chunks)
                    await self.update_progress(f"Ошибка на части {i + 1}. Обработано {i} из {total_chunks}. Частичный результат сохранён.")
                raise

            all_items.extend(data.get("items", []))
            summary = data.get("changes_summary", "")
            if summary:
                changes_summary_parts.append(summary)

            await self._save_progress_data({
                "chunks_done": i + 1,
                "total_chunks": total_chunks,
                "items": all_items,
                "summaries": changes_summary_parts,
            })

        changes_summary = "\n\n".join(changes_summary_parts) if changes_summary_parts else None

        await self.update_progress(f"Проверено {len(all_items)} позиций. Формирование Excel...")
        excel_data = generate_list(all_items, changes_summary=changes_summary)
        await self.save_result(self._result_filename(task, "Проверка_полноты_ГЭСН.xlsx"), _XLSX_MIME, excel_data)
        await self._create_initial_generic_version(excel_data, task.task_type)
        logger.info(
            "Check completeness task completed",
            task_id=self.task_id,
            source_task_id=source_task_id,
            items=len(all_items),
            chunks=total_chunks,
        )

    async def _handle_list_from_project(self, task: Task) -> None:
        await self.update_progress("Поиск PDF проектной документации...")

        pdf_bytes: Optional[bytes] = None
        for f in await self._load_input_files(task):
            if f.get("mime_type", "") == "application/pdf":
                pdf_bytes = base64.b64decode(f["content_b64"])
                break

        if not pdf_bytes:
            raise ValueError("PDF-файл не найден во вложениях задачи")

        await self.update_progress("Анализ проектной документации...")

        try:
            chunks = chunk_project_pdf(pdf_bytes)
        except Exception as e:
            logger.error("PDF chunk extract failed", task_id=self.task_id, error=str(e))
            raise ValueError(f"Не удалось обработать PDF: {e}")

        total_chunks = len(chunks)
        logger.info(
            "PDF chunked for project list",
            task_id=self.task_id,
            total_chunks=total_chunks,
            drawing_pages=len(chunks[0]["image_pages"]) if chunks else 0,
        )

        if total_chunks > 1:
            await self.update_progress(
                f"PDF разбит на {total_chunks} части для обработки..."
            )

        accumulated_items: list[dict] = []
        seen_names: set[str] = set()

        for chunk_idx, chunk in enumerate(chunks, 1):
            if total_chunks > 1:
                await self.update_progress(
                    f"Обработка части {chunk_idx} из {total_chunks}..."
                )

            prompt_pass1 = (
                chunk["text"] + "\n\n" + PROMPT_LIST_FROM_PROJECT
                if chunk["text"]
                else PROMPT_LIST_FROM_PROJECT
            )

            if total_chunks > 1:
                prompt_pass1 = (
                    f"ЧАСТЬ {chunk_idx} ИЗ {total_chunks} ДОКУМЕНТА.\n\n"
                    + prompt_pass1
                )

            messages = [{"role": "user", "content": prompt_pass1}]
            try:
                data = await self._interruptible_claude_json_with_retry(
                    messages,
                    system_prompt=SYSTEM_BASE,
                    image_data=chunk["image_pages"] or None,
                    processing_timeout=1200.0,
                    max_tokens=64000,
                )
            except Exception as chunk_err:
                logger.warning(
                    "Project PDF chunk failed",
                    task_id=self.task_id,
                    chunk=chunk_idx,
                    error=str(chunk_err),
                )
                if chunk_idx == 1:
                    raise
                continue

            chunk_items = data.get("items", [])
            for item in chunk_items:
                name_key = (item.get("name", "").strip().lower(), item.get("type", "").strip())
                if name_key not in seen_names:
                    seen_names.add(name_key)
                    accumulated_items.append(item)

            logger.info(
                "Project PDF chunk processed",
                task_id=self.task_id,
                chunk=chunk_idx,
                total=total_chunks,
                new_items=len(chunk_items),
                total_items=len(accumulated_items),
            )

        items = accumulated_items
        if not items:
            raise ValueError("Claude не вернул ни одной позиции. Проверьте содержимое PDF.")

        await self.update_progress(f"Найдено {len(items)} позиций. Проверяю незаполненные объёмы...")

        # --- Проход 2: уточнение объёмов для позиций с quantity=null ---
        null_indices = [i for i, item in enumerate(items) if item.get("quantity") is None]

        if null_indices:
            await self.update_progress(
                f"Уточняю объёмы для {len(null_indices)} позиций..."
            )
            _PASS2_CHUNK = 15
            chunks_null = [null_indices[i:i + _PASS2_CHUNK] for i in range(0, len(null_indices), _PASS2_CHUNK)]

            for chunk_num, chunk_idx in enumerate(chunks_null, 1):
                if len(chunks_null) > 1:
                    await self.update_progress(
                        f"Уточняю объёмы: часть {chunk_num} из {len(chunks_null)}..."
                    )

                null_items_payload = [items[i] for i in chunk_idx]
                null_json = json.dumps({"items": null_items_payload}, ensure_ascii=False, indent=2)
                messages2 = [{"role": "user", "content": f"{null_json}\n\n{PROMPT_LIST_FROM_PROJECT_PASS2}"}]

                try:
                    all_images = chunks[0]["image_pages"] if chunks else []
                    data2 = await self._interruptible_claude_json_with_retry(
                        messages2,
                        system_prompt=SYSTEM_BASE,
                        image_data=all_images or None,
                        processing_timeout=900.0,
                        max_tokens=64000,
                    )
                    resolved = data2.get("items", [])

                    if len(resolved) == len(chunk_idx):
                        for orig_idx, resolved_item in zip(chunk_idx, resolved):
                            if resolved_item.get("quantity") is not None:
                                resolved_item["_calculated"] = True
                                items[orig_idx] = resolved_item
                    else:
                        logger.warning(
                            "Pass2 returned unexpected item count",
                            task_id=self.task_id,
                            expected=len(chunk_idx),
                            got=len(resolved),
                        )
                except Exception as pass2_err:
                    logger.warning(
                        "Pass2 failed, keeping original null items",
                        task_id=self.task_id,
                        error=str(pass2_err),
                    )

        resolved_count = sum(1 for i in null_indices if items[i].get("quantity") is not None)
        if null_indices:
            await self.update_progress(
                f"Объёмы уточнены: {resolved_count} из {len(null_indices)} заполнено. Формирование Excel..."
            )
        else:
            await self.update_progress(f"Найдено {len(items)} позиций. Формирование Excel...")

        await self._save_progress_data({"items": items})

        excel_data = generate_list(items)
        await self.save_result(self._result_filename(task, "Перечень_из_проекта.xlsx"), _XLSX_MIME, excel_data)
        await self._create_initial_generic_version(excel_data, task.task_type)
        logger.info(
            "List from project task completed",
            task_id=self.task_id,
            items=len(items),
            null_resolved=resolved_count if null_indices else 0,
        )

    async def _handle_check_project_completeness(self, task: Task) -> None:
        source_task_id = (task.user_prompt or "").strip()
        if not source_task_id:
            raise ValueError("ID исходной задачи не указан")

        res = await self.db.execute(select(Task).where(Task.id == source_task_id))
        source_task = res.scalar_one_or_none()
        if not source_task:
            raise ValueError(f"Исходная задача {source_task_id!r} не найдена")
        if source_task.task_type.upper() != "LIST_FROM_PROJECT":
            raise ValueError("Исходная задача должна быть типа LIST_FROM_PROJECT")

        items = (source_task.progress_data or {}).get("items", [])
        if not items:
            raise ValueError("В исходной задаче нет перечня позиций")

        await self.update_progress(f"Загружено {len(items)} позиций. Начинаем проверку по ГЭСН...")

        progress_data = task.progress_data or {}
        start_chunk = progress_data.get("chunks_done", 0)
        all_items: list = list(progress_data.get("items", []))
        changes_summary_parts: list = list(progress_data.get("summaries", []))

        chunks = _chunk_by_work_boundaries(items, max_chunk_size=25)
        total_chunks = len(chunks)

        for i in range(start_chunk, total_chunks):
            try:
                await self._check_cancelled()
            except TaskCancelledError:
                if all_items:
                    await self._save_partial(all_items, i, total_chunks)
                    await self.update_progress(f"Остановлено на части {i} из {total_chunks}. Частичный результат сохранён.")
                raise

            if total_chunks > 1:
                await self.update_progress(f"Проверка части {i + 1} из {total_chunks}...")
            else:
                await self.update_progress("Проверяем полноту материалов по ГЭСН...")

            chunk_json = json.dumps({"items": chunks[i]}, ensure_ascii=False, indent=2)
            messages = [{"role": "user", "content": f"{chunk_json}\n\n{PROMPT_CHECK_PROJECT_COMPLETENESS}"}]

            try:
                data = await self._interruptible_claude_json_with_retry(messages, system_prompt=SYSTEM_BASE, processing_timeout=1200.0)
            except TaskCancelledError:
                if all_items:
                    await self._save_partial(all_items, i, total_chunks)
                    await self.update_progress(f"Остановлено на части {i + 1} из {total_chunks}. Частичный результат сохранён.")
                raise
            except Exception:
                if all_items:
                    await self._save_partial(all_items, i, total_chunks)
                    await self.update_progress(f"Ошибка на части {i + 1}. Обработано {i} из {total_chunks}. Частичный результат сохранён.")
                raise

            all_items.extend(data.get("items", []))
            summary = data.get("changes_summary", "")
            if summary:
                changes_summary_parts.append(summary)

            await self._save_progress_data({
                "chunks_done": i + 1,
                "total_chunks": total_chunks,
                "items": all_items,
                "summaries": changes_summary_parts,
            })

        changes_summary = "\n\n".join(changes_summary_parts) if changes_summary_parts else None

        await self.update_progress(f"Проверено {len(all_items)} позиций. Формирование Excel...")
        excel_data = generate_list(all_items, changes_summary=changes_summary)
        await self.save_result(self._result_filename(task, "Проверка_полноты_по_проекту.xlsx"), _XLSX_MIME, excel_data)
        await self._create_initial_generic_version(excel_data, task.task_type)
        logger.info(
            "Check project completeness task completed",
            task_id=self.task_id,
            source_task_id=source_task_id,
            items=len(all_items),
            chunks=total_chunks,
        )

    async def _handle_estimate_from_list(self, task: Task) -> None:
        """
        Шаг 0: Получаем items — либо из файла (Path A), либо из существующей задачи (Path B).
        Шаг 1: Поиск цен по прайсу (exact + embedding, без web search).
        Шаг 2: Claude для ненайденных позиций (чанки по границам «Работа»).
        Шаг 3: Сборка Excel сметы, расчёт итогов, сохранение task.cost.
        """
        from datetime import date as _date

        # ── Шаг 0: Получаем items ───────────────────────────────────────────
        items: list[dict] = []
        user_prompt = task.user_prompt or ""

        if user_prompt.startswith("{"):
            # Path B: items из существующей задачи
            try:
                prompt_data = json.loads(user_prompt)
            except Exception:
                prompt_data = {}

            if prompt_data.get("path") == "B":
                source_task_id = prompt_data.get("source_task_id")
                source_stage = prompt_data.get("source_stage", 1)

                await self.update_progress("Загрузка позиций из существующей задачи...")
                source_task_res = await self.db.execute(
                    select(Task).where(Task.id == source_task_id)
                )
                source_task = source_task_res.scalar_one_or_none()
                if not source_task:
                    raise ValueError(f"Исходная задача {source_task_id} не найдена")

                if source_stage == 2:
                    # Find related check task
                    check_type = (
                        "CHECK_LIST_COMPLETENESS"
                        if source_task.task_type == "LIST_FROM_GRAND"
                        else "CHECK_PROJECT_COMPLETENESS"
                    )
                    from sqlalchemy import desc as _desc
                    check_res = await self.db.execute(
                        select(Task)
                        .where(Task.user_prompt == str(source_task.id))
                        .where(Task.task_type == check_type)
                        .where(Task.status == "completed")
                        .order_by(_desc(Task.created_at))
                        .limit(1)
                    )
                    check_task_obj = check_res.scalar_one_or_none()
                    if not check_task_obj:
                        raise ValueError("Задача проверки полноты не найдена или не завершена")
                    items = (check_task_obj.progress_data or {}).get("items", [])
                    if not items:
                        raise ValueError("В задаче проверки полноты нет позиций")
                else:
                    # Stage 1: items from source task
                    items = (source_task.progress_data or {}).get("items", [])
                    if not items:
                        raise ValueError("В исходной задаче нет сохранённых позиций")

                logger.info("Loaded items from source task (Path B)", task_id=self.task_id, items=len(items))
            else:
                # Fallback: treat as Path A
                user_prompt = ""

        if not items:
            # Path A: парсим лист «Перечень» из загруженного Excel
            await self.update_progress("Поиск Excel-файла перечня...")
            excel_bytes: Optional[bytes] = None
            for f in await self._load_input_files(task):
                mime = f.get("mime_type", "")
                if "spreadsheet" in mime or "excel" in mime or mime == _XLSX_MIME:
                    excel_bytes = base64.b64decode(f["content_b64"])
                    break

            if not excel_bytes:
                raise ValueError("Excel-файл (.xlsx) с перечнем не найден во вложениях задачи")

            await self.update_progress("Парсинг листа «Перечень»...")
            items = parse_list_sheet(excel_bytes)
            logger.info("Parsed list sheet", task_id=self.task_id, items=len(items))

        # ── Шаг 1: Поиск цен по прайсу ─────────────────────────────────────
        await self.update_progress(f"Поиск цен для {len(items)} позиций по корпоративному прайсу...")

        # Keyed by global index in `items` — eliminates all name-based lookups later.
        matched_by_gidx: dict[int, dict] = {}
        unmatched_by_gidx: dict[int, dict] = {}  # gidx -> enriched item with "_id" = gidx

        for gidx, item in enumerate(items):
            item_type = str(item.get("type", "")).strip()
            name = str(item.get("name", "")).strip()
            enriched = dict(item)
            enriched["_id"] = gidx
            enriched.setdefault("work_price", None)
            enriched.setdefault("material_price", None)
            enriched.setdefault("price_list_name", None)
            enriched.setdefault("sources", None)

            found = False
            if item_type == "Работа":
                work_info = _price_svc._exact_match_work(name)
                match_method = "exact" if work_info is not None else None
                if work_info is None:
                    work_info = await _price_svc._embedding_match_work(name)
                    if work_info is not None:
                        match_method = "embedding"
                if work_info is not None and work_info.get("min_price") is not None:
                    enriched["work_price"] = work_info.get("min_price")
                    enriched["price_list_name"] = work_info.get("name")
                    found = True
                    logger.info("Item MATCHED in price list", task_id=self.task_id, name=name, method=match_method, price_entry=work_info.get("name"))
                else:
                    logger.info("Item NOT matched in price list", task_id=self.task_id, name=name, work_info_found=(work_info is not None))

            elif item_type == "Материал":
                mat_price = _price_svc._exact_match_material(name)
                match_method = "exact" if mat_price is not None else None
                if mat_price is None:
                    mat_price = await _price_svc._embedding_match_material(name)
                    if mat_price is not None:
                        match_method = "embedding"
                if mat_price is not None:
                    enriched["material_price"] = mat_price
                    enriched["price_list_name"] = name
                    found = True
                    logger.info("Material MATCHED in price list", task_id=self.task_id, name=name, method=match_method)
                else:
                    logger.info("Material NOT matched in price list", task_id=self.task_id, name=name)

            if found:
                matched_by_gidx[gidx] = enriched
            else:
                unmatched_by_gidx[gidx] = enriched

        n_matched = len(matched_by_gidx)
        n_unmatched = len(unmatched_by_gidx)
        logger.info(
            "Price lookup done",
            task_id=self.task_id,
            matched=n_matched,
            unmatched=n_unmatched,
        )
        await self.update_progress(
            f"Прайс: найдено {n_matched}, не найдено {n_unmatched} из {len(items)} позиций."
        )

        # ── Шаг 2: Claude для ненайденных позиций ───────────────────────────
        # Results keyed by int _id (= global index), not by name string.
        claude_results: dict[int, dict] = {}

        async def _call_claude_chunk(chunk: list[dict], chunk_label: str) -> None:
            """Send one chunk to Claude and populate claude_results by _id."""
            unmatched_json = json.dumps(
                [{"id": it["_id"], "type": it["type"], "name": it["name"],
                  "unit": it["unit"], "quantity": it.get("quantity")}
                 for it in chunk],
                ensure_ascii=False, indent=2,
            )
            prompt_text = PROMPT_ESTIMATE_FROM_LIST.format(
                current_date=current_date,
                unmatched_items_json=unmatched_json,
            )
            messages = [{"role": "user", "content": prompt_text}]
            try:
                data = await self._interruptible_claude_json_with_retry(
                    messages,
                    system_prompt=SYSTEM_BASE,
                    use_web_search=True,
                    processing_timeout=1200.0,
                )
            except TaskCancelledError:
                raise
            except Exception as chunk_error:
                logger.warning(
                    "Claude chunk failed for ESTIMATE_FROM_LIST, skipping",
                    task_id=self.task_id,
                    chunk_label=chunk_label,
                    error=str(chunk_error),
                )
                return
            for result_item in data.get("items", []):
                item_id = result_item.get("id")
                if item_id is not None:
                    claude_results[int(item_id)] = result_item

        if unmatched_by_gidx:
            unmatched_list = list(unmatched_by_gidx.values())
            current_date = _date.today().strftime("%d.%m.%Y")
            chunks = _chunk_by_work_boundaries(unmatched_list, max_chunk_size=25)
            total_chunks = len(chunks)

            await self.update_progress(
                f"Прайс: {n_matched} позиций найдено, {n_unmatched} — нет. "
                f"Отправляем {total_chunks} чанк(а) в Claude..."
            )

            for i, chunk in enumerate(chunks):
                try:
                    await self._check_cancelled()
                except TaskCancelledError:
                    raise
                if total_chunks > 1:
                    await self.update_progress(f"Claude: обработка части {i + 1} из {total_chunks}...")
                await _call_claude_chunk(chunk, chunk_label=f"{i + 1}/{total_chunks}")

            # Retry any ids Claude skipped — in smaller batches of 5.
            missing_ids = set(unmatched_by_gidx.keys()) - set(claude_results.keys())
            if missing_ids:
                await self.update_progress(
                    f"Повторная обработка {len(missing_ids)} пропущенных позиций (батчи по 5)..."
                )
                missing_items = [unmatched_by_gidx[gidx] for gidx in sorted(missing_ids)]
                retry_chunks = [missing_items[i:i + 5] for i in range(0, len(missing_items), 5)]
                for j, retry_chunk in enumerate(retry_chunks):
                    try:
                        await self._check_cancelled()
                    except TaskCancelledError:
                        raise
                    await _call_claude_chunk(retry_chunk, chunk_label=f"retry-{j + 1}/{len(retry_chunks)}")

            still_missing = set(unmatched_by_gidx.keys()) - set(claude_results.keys())
            if still_missing:
                logger.warning(
                    "Some items remain unpriced after retry",
                    task_id=self.task_id,
                    count=len(still_missing),
                    names=[unmatched_by_gidx[gidx].get("name") for gidx in sorted(still_missing)],
                )

        # ── Шаг 3: Сборка итогового результата в исходном порядке ───────────
        final_items: list[dict] = []
        for gidx, item in enumerate(items):
            if gidx in matched_by_gidx:
                final_items.append(matched_by_gidx[gidx])
                continue
            cr = claude_results.get(gidx)
            if cr:
                enriched = {
                    "type": item.get("type", ""),
                    "name": str(item.get("name", "")).strip(),
                    "unit": cr.get("unit") or item.get("unit", ""),
                    "quantity": item.get("quantity"),
                    "work_price": cr.get("work_price"),
                    "material_price": cr.get("material_price"),
                    "price_list_name": None,
                    "sources": cr.get("sources", ""),
                    "notes": cr.get("notes", ""),
                }
            else:
                enriched = {
                    "type": item.get("type", ""),
                    "name": str(item.get("name", "")).strip(),
                    "unit": item.get("unit", ""),
                    "quantity": item.get("quantity"),
                    "work_price": None,
                    "material_price": None,
                    "price_list_name": None,
                    "sources": "",
                    "notes": "Цена не определена",
                }
            final_items.append(enriched)

        await self.update_progress(f"Собрано {len(final_items)} позиций. Формирование Excel сметы...")

        excel_data, grand_total = generate_estimate_xlsx(final_items)

        # Save result file
        await self.save_result(self._result_filename(task, "Смета_из_перечня.xlsx"), _XLSX_MIME, excel_data)

        # Save cost and estimation_status
        task_res = await self.db.execute(select(Task).where(Task.id == self.task_id))
        upd_task = task_res.scalar_one_or_none()
        if upd_task:
            from decimal import Decimal as _Decimal
            upd_task.cost = _Decimal(str(round(grand_total, 2)))
            upd_task.estimation_status = "estimated"
            upd_task.updated_at = datetime.now(timezone.utc)
            await self.db.commit()

        # Save items to progress_data for future use (Path B)
        await self._save_progress_data({"items": final_items})

        logger.info(
            "Estimate from list completed",
            task_id=self.task_id,
            items=len(final_items),
            matched=len(matched_by_gidx),
            unmatched=len(unmatched_by_gidx),
            grand_total=grand_total,
        )

    async def _heartbeat(self, stop_event: asyncio.Event) -> None:
        """Log a heartbeat every 30 s so it's clear the task is alive, not hung."""
        elapsed = 0
        while not stop_event.is_set():
            await asyncio.sleep(30)
            if stop_event.is_set():
                break
            elapsed += 30
            logger.info("Task still running", task_id=self.task_id, elapsed_seconds=elapsed)

    async def _handle_estimate_optimization(self, task: Task) -> None:
        """Parse uploaded Excel files and create initial EstimateVersion records."""
        import uuid as _uuid

        await self.update_progress("Парсинг файлов сметы...")

        files = await self._load_input_files(task)
        if not files:
            raise ValueError("Файл сметы не найден во вложениях задачи")

        # Determine which files are estimate vs client from user_prompt JSON
        client_file_indices: set[int] = set()
        user_prompt_meta: dict = {}
        if task.user_prompt:
            try:
                user_prompt_meta = json.loads(task.user_prompt)
            except (ValueError, TypeError):
                pass

        for cf in user_prompt_meta.get("client_files", []):
            idx = cf.get("index")
            if isinstance(idx, int):
                client_file_indices.add(idx)

        # Find the first non-client xlsx as the main estimate
        main_xlsx_bytes: Optional[bytes] = None
        main_idx: int = -1
        for i, f in enumerate(files):
            if i in client_file_indices:
                continue
            mime = f.get("mime_type", "")
            if "spreadsheet" in mime or "excel" in mime or mime == _XLSX_MIME:
                main_xlsx_bytes = base64.b64decode(f["content_b64"])
                main_idx = i
                break

        if main_xlsx_bytes is None:
            raise ValueError("Excel-файл (.xlsx) сметы не найден во вложениях задачи")

        rows = parse_estimate_excel(main_xlsx_bytes)
        if not rows:
            raise ValueError(
                "Не удалось извлечь строки из Excel-сметы. "
                "Проверьте формат файла (должен быть .xlsx с заголовком Наименование)."
            )

        # Create "original" version
        original = EstimateVersion(
            id=str(_uuid.uuid4()),
            task_id=str(task.id),
            version_number=0,
            version_label="original",
            version_display_name="Исходная смета",
            rows=rows,
        )
        self.db.add(original)
        await self.db.flush()
        logger.info("EstimateVersion original created", task_id=str(task.id), rows=len(rows))

        # Process client files if any
        version_number = 1
        for i, f in enumerate(files):
            if i == main_idx:
                continue
            cf_meta = next(
                (c for c in user_prompt_meta.get("client_files", []) if c.get("index") == i),
                None,
            )
            file_type = (cf_meta or {}).get("type", "")
            mime = f.get("mime_type", "")
            is_xlsx = "spreadsheet" in mime or "excel" in mime or mime == _XLSX_MIME

            if file_type == "Смета" and is_xlsx:
                await self.update_progress("Парсинг сметы заказчика...")
                client_bytes = base64.b64decode(f["content_b64"])
                client_rows = parse_estimate_excel(client_bytes)
                if client_rows:
                    client_version = EstimateVersion(
                        id=str(_uuid.uuid4()),
                        task_id=str(task.id),
                        version_number=version_number,
                        version_label="client",
                        version_display_name="Смета заказчика",
                        rows=client_rows,
                    )
                    self.db.add(client_version)
                    await self.db.flush()
                    version_number += 1
                    logger.info(
                        "EstimateVersion client created",
                        task_id=str(task.id),
                        rows=len(client_rows),
                    )

        await self.db.commit()
        await self.update_progress("Смета загружена. Редактор готов к работе.")


async def process_task(task_id: str, db: AsyncSession) -> None:
    """Wrapper function for backward compatibility with routers."""
    processor = TaskProcessor(task_id, db)
    await processor.process()
