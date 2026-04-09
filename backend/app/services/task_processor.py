import asyncio
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.models.task import Task
from app.models.result import TaskResult
from app.services.claude_service import call_claude
from app.services.excel_service import generate_list
from app.constants import ESTIMATE_TASK_TYPES
from app.utils.xlsx_cost_parser import extract_total_cost
from app.utils.file_parser import parse_file
from app.utils.json_utils import extract_json

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

PROMPT_LIST_FROM_GRAND = """Ты — опытный инженер-сметчик со знанием нормативной базы РФ (ГЭСН-2017/ФСНБ-2022, ФЕР/ТЕР по Свердловской области, СП, ГОСТ).

Задача: проанализировать техническое задание и составить полный нормативный перечень работ и материалов.

ПОРЯДОК СТРОК В ПЕРЕЧНЕ — строго соблюдать:
Работа 1
  Материал 1 к Работе 1
  Материал 2 к Работе 1
  ...
Работа 2
  Материал 1 к Работе 2
  ...

Каждый вид работы должен идти ПЕРВОЙ строкой, затем сразу все материалы к этой работе.

ТРЕБОВАНИЯ К МАТЕРИАЛАМ:
1. Для каждого вида работы определи полный перечень материалов по нормативной базе:
   - ГЭСН / ФСНБ-2022 — основной источник норм расхода материалов
   - ФЕР/ТЕР Свердловской области — для региональной специфики
   - Технические части сборников ГЭСН — что включено в норму, что учитывается отдельно
   - СП и ГОСТ — для нестандартных решений

2. Если в гранд-смете указан материал, но не указан объём — рассчитай объём по нормам ГЭСН исходя из объёма работ.

3. Если в гранд-смете отсутствует материал, который нормативно необходим — добавь его с пометкой в примечании.

ФИКСАЦИЯ ИЗМЕНЕНИЙ:
- В поле notes для каждой изменённой позиции указывай:
  * "Добавлено по ГЭСН XX-XX-XXX: [обоснование]"
  * "Объём скорректирован: в ТЗ [X] [ед], распределено между работами по норме ГЭСН [норма]"
  * "Наименование уточнено: в гранд-смете '[исходное]', скорректировано на '[новое]' согласно [норматив]"

ПОЯСНИТЕЛЬНЫЙ ТЕКСТ:
После формирования перечня добавь поле "changes_summary" — текст с обоснованием всех изменений по сравнению с гранд-сметой.

Верни результат СТРОГО в формате JSON, без markdown блоков, без preamble текста, первый символ {, последний }:
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "notes": "Примечание / обоснование изменения"
    }
  ],
  "changes_summary": "Пояснительный текст обо всех изменениях по сравнению с гранд-сметой"
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }."""


class TaskCancelledError(Exception):
    """Raised when a task has been cancelled by the user."""


class TaskProcessor:
    def __init__(self, task_id: str, db: AsyncSession):
        self.task_id = task_id
        self.db = db

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
        """Delegate to shared extract_json utility."""
        try:
            return extract_json(response)
        except ValueError:
            logger.error("Failed to parse JSON response", response=response[:500])
            raise ValueError("Не удалось распознать ответ Claude как JSON")

    async def _call_claude_json(
        self,
        messages: list[dict],
        system_prompt: str,
        use_web_search: bool = False,
        image_data: Optional[list] = None,
        processing_timeout: Optional[float] = None,
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
            )
            return self._parse_json_response(retry_response)

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
            else:
                raise NotImplementedError(f"Тип задачи {task.task_type!r} ещё не настроен")

        except TaskCancelledError:
            logger.info("Task was cancelled by user", task_id=self.task_id)
        except Exception as e:
            logger.error("Task processing failed", task_id=self.task_id, error=str(e))
            await self.update_status("failed", error=str(e))
            await self.update_progress(f"Ошибка: {str(e)[:400]}")
        finally:
            stop_event.set()
            heartbeat_task.cancel()

    async def _handle_list_from_grand(self, task: Task) -> None:
        await self.update_progress("Анализ гранд-сметы...")
        messages, image_blocks = self._build_messages_with_files(task, PROMPT_LIST_FROM_GRAND)

        await self.update_progress("Формирование перечня с помощью ИИ...")
        data = await self._call_claude_json(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )

        await self.update_progress("Обработка результатов...")
        items = data.get("items", [])
        changes_summary = data.get("changes_summary")

        if not items:
            raise ValueError("Claude не вернул позиции. Проверьте содержимое документов.")

        await self.update_progress(f"Найдено {len(items)} позиций. Формирование Excel...")
        excel_data = generate_list(items, changes_summary=changes_summary)

        await self.save_result(
            "Перечень_из_Гранд-сметы.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            excel_data,
        )
        logger.info("List from Grand task completed", items=len(items))

    async def _heartbeat(self, stop_event: asyncio.Event) -> None:
        """Log a heartbeat every 30 s so it's clear the task is alive, not hung."""
        elapsed = 0
        while not stop_event.is_set():
            await asyncio.sleep(30)
            if stop_event.is_set():
                break
            elapsed += 30
            logger.info("Task still running", task_id=self.task_id, elapsed_seconds=elapsed)
