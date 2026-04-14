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
from app.services.claude_service import call_claude
from app.services.excel_service import generate_list
from app.constants import ESTIMATE_TASK_TYPES
from app.utils.xlsx_cost_parser import extract_total_cost
from app.utils.file_parser import parse_file, parse_xlsx_grand, chunk_rows, rows_to_text, pdf_to_content_block
from app.utils.json_utils import extract_json

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

    async def save_result(self, file_name: str, mime_type: str, file_data: bytes, slot: str = "result") -> None:
        result_record = TaskResult(
            task_id=self.task_id,
            file_name=file_name,
            mime_type=mime_type,
            file_data=file_data,
            slot=slot,
        )
        self.db.add(result_record)
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
            elif task_type == "CHECK_LIST_COMPLETENESS":
                await self._handle_check_completeness(task)
            elif task_type == "LIST_FROM_PROJECT":
                await self._handle_list_from_project(task)
            elif task_type == "CHECK_PROJECT_COMPLETENESS":
                await self._handle_check_project_completeness(task)
            else:
                raise NotImplementedError(f"Тип задачи {task.task_type!r} ещё не настроен")

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

    async def _handle_list_from_grand(self, task: Task) -> None:
        # --- Определяем, это resume или новый запуск ---
        progress_data = task.progress_data or {}
        start_chunk = progress_data.get("chunks_done", 0)
        accumulated_items: list = list(progress_data.get("items", []))
        partial_count: int = progress_data.get("partial_count", 0)

        # --- Извлекаем Excel из вложений ---
        await self.update_progress("Анализ файла гранд-сметы...")
        excel_bytes: Optional[bytes] = None
        for f in task.input_file_data or []:
            mime = f.get("mime_type", "")
            if "spreadsheet" in mime or "excel" in mime or mime == _XLSX_MIME:
                excel_bytes = base64.b64decode(f["content_b64"])
                break

        if not excel_bytes:
            raise ValueError("Excel-файл (.xlsx) не найден во вложениях задачи")

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
                    data = await self._call_claude_json(
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
            "Перечень_из_Гранд-сметы.xlsx",
            _XLSX_MIME,
            excel_data,
        )
        logger.info("List from Grand task completed", task_id=self.task_id, items=len(accumulated_items), chunks=total_chunks)

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

        if len(items) <= 300:
            chunks = [items]
        else:
            chunks = _chunk_by_work_boundaries(items)

        total_chunks = len(chunks)
        all_items: list = []
        changes_summary_parts: list = []

        for i, chunk in enumerate(chunks):
            await self._check_cancelled()
            if total_chunks > 1:
                await self.update_progress(f"Проверка части {i + 1} из {total_chunks}...")
            else:
                await self.update_progress("Проверяем полноту материалов по ГЭСН...")

            chunk_json = json.dumps({"items": chunk}, ensure_ascii=False, indent=2)
            messages = [{"role": "user", "content": f"{chunk_json}\n\n{PROMPT_CHECK_COMPLETENESS}"}]

            data = await self._call_claude_json(messages, system_prompt=SYSTEM_BASE)
            all_items.extend(data.get("items", []))
            summary = data.get("changes_summary", "")
            if summary:
                changes_summary_parts.append(summary)

        changes_summary = "\n\n".join(changes_summary_parts) if changes_summary_parts else None

        await self.update_progress(f"Проверено {len(all_items)} позиций. Формирование Excel...")
        excel_data = generate_list(all_items, changes_summary=changes_summary)
        await self.save_result("Проверка_полноты_ГЭСН.xlsx", _XLSX_MIME, excel_data)
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
        for f in task.input_file_data or []:
            if f.get("mime_type", "") == "application/pdf":
                pdf_bytes = base64.b64decode(f["content_b64"])
                break

        if not pdf_bytes:
            raise ValueError("PDF-файл не найден во вложениях задачи")

        await self.update_progress("Анализ проектной документации...")

        try:
            pdf_block = pdf_to_content_block(pdf_bytes)
        except ValueError as e:
            raise ValueError(str(e))

        messages = [{"role": "user", "content": PROMPT_LIST_FROM_PROJECT}]
        data = await self._call_claude_json(
            messages,
            system_prompt=SYSTEM_BASE,
            image_data=[pdf_block],
        )

        items = data.get("items", [])
        if not items:
            raise ValueError("Claude не вернул ни одной позиции. Проверьте содержимое PDF.")

        await self._save_progress_data({"items": items})
        await self.update_progress(f"Найдено {len(items)} позиций. Формирование Excel...")

        excel_data = generate_list(items)
        await self.save_result("Перечень_из_проекта.xlsx", _XLSX_MIME, excel_data)
        logger.info("List from project task completed", task_id=self.task_id, items=len(items))

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

        if len(items) <= 300:
            chunks = [items]
        else:
            chunks = _chunk_by_work_boundaries(items)

        total_chunks = len(chunks)
        all_items: list = []
        changes_summary_parts: list = []

        for i, chunk in enumerate(chunks):
            await self._check_cancelled()
            if total_chunks > 1:
                await self.update_progress(f"Проверка части {i + 1} из {total_chunks}...")
            else:
                await self.update_progress("Проверяем полноту материалов по ГЭСН...")

            chunk_json = json.dumps({"items": chunk}, ensure_ascii=False, indent=2)
            messages = [{"role": "user", "content": f"{chunk_json}\n\n{PROMPT_CHECK_PROJECT_COMPLETENESS}"}]

            data = await self._call_claude_json(messages, system_prompt=SYSTEM_BASE)
            all_items.extend(data.get("items", []))
            summary = data.get("changes_summary", "")
            if summary:
                changes_summary_parts.append(summary)

        changes_summary = "\n\n".join(changes_summary_parts) if changes_summary_parts else None

        await self.update_progress(f"Проверено {len(all_items)} позиций. Формирование Excel...")
        excel_data = generate_list(all_items, changes_summary=changes_summary)
        await self.save_result("Проверка_полноты_по_проекту.xlsx", _XLSX_MIME, excel_data)
        logger.info(
            "Check project completeness task completed",
            task_id=self.task_id,
            source_task_id=source_task_id,
            items=len(all_items),
            chunks=total_chunks,
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


async def process_task(task_id: str, db: AsyncSession) -> None:
    """Wrapper function for backward compatibility with routers."""
    processor = TaskProcessor(task_id, db)
    await processor.process()
