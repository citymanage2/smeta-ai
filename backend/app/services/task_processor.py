import asyncio
import base64
import json
import math
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.models.task import Task
from app.models.result import TaskResult
from app.models.task_input_file import TaskInputFile
from app.models.estimate_version import EstimateVersion
from app.services import storage_service
from app.services.claude_service import (
    call_claude,
    build_batch_request,
    submit_claude_batch,
    collect_claude_batch,
    InsufficientBalanceError,
    ResponseTruncatedError,
)
from app.services.excel_service import generate_list
from app.services.estimate_parser import parse_estimate_excel
from app.constants import ESTIMATE_TASK_TYPES, TERMINAL_TASK_STATUSES
from app.utils.xlsx_cost_parser import extract_total_cost, parse_list_sheet
from app.utils.file_parser import parse_file, parse_xlsx_grand, chunk_rows, rows_to_text
from app.utils.price_coercion import coerce_price
from app.utils.pdf_text_extractor import chunk_project_pdf
from app.utils.pdf_ocr_extractor import (
    chunk_pdf_pages,
    extract_single_page,
    get_pdf_page_count,
    timed_out_page_numbers,
)
from app.utils.json_utils import extract_json
from app.utils.xlsx_exporter import generate_estimate_xlsx
from app.utils.unit_normalizer import normalize_items
from app.services import price_service as _price_svc

# Fast-режим: сколько чанков ESTIMATE_FROM_LIST обрабатывать параллельно.
# 1 == последовательно (запасной путь). Значение — из env (Settings), чтобы
# снижать при множестве параллельных задач в worker (защита от 429 Anthropic).
from app.config import settings as _settings
FAST_CHUNK_CONCURRENCY = _settings.FAST_CHUNK_CONCURRENCY

# Шаг 2 ESTIMATE_FROM_LIST (fast/sync): каждые сколько чанков главного прохода
# сохранять промежуточный чекпоинт claude_partial. При паузе на балансе resume
# продолжит с последней группы — теряется максимум одна группа, а не вся смета.
ESTIMATE_MAIN_CHECKPOINT_GROUP = 8
# Размер чанка в проходе-доборе (пропущенные + нулевые цены). Было 5 в каждом из
# двух отдельных проходов: мелкий чанк заново запускает полный набор web-поисков,
# а платим мы за каждый поиск. Обрезка ответа теперь не фатальна — чанк дробится
# пополам (ResponseTruncatedError), поэтому запас по max_tokens не критичен.
ESTIMATE_RETRY_CHUNK = 10

# Предельный срок на одну пачку запросов к ИИ (см. Settings.CHUNK_STAGE_DEADLINE_S).
CHUNK_STAGE_DEADLINE_S = _settings.CHUNK_STAGE_DEADLINE_S


def _chunk_stage_deadline(n_chunks: int, concurrency: int) -> float:
    """Дедлайн пачки, растущий вместе с её размером.

    Фиксированное значение не годится: пачки бывают и на 8 чанков (главный проход
    группами), и на 30+ (добор позиций без цены). При параллельности 4 тридцать
    чанков — это 8 волн, штатно ~24 минуты, и жёсткие 30 минут обрывали бы
    здоровую работу. Считаем по волнам, с щедрым запасом на волну: цель — поймать
    зависание (часы), а не подгонять норматив.
    """
    waves = max(1, math.ceil(n_chunks / max(1, concurrency)))
    return max(float(CHUNK_STAGE_DEADLINE_S), waves * 600.0)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

logger = structlog.get_logger()


def _balance_error_detail(err: Exception) -> str:
    """Хвост для сообщения о паузе с сырым ответом API (или пустая строка).

    Нужен, потому что текст паузы фиксированный («баланс Anthropic исчерпан»), а
    на сервере запросы идут через агрегатор (ANTHROPIC_BASE_URL) — без ответа API
    непонятно, чей счёт пуст и не путаем ли мы билинг с другой 4xx-ошибкой.
    """
    status_code = getattr(err, "status_code", None)
    api_message = (getattr(err, "api_message", None) or "").strip()
    if not status_code and not api_message:
        return ""
    parts = [str(status_code) if status_code else "—"]
    if api_message:
        parts.append(api_message[:200])
    return f" Ответ API: {' '.join(parts)}"

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

ПРОПУСКАЙ следующие строки (они не являются работами или материалами):
- строки с кодами расценок без описания (ФЕР-xx, ТЕР-xx, ГЭСН-xx и т.п.)
- строки с обозначениями составляющих затрат: «1 ОТ», «2 ЭМ», «3 в т.ч. ОТм», «4 М» и аналогичные
- заголовки разделов и глав (Раздел 1, Глава 2 и т.п.)
- итоговые строки (Итого, Всего, НДС, НР, СП, ФОТ и т.п.)

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

ВАЖНО ПРО НДС: поля work_price и material_price ВСЕГДА должны содержать цену БЕЗ НДС.
Если найденная рыночная цена включает НДС — раздели её на 1.22, чтобы получить цену без НДС.
Поле notes заполняй КРАТКО и только по необходимости:
  - если из найденной цены вычитался НДС — короткая пометка "НДС вычтен"
  - для работ на УСН — короткая пометка "УСН, без НДС"
  - в остальных случаях notes оставляй пустым ("")
Не дублируй в notes цену и источники — цена уже в полях work_price/material_price, источники — в sources.

КРИТИЧЕСКИ ВАЖНО: каждая входная позиция имеет числовое поле "id".
Ты ОБЯЗАН вернуть результат для КАЖДОЙ позиции из списка, сохранив то же самое
значение "id" без изменений. Пропуск любой позиции недопустим.

АБСОЛЮТНЫЙ ЗАПРЕТ на null-цены:
- Для позиции типа "Работа": поле work_price ОБЯЗАНО быть числом больше нуля. null и 0 недопустимы.
- Для позиции типа "Материал": поле material_price ОБЯЗАНО быть числом больше нуля. null и 0 недопустимы.
Если точная цена неизвестна — используй рыночную оценку из открытых источников г. Екатеринбург.
Придумать число нельзя, но найти реальную рыночную цену — обязательно.

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
      "work_price": число без НДС или null,
      "material_price": число без НДС или null,
      "sources": "Источник 1: цена; Источник 2: цена; Источник 3: цена",
      "notes": "" или краткая пометка про НДС (см. правило выше)
    }}
  ]
}}"""


PROMPT_ENRICH_NORMS = """Ты — опытный инженер-сметчик со знанием ГЭСН-2017/ФСНБ-2022, ФЕР/ТЕР по Свердловской области.

Тебе передан перечень работ и материалов из строительной сметы.
Для каждого материала определи норматив расхода на единицу работы по ГЭСН/ФСНБ.

Для каждого материала верни:
- qty_per_work_unit: число (норма расхода на 1 единицу работы) или null, если норма не определена
- norm_reference: шифр нормы, например "ГЭСН 08-01-003" или null

Верни результат СТРОГО в формате JSON, без markdown, первый символ {, последний }:
{
  "materials": [
    {
      "row_id": "id строки материала",
      "qty_per_work_unit": число или null,
      "norm_reference": "ГЭСН XX-XX-XXX" или null
    }
  ]
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }."""


def _chunk_by_work_boundaries(items: list, max_chunk_size: int = 200) -> list:
    """Split items into chunks at 'Работа' boundaries when possible, or by hard size limit."""
    if not items:
        return []
    chunks = []
    current_chunk: list = []
    for item in items:
        is_work = item.get("type", "").strip() == "Работа"
        # Split at Работа boundary when chunk is large enough
        if is_work and current_chunk and len(current_chunk) >= max_chunk_size:
            chunks.append(current_chunk)
            current_chunk = []
        # Hard limit: split even mid-block if chunk doubled the target size
        elif len(current_chunk) >= max_chunk_size * 2:
            chunks.append(current_chunk)
            current_chunk = []
        current_chunk.append(item)
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


class TaskCancelledError(Exception):
    """Raised when a task has been cancelled by the user."""


class StageDeadlineError(Exception):
    """Этап не уложился в отведённое время и был прерван.

    Отдельный тип, а не TaskCancelledError: пользователю нельзя писать «вы
    остановили задачу», когда её оборвал таймаут. Уже оплаченные чанки при этом
    применяются и попадают в чекпоинт — перезапуск продолжит с них.
    """


class TaskProcessor:
    def __init__(
        self,
        task_id: str,
        db: AsyncSession,
        job_id: Optional[int] = None,
        job_attempt: Optional[int] = None,
    ):
        self.task_id = task_id
        self.db = db
        # id job, под которой идёт ЭТОТ прогон. Признак поколения: «Перезапустить»
        # снимает старую job и ставит новую, и по нему прежний прогон понимает, что
        # его сменили, и останавливается на ближайшем чекпоинте. Без этого рестарт
        # висящей задачи запускал ВТОРОЙ прогон параллельно первому — двойная
        # стоимость API и два обработчика, пишущих в одну задачу.
        self.job_id = job_id
        # Номер попытки этой job на момент захвата. Деплой и reclaim возвращают ту
        # же job в очередь, и следующий захват увеличивает attempts — по нему
        # «зависший» прогон отличает себя от того, кто считает задачу сейчас.
        self.job_attempt = job_attempt
        self._input_files_cache: list[dict] | None = None

    async def _load_input_files(self, task: Task) -> list[dict]:
        """Return input files with content_b64, loading bytes from S3 by storage_key.

        Все входные файлы (в т.ч. перенесённые legacy) лежат в task_input_files;
        байты — в S3. Результат кэшируется на время одного прогона процессора.
        """
        if self._input_files_cache is not None:
            return self._input_files_cache

        result = await self.db.execute(
            select(TaskInputFile)
            .where(TaskInputFile.task_id == self.task_id)
            .order_by(TaskInputFile.file_index)
        )
        rows = result.scalars().all()
        files = []
        for r in rows:
            data = await storage_service.load_bytes(r.storage_key)
            files.append({
                "name": r.file_name,
                "mime_type": r.mime_type,
                "size_bytes": r.size_bytes,
                "content_b64": base64.b64encode(data).decode("utf-8"),
            })
        self._input_files_cache = files
        return self._input_files_cache

    async def _check_cancelled(self) -> None:
        """Остановить прогон, если задачу отменили ИЛИ этот прогон сменили новым.

        Второе — про «Перезапустить»: он снимает job текущего прогона и ставит
        новую. Прежний обработчик об этом иначе не узнает и продолжит считать
        параллельно новому: два прогона пишут в одну задачу, а запросы к ИИ
        оплачиваются дважды. Своя job больше не `running` → нас сменили, выходим.
        """
        result = await self.db.execute(
            select(Task).where(Task.id == self.task_id)
        )
        task = result.scalar_one_or_none()
        if task and task.status == "cancelled":
            raise TaskCancelledError("Задача остановлена пользователем")

        if self.job_id is None:
            return
        from app.models.job import Job

        row = (
            await self.db.execute(
                select(Job.status, Job.attempts).where(Job.id == self.job_id)
            )
        ).first()
        if row is None:
            return
        job_status, job_attempts = row

        # Номер попытки — точный признак поколения. Одну и ту же job могут выдать
        # заново: деплой возвращает её в очередь, reclaim — тоже (через 15 минут
        # без сигнала). Каждый новый захват увеличивает attempts, а heartbeat его
        # не трогает. Если наш номер устарел, значит задачу уже считает кто-то
        # другой, и продолжать — это второй прогон и вторая оплата запросов к ИИ.
        superseded = job_status != "running" or (
            self.job_attempt is not None and job_attempts != self.job_attempt
        )
        if superseded:
            logger.info(
                "Run superseded — прогон заменён",
                task_id=self.task_id,
                job_id=self.job_id,
                job_status=job_status,
                job_attempts=job_attempts,
                my_attempt=self.job_attempt,
            )
            raise TaskCancelledError("Прогон заменён новым")

    async def update_progress(self, message: str) -> None:
        result = await self.db.execute(
            select(Task).where(Task.id == self.task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            task.progress_message = message
            current_log = list(task.progress_log or [])
            if not current_log or current_log[-1] != message:
                current_log.append(message)
                task.progress_log = current_log
            task.updated_at = datetime.now(timezone.utc)
            await self.db.commit()
        logger.info("Task progress", task_id=self.task_id, message=message)

    async def update_progress_message(self, message: str) -> None:
        """Обновить ТОЛЬКО живую строку статуса, не дописывая её в историю.

        Для часто меняющихся индикаторов («готово 7 из 38»): update_progress
        добавляет каждое новое сообщение в progress_log, и тик раз в 10 секунд
        распухал бы блок «ХОД ВЫПОЛНЕНИЯ» на сотни строк за один этап.
        updated_at двигаем — по нему видно, что задача жива.
        """
        result = await self.db.execute(
            select(Task).where(Task.id == self.task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            task.progress_message = message
            task.updated_at = datetime.now(timezone.utc)
            await self.db.commit()

    async def update_status(self, status: str, error: Optional[str] = None) -> None:
        result = await self.db.execute(
            select(Task).where(Task.id == self.task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            now = datetime.now(timezone.utc)
            task.status = status
            task.updated_at = now
            # Границы фактической обработки — основа прогноза времени (eta_service).
            # started_at переставляем на КАЖДЫЙ прогон: после рестарта или resume
            # остаток задачи считается от текущего запуска, а не от первой попытки.
            if status == "processing":
                task.started_at = now
            elif status in TERMINAL_TASK_STATUSES:
                task.finished_at = now
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
        existing = await self.db.execute(
            select(TaskResult).where(
                TaskResult.task_id == self.task_id,
                TaskResult.slot == slot,
            ).limit(1)
        )
        record = existing.scalar_one_or_none()
        old_key = record.storage_key if record is not None else None
        storage_key = await storage_service.store_result_file(
            self.task_id, slot, file_name, mime_type, file_data
        )
        if record is not None:
            record.file_name = file_name
            record.mime_type = mime_type
            record.storage_key = storage_key
            record.size_bytes = len(file_data)
        else:
            record = TaskResult(
                task_id=self.task_id,
                file_name=file_name,
                mime_type=mime_type,
                storage_key=storage_key,
                size_bytes=len(file_data),
                slot=slot,
            )
            self.db.add(record)
        await self.db.commit()
        if old_key and old_key != storage_key:
            await storage_service.delete_key_safe(old_key)  # прежний объект слота

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

    @staticmethod
    def _json_safe(obj):
        """Recursively convert non-JSON-serializable types (datetime, date, Decimal) to primitives."""
        if isinstance(obj, dict):
            return {k: TaskProcessor._json_safe(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [TaskProcessor._json_safe(v) for v in obj]
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return obj

    async def _is_batch_pending(self) -> bool:
        """Свежий из БД признак «пачка Batch API отправлена, результатов ещё нет»."""
        from app.services.checkpoint import is_batch_pending

        result = await self.db.execute(select(Task).where(Task.id == self.task_id))
        task = result.scalar_one_or_none()
        return bool(task) and is_batch_pending(task.progress_data)

    async def _save_progress_data(self, data: dict) -> None:
        result = await self.db.execute(select(Task).where(Task.id == self.task_id))
        task = result.scalar_one_or_none()
        if task:
            task.progress_data = TaskProcessor._json_safe(data)
            task.updated_at = datetime.now(timezone.utc)
            await self.db.commit()

    async def _auto_fill_estimate_slot(self) -> None:
        """Promote slot='result' → 'estimate' and set estimation_status after task completes.

        Called automatically when an ESTIMATE_TASK_TYPE (except ESTIMATE_OPTIMIZATION,
        which manages its own slots) transitions to 'completed'.
        """
        task_res = await self.db.execute(select(Task).where(Task.id == self.task_id))
        task = task_res.scalar_one_or_none()
        if not task or task.task_type not in ESTIMATE_TASK_TYPES or task.task_type == "ESTIMATE_OPTIMIZATION":
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
                cost_bytes = await storage_service.load_bytes(result_row.storage_key)
                cost = extract_total_cost(cost_bytes)
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
        cancel_check_interval: float = 10.0,
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
        finally:
            # Guarantee api_task is cancelled regardless of what exception propagated.
            # Prevents orphaned API calls when _check_cancelled() raises a non-cancel error.
            if not api_task.done():
                api_task.cancel()
                try:
                    await api_task
                except (asyncio.CancelledError, Exception):
                    pass

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
            except InsufficientBalanceError:
                # Баланс API исчерпан — ретраи не помогут; пробрасываем на паузу.
                raise
            except ResponseTruncatedError:
                # Промпт не изменился → повтор снова упрётся в max_tokens.
                # Ретрай здесь стоил бы трёх полных оплаченных вызовов; порцию
                # данных уменьшает caller (дробит чанк).
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
            except InsufficientBalanceError:
                # Баланс API исчерпан — ретраи не помогут; пробрасываем на паузу.
                raise
            except ResponseTruncatedError:
                # Промпт не изменился → повтор снова упрётся в max_tokens.
                # Ретрай здесь стоил бы трёх полных оплаченных вызовов; порцию
                # данных уменьшает caller (дробит чанк).
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
                    await self._check_cancelled()
        raise last_error  # type: ignore[misc]

    async def _run_chunks_parallel(
        self,
        workers: list,
        concurrency: int = FAST_CHUNK_CONCURRENCY,
        cancel_check_interval: float = 10.0,
        return_exceptions: bool = False,
        progress_label: Optional[str] = None,
        progress_tick: Optional[float] = None,
        progress_offset: int = 0,
        progress_total: Optional[int] = None,
        deadline_s: Optional[float] = None,
    ) -> list:
        """Выполнить db-free воркеры параллельно под Semaphore, вернуть результаты по порядку.

        return_exceptions=True — не поднимать исключение воркера, а вернуть его на
        месте результата (включая CancelledError при отмене задачи). Нужно там, где
        ответы уже оплачены: caller обязан применить успешные и сохранить чекпоинт,
        и только потом падать — иначе resume оплатит их второй раз.

        Каждый worker — zero-arg async callable, который НЕ обращается к self.db
        (иначе конкурентный доступ к AsyncSession сломает сессию). Отмена задачи
        отслеживается одним общим watcher-ом (self.db читает только он) — при отмене
        воркеры отменяются и поднимается TaskCancelledError. concurrency=1 → фактически
        последовательно. Реальные (не-отмена) исключения воркеров пробрасываются.

        progress_label — шаблон с полями {done}/{total}; если задан, watcher
            публикует «сколько уже готово» по мере завершения воркеров. Публикует
            именно watcher, а не воркеры: он и так единственный, кому разрешён
            self.db, поэтому новых точек конкуренции по сессии не появляется.
            Идёт в progress_message мимо progress_log — иначе история «ХОД
            ВЫПОЛНЕНИЯ» распухла бы на сотни строк за один этап.

        progress_offset / progress_total — сквозной счёт, когда пачка это лишь
            часть работы задачи. Без них пользователь увидел бы «готово 8 из 8»,
            а затем снова «готово 1 из 8» на следующей группе — счётчик, который
            откатывается, хуже отсутствующего.

        deadline_s — предельный срок на всю пачку. По истечении незавершённые
            воркеры отменяются, и на их месте оказывается StageDeadlineError
            (а не CancelledError) — чтобы caller отличил таймаут от нажатия
            «Стоп» и не написал пользователю, будто тот сам остановил задачу.
            Без него зависший API растягивает пачку на часы: автоповтор ждёт до
            RATE_LIMIT_MAX_WAIT на попытку, и это умножается на число чанков.
        """
        if not workers:
            return []

        sem = asyncio.Semaphore(max(1, concurrency))
        total = progress_total if progress_total is not None else len(workers)
        done_count = {"n": 0}

        async def _guard(w):
            async with sem:
                try:
                    return await w()
                finally:
                    # Счётчик в памяти: воркеру по-прежнему нельзя трогать self.db.
                    done_count["n"] += 1

        tasks = [asyncio.create_task(_guard(w)) for w in workers]
        cancelled = {"flag": False}
        timed_out = {"flag": False}

        tick = progress_tick if progress_tick is not None else cancel_check_interval
        started_at = asyncio.get_event_loop().time()

        async def _watch():
            last_published = -1
            try:
                while True:
                    await asyncio.sleep(tick)
                    if all(t.done() for t in tasks):
                        return

                    if deadline_s is not None and (
                        asyncio.get_event_loop().time() - started_at >= deadline_s
                    ):
                        timed_out["flag"] = True
                        for t in tasks:
                            if not t.done():
                                t.cancel()
                        return

                    if progress_label and done_count["n"] != last_published:
                        last_published = done_count["n"]
                        try:
                            await self.update_progress_message(
                                progress_label.format(
                                    done=progress_offset + last_published, total=total
                                )
                            )
                        except Exception as pub_err:  # noqa: BLE001
                            # Живой индикатор — вспомогательный: сбой его записи
                            # не должен ронять уже оплаченную пачку.
                            logger.warning(
                                "Failed to publish chunk progress",
                                task_id=self.task_id,
                                error=str(pub_err),
                            )

                    try:
                        await self._check_cancelled()
                    except TaskCancelledError:
                        cancelled["flag"] = True
                        for t in tasks:
                            if not t.done():
                                t.cancel()
                        return
            except asyncio.CancelledError:
                return

        watcher = asyncio.create_task(_watch())
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):
                pass

        # Отмена по дедлайну доходит до gather как CancelledError — неотличимо от
        # пользовательского «Стоп». Подменяем на типизированную ошибку, пока
        # известна настоящая причина.
        if timed_out["flag"]:
            deadline_msg = (
                f"Этап не уложился в отведённое время ({int(deadline_s or 0) // 60} мин.). "
                "Обработано не всё; сохранённый результат можно продолжить перезапуском."
            )
            results = [
                StageDeadlineError(deadline_msg) if isinstance(r, asyncio.CancelledError) else r
                for r in results
            ]

        if return_exceptions:
            # Отмена приходит сюда как CancelledError в результатах: флаг ставится
            # только когда есть незавершённые таски, и они тут же отменяются.
            return results

        if cancelled["flag"]:
            raise TaskCancelledError("Задача остановлена пользователем")

        for r in results:
            if isinstance(r, asyncio.CancelledError):
                raise TaskCancelledError("Задача остановлена пользователем")
            if isinstance(r, BaseException):
                raise r
        return results

    async def _fetch_price_chunk(
        self, chunk: list[dict], current_date: str, chunk_label: str
    ) -> list[dict]:
        """DB-free: отправить чанк позиций в Claude, вернуть список result-items.

        НЕ обращается к self.db (безопасно под _run_chunks_parallel).
        Ошибки чанка (кроме отмены/таймаута/баланса) поглощаются → [].
        Используется и основным проходом сметы, и добором после batch-режима.
        """
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
            # Non-interruptible вариант: НЕ поллит self.db (отмену ведёт общий
            # watcher в _run_chunks_parallel). Логирование стоимости в call_claude
            # использует независимую сессию — конкуренции по self.db нет.
            data = await self._call_claude_json_with_retry(
                messages,
                system_prompt=SYSTEM_BASE,
                use_web_search=True,
                processing_timeout=1200.0,
            )
        except (TaskCancelledError, asyncio.TimeoutError):
            raise
        except InsufficientBalanceError:
            # Баланс API исчерпан — не проглатываем чанк, пробрасываем на паузу.
            raise
        except ResponseTruncatedError:
            # Ответ не поместился в max_tokens. Повторять тот же чанк
            # бессмысленно и дорого — режем пополам и считаем половины.
            if len(chunk) < 2:
                logger.warning(
                    "Single item response truncated, skipping",
                    task_id=self.task_id,
                    chunk_label=chunk_label,
                    name=chunk[0].get("name") if chunk else None,
                )
                return []
            mid = len(chunk) // 2
            logger.warning(
                "Chunk response truncated, splitting in half",
                task_id=self.task_id,
                chunk_label=chunk_label,
                size=len(chunk),
            )
            left = await self._fetch_price_chunk(chunk[:mid], current_date, f"{chunk_label}a")
            right = await self._fetch_price_chunk(chunk[mid:], current_date, f"{chunk_label}b")
            return left + right
        except Exception as chunk_error:
            logger.warning(
                "Claude chunk failed for ESTIMATE_FROM_LIST, skipping",
                task_id=self.task_id,
                chunk_label=chunk_label,
                error=str(chunk_error),
            )
            return []
        return data.get("items", [])

    @staticmethod
    def _ids_without_price(
        unmatched_by_gidx: dict[int, dict], claude_results: dict[int, dict]
    ) -> list[int]:
        """Позиции, которые Claude пропустил или вернул с нулевой ценой.

        Одна и та же проблема «цены нет» — раньше два отдельных прохода.
        """
        problem: list[int] = []
        for gidx, item in unmatched_by_gidx.items():
            cr = claude_results.get(gidx)
            if cr is None:
                problem.append(gidx)
                continue
            # coerce_price, а не `not ...`: строка «мусор» и отрицательная цена
            # тоже truthy, то есть раньше считались готовыми и уезжали в смету
            # вместо того, чтобы попасть в добор и получить вторую попытку.
            if item.get("type") == "Работа" and coerce_price(cr.get("work_price")) is None:
                problem.append(gidx)
            elif item.get("type") == "Материал" and coerce_price(cr.get("material_price")) is None:
                problem.append(gidx)
        return sorted(problem)

    async def _cache_priced_item(self, result_item: dict) -> None:
        """Сохранить цену позиции в кеш (self.db), если она валидна. Ошибки поглощает."""
        _item_type_str = result_item.get("type", "")
        _item_name = result_item.get("name", "")
        _item_unit = result_item.get("unit")
        _item_sources = result_item.get("sources")
        try:
            # coerce_price вместо float(...): непригодное значение раньше роняло
            # float() и уходило в except ниже как «ошибка кеша», хотя это просто
            # отсутствие цены. В кеш должны попадать только пригодные цены —
            # иначе мусор от ИИ переиспользуется в следующих сметах.
            if _item_type_str == "Работа":
                _item_price = coerce_price(result_item.get("work_price"))
                if _item_price is not None:
                    await _price_svc.save_to_cache(
                        self.db, "work", _item_name, _item_unit, _item_price, _item_sources
                    )
                    logger.info("Saved to price cache", task_id=self.task_id, name=_item_name)
            elif _item_type_str == "Материал":
                _item_price = coerce_price(result_item.get("material_price"))
                if _item_price is not None:
                    await _price_svc.save_to_cache(
                        self.db, "material", _item_name, _item_unit, _item_price, _item_sources
                    )
                    logger.info("Saved to price cache", task_id=self.task_id, name=_item_name)
        except Exception as _cache_err:
            logger.warning("Failed to save to price cache", task_id=self.task_id, name=_item_name, error=str(_cache_err))

    @staticmethod
    def _pending_chunks(chunks: list, done_ids: set) -> list:
        """Отфильтровать чанки, оставив только позиции с _id, ещё не посчитанными
        Claude (done_ids). Полностью посчитанные чанки исключаются, частичные —
        обрезаются до необсчитанных позиций. Для resume fast/sync: уже оценённые
        позиции повторно в Claude не отправляются."""
        out: list = []
        for c in chunks:
            rem = [it for it in c if it.get("_id") not in done_ids]
            if rem:
                out.append(rem)
        return out

    async def _save_claude_partial(
        self, items: list, matched_by_gidx: dict, claude_results: dict
    ) -> None:
        """Промежуточный чекпоинт шага 2 (fast/sync): накопленные claude_results.
        Тот же формат, что pre_excel, но _stage="claude_partial" — resume прогонит
        шаги 0-1 заново, а шаг 2 продолжит только по необсчитанным позициям."""
        await self._save_progress_data({
            "_stage": "claude_partial",
            "items": items,
            "matched": {str(k): v for k, v in matched_by_gidx.items()},
            "claude_results": {str(k): v for k, v in claude_results.items()},
        })

    async def _submit_estimate_batch(
        self,
        task: Task,
        items: list[dict],
        matched_by_gidx: dict,
        unmatched_by_gidx: dict,
        current_date: str,
        chunks: list[list[dict]],
    ) -> None:
        """Batch-режим: отправить чанки ненайденных позиций в Message Batches API,
        сохранить состояние (_stage=batch_pending) и выйти. Смету достроит поллер
        (Phase 5) через resume_from_batch после завершения пачки.
        """
        # Resumable-чекпоинт ДО отправки: если билинг падает на submit_claude_batch
        # (баланс исчерпан) → задача уходит в paused. Без этого чекпоинта её не
        # подхватил бы resume_poller (batch_pending не входит в RESUMABLE_STAGES,
        # а до submit его ещё нет). claude_partial с пустыми результатами → resume
        # прогонит шаги 0-1 заново (дёшево) и повторит отправку пачки.
        await self._save_claude_partial(items, matched_by_gidx, {})

        requests = []
        for i, chunk in enumerate(chunks):
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
            requests.append(
                build_batch_request(
                    custom_id=f"chunk-{i}",
                    messages=[{"role": "user", "content": prompt_text}],
                    system_prompt=SYSTEM_BASE,
                    use_web_search=True,
                )
            )

        batch_id = await submit_claude_batch(requests)
        await self._save_progress_data({
            "_stage": "batch_pending",
            "batch_id": batch_id,
            "items": items,
            "matched": {str(k): v for k, v in matched_by_gidx.items()},
            "unmatched": {str(k): v for k, v in unmatched_by_gidx.items()},
            "current_date": current_date,
        })
        await self.update_progress(
            f"Отправлено в пакетную обработку (Batch API): {len(chunks)} чанк(ов). "
            f"Ожидание результатов (обычно до часа)..."
        )
        logger.info(
            "Estimate batch submitted",
            task_id=self.task_id, batch_id=batch_id, chunks=len(chunks),
        )

    async def resume_from_batch(self, task: Task) -> None:
        """Вызывается поллером (Phase 5), когда пачка завершена: собрать результаты,
        наполнить claude_results, сохранить pre_excel-чекпоинт и запустить step3.

        Позиции, которые пачка пропустила или вернула с нулевой ценой, добираются
        синхронно тем же путём, что и в fast-режиме (обычно это единицы позиций —
        второй часовой пачки ради них не нужно). Без добора смета выходила с
        пустыми ценами, чего быть не должно.

        Идемпотентно: повторный вызов после рестарта повторно собирает ту же пачку.
        """
        from datetime import date as _date

        _p = task.progress_data or {}
        batch_id = _p.get("batch_id")
        items: list[dict] = _p.get("items", [])
        matched = {int(k): v for k, v in _p.get("matched", {}).items()}
        unmatched = {int(k): v for k, v in _p.get("unmatched", {}).items()}
        current_date = _p.get("current_date") or _date.today().strftime("%d.%m.%Y")

        await self.update_progress("Batch завершён. Сбор результатов и формирование сметы...")

        claude_results: dict[int, dict] = {}
        results_by_cid = await collect_claude_batch(batch_id, task_id=self.task_id, db=self.db)
        for _cid, entry in results_by_cid.items():
            if entry.get("error") or not entry.get("text"):
                continue
            try:
                data = self._parse_json_response(entry["text"])
            except ValueError:
                logger.warning("Batch chunk JSON parse failed, skipping", task_id=self.task_id, custom_id=_cid)
                continue
            for result_item in data.get("items", []):
                item_id = result_item.get("id")
                if item_id is not None:
                    claude_results[int(item_id)] = result_item
                    await self._cache_priced_item(result_item)

        # Добор: позиции без цены после пачки. В fast-режиме это отдельный проход
        # после основного; batch без него отдавал смету с пустыми ценами.
        problem_ids = self._ids_without_price(unmatched, claude_results)
        if problem_ids:
            await self.update_progress(
                f"Добор {len(problem_ids)} позиций без цены после пакетной обработки..."
            )
            problem_items = [unmatched[gidx] for gidx in problem_ids]
            retry_chunks = [
                problem_items[i:i + ESTIMATE_RETRY_CHUNK]
                for i in range(0, len(problem_items), ESTIMATE_RETRY_CHUNK)
            ]
            total_retry = len(retry_chunks)
            workers = [
                (lambda c=c, k=k: self._fetch_price_chunk(
                    c, current_date, f"batch-retry-{k + 1}/{total_retry}"
                ))
                for k, c in enumerate(retry_chunks)
            ]
            results = await self._run_chunks_parallel(
                workers, concurrency=FAST_CHUNK_CONCURRENCY, return_exceptions=True,
                progress_label="Добор цен: готово {done} из {total} частей...",
                deadline_s=_chunk_stage_deadline(total_retry, FAST_CHUNK_CONCURRENCY),
            )
            first_error: Optional[BaseException] = None
            for chunk_result in results:
                if isinstance(chunk_result, BaseException):
                    if first_error is None:
                        first_error = chunk_result
                    continue
                for result_item in chunk_result:
                    item_id = result_item.get("id")
                    if item_id is not None:
                        claude_results[int(item_id)] = result_item
                        await self._cache_priced_item(result_item)
            if first_error is not None:
                # Пачка уже оплачена — фиксируем всё собранное, чтобы повторный
                # заход (пауза по балансу) не пересчитывал её заново.
                await self._save_progress_data({
                    "_stage": "pre_excel",
                    "items": items,
                    "matched": {str(k): v for k, v in matched.items()},
                    "claude_results": {str(k): v for k, v in claude_results.items()},
                })
                if isinstance(first_error, asyncio.CancelledError):
                    raise TaskCancelledError("Задача остановлена пользователем")
                raise first_error

            still_empty = self._ids_without_price(unmatched, claude_results)
            if still_empty:
                logger.warning(
                    "Some items remain unpriced after batch retry",
                    task_id=self.task_id,
                    count=len(still_empty),
                    names=[unmatched[g].get("name") for g in still_empty],
                )

        # pre_excel-чекпоинт (тот же формат, что и fast-путь) — устойчивость к рестарту на step3.
        await self._save_progress_data({
            "_stage": "pre_excel",
            "items": items,
            "matched": {str(k): v for k, v in matched.items()},
            "claude_results": {str(k): v for k, v in claude_results.items()},
        })
        await self._run_estimate_step3(task, items, matched, claude_results)

    async def process(self) -> None:
        """Main processing method."""
        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat(stop_event)
        )
        try:
            # Читаем задачу ДО перевода в `processing`: раньше статус ставился
            # безусловно, и job отменённой (или удалённой в корзину) задачи
            # воскрешала её в «Обработку» — со слотом воркера и оплаченными
            # запросами. Отмена и удаление должны быть окончательными.
            result = await self.db.execute(
                select(Task).where(Task.id == self.task_id)
            )
            task = result.scalar_one_or_none()
            if not task:
                raise ValueError(f"Задача {self.task_id} не найдена")
            if task.status == "cancelled" or task.deleted_at is not None:
                logger.info(
                    "Task not processed — cancelled or deleted",
                    task_id=self.task_id,
                    status=task.status,
                    deleted=task.deleted_at is not None,
                )
                return

            await self.update_status("processing")
            await self.update_progress("Начало обработки задачи...")

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

            # Batch-режим: пачка отправлена в Anthropic, результатов ещё нет —
            # задача НЕ завершена. Оставляем `processing`, чтобы её увидел
            # batch_poller (он ищет processing + _stage=batch_pending) и достроил
            # смету. Иначе задача помечалась completed без результата и поллер
            # её больше никогда не подхватывал.
            if await self._is_batch_pending():
                logger.info("Task left in processing — batch pending", task_id=self.task_id)
                return

            await self._auto_fill_estimate_slot()
            await self.update_status("completed")

        except TaskCancelledError:
            logger.info("Task was cancelled by user", task_id=self.task_id)
        except StageDeadlineError as deadline_error:
            # Этап оборвался по таймауту. Не paused: пауза означает «ждём
            # пополнения счёта», и resume_poller крутил бы такую задачу каждые
            # 10 минут по кругу. Честный failed + сохранённый чекпоинт: перезапуск
            # продолжит с последней группы, уже оплаченное не оплачивается снова.
            logger.error(
                "Task failed — stage deadline exceeded",
                task_id=self.task_id,
                error=str(deadline_error),
            )
            try:
                await self.db.rollback()
            except Exception:
                pass
            await self.update_status("failed", error=str(deadline_error))
            await self.update_progress(f"⏱ {deadline_error}")
        except InsufficientBalanceError as balance_error:
            # Баланс API исчерпан — не failed, а пауза. Чекпоинт (progress_data)
            # к этому моменту уже сохранён отдельными сессиями и переживает
            # rollback; планировщик возобновит задачу после пополнения счёта.
            logger.warning(
                "Task paused — Anthropic API balance exhausted",
                task_id=self.task_id,
                status_code=getattr(balance_error, "status_code", None),
                api_message=getattr(balance_error, "api_message", None),
            )
            try:
                await self.db.rollback()
            except Exception:
                pass
            await self.update_status(
                "paused",
                error="Баланс API Anthropic исчерпан. Задача продолжится автоматически после пополнения счёта.",
            )
            # Сырой ответ API — в шаг прогресса: на сервере запросы идут через
            # агрегатор, и без этой строки нельзя понять, чей счёт пуст (диагноз
            # иначе только по логам worker'а).
            await self.update_progress(
                "⏸ На паузе: баланс API исчерпан. Возобновление произойдёт автоматически после пополнения."
                + _balance_error_detail(balance_error)
            )
        except Exception as e:
            logger.error("Task processing failed", task_id=self.task_id, error=str(e))
            try:
                await self.db.rollback()
            except Exception:
                pass
            await self.update_status("failed", error=str(e))
            await self.update_progress(f"Ошибка: {str(e)[:400]}")
        finally:
            stop_event.set()
            heartbeat_task.cancel()

    async def _save_partial(self, items: list, chunk_idx: int, total: int, prefix: str = "Частичная_проверка") -> None:
        """Save accumulated items as a partial Excel result."""
        excel_data = await asyncio.to_thread(generate_list,items)
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
                        accumulated_items = normalize_items(accumulated_items)
                        partial_excel = await asyncio.to_thread(generate_list,accumulated_items)
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
                        accumulated_items = normalize_items(accumulated_items)
                        partial_excel = await asyncio.to_thread(generate_list,accumulated_items)
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

        accumulated_items = normalize_items(accumulated_items)
        await self.update_progress(f"Найдено {len(accumulated_items)} позиций. Формирование Excel...")
        excel_data = await asyncio.to_thread(generate_list,accumulated_items)
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

        # OCR выполняется постранично: каждая страница сохраняется в progress_data.
        # При рестарте инстанса — продолжаем с той страницы, на которой остановились.
        if "ocr_pages" in progress_data:
            # Все страницы уже распознаны до предыдущего рестарта
            pages = progress_data["ocr_pages"]
            await self.update_progress(
                f"OCR уже выполнен ({len(pages)} стр.), продолжаем обработку..."
            )
        else:
            pages_partial: list = list(progress_data.get("ocr_pages_partial", []))
            ocr_start_page = len(pages_partial)

            total_pages = await asyncio.to_thread(get_pdf_page_count, pdf_bytes)

            if ocr_start_page > 0:
                await self.update_progress(
                    f"Продолжаем OCR со страницы {ocr_start_page + 1} из {total_pages}..."
                )
            else:
                await self.update_progress(
                    f"Извлечение текста из PDF гранд-сметы ({total_pages} стр.)..."
                )

            # A5: предупреждение о большом файле
            if total_pages > 50:
                await self.update_progress(
                    f"Большой файл: {total_pages} страниц, обработка займёт несколько минут..."
                )

            for page_idx in range(ocr_start_page, total_pages):
                await self.update_progress(
                    f"OCR страницы {page_idx + 1} из {total_pages}..."
                )
                # Каждая страница обрабатывается в отдельном потоке — event loop свободен.
                # extract_single_page открывает и закрывает PDF каждый раз — освобождает память.
                page_result = await asyncio.to_thread(extract_single_page, pdf_bytes, page_idx)
                pages_partial.append(page_result)
                # Сохраняем прогресс после каждой страницы — при следующем рестарте пропустим её
                await self._save_progress_data({
                    **progress_data,
                    "ocr_pages_partial": pages_partial,
                })

            pages = pages_partial
            # Помечаем OCR как полностью завершённый
            await self._save_progress_data({
                **{k: v for k, v in progress_data.items() if k != "ocr_pages_partial"},
                "ocr_pages": pages,
            })

        # Страницы, где OCR упал в таймаут — их текст потерян, перечень по ним неполон.
        # Раньше это молча терялось; теперь предупреждаем явно (важно: неполная смета =
        # финансовый риск на тендере).
        timeout_pages = timed_out_page_numbers(pages)
        if timeout_pages:
            nums = ", ".join(str(n) for n in timeout_pages)
            await self.update_progress(
                f"⚠ Страницы {nums} не распознались (таймаут OCR) — перечень может быть неполным. "
                f"Проверьте эти страницы вручную или перезапустите задачу."
            )
            logger.warning(
                "OCR pages timed out — list may be incomplete",
                task_id=self.task_id,
                pages=timeout_pages,
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
                        accumulated_items = normalize_items(accumulated_items)
                        partial_excel = await asyncio.to_thread(generate_list,accumulated_items)
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
                        accumulated_items = normalize_items(accumulated_items)
                        partial_excel = await asyncio.to_thread(generate_list,accumulated_items)
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

        accumulated_items = normalize_items(accumulated_items)
        await self.update_progress(f"Найдено {len(accumulated_items)} позиций. Формирование Excel...")
        excel_data = await asyncio.to_thread(generate_list,accumulated_items)
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

        all_items = normalize_items(all_items)
        await self.update_progress(f"Проверено {len(all_items)} позиций. Формирование Excel...")
        excel_data = await asyncio.to_thread(generate_list,all_items, changes_summary=changes_summary)
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

        # Resume: восстанавливаем накопленные позиции и стадию из чекпоинта.
        progress_data = task.progress_data or {}
        pd_stage = progress_data.get("_stage")
        accumulated_items: list[dict] = list(progress_data.get("items", []))
        seen_names: set = set()
        for it in accumulated_items:
            seen_names.add((it.get("name", "").strip().lower(), it.get("type", "").strip()))

        if pd_stage == "pass1_done":
            # Проход 1 уже завершён ранее (пауза случилась в проходе 2) —
            # пропускаем дорогой проход 1 и идём сразу к уточнению объёмов.
            start_chunk = total_chunks
        else:
            start_chunk = int(progress_data.get("chunks_done", 0) or 0)

        for chunk_idx in range(start_chunk, total_chunks):
            chunk = chunks[chunk_idx]
            display = chunk_idx + 1
            if total_chunks > 1:
                await self.update_progress(
                    f"Обработка части {display} из {total_chunks}..."
                )

            prompt_pass1 = (
                chunk["text"] + "\n\n" + PROMPT_LIST_FROM_PROJECT
                if chunk["text"]
                else PROMPT_LIST_FROM_PROJECT
            )

            if total_chunks > 1:
                prompt_pass1 = (
                    f"ЧАСТЬ {display} ИЗ {total_chunks} ДОКУМЕНТА.\n\n"
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
            except InsufficientBalanceError:
                # Баланс исчерпан — на паузу. Чекпоинт после предыдущего чанка
                # уже сохранён, resume продолжит с необработанных частей PDF.
                raise
            except Exception as chunk_err:
                logger.warning(
                    "Project PDF chunk failed",
                    task_id=self.task_id,
                    chunk=display,
                    error=str(chunk_err),
                )
                if chunk_idx == 0:
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
                chunk=display,
                total=total_chunks,
                new_items=len(chunk_items),
                total_items=len(accumulated_items),
            )

            # Чекпоинт после каждого чанка прохода 1 — resume не пересчитывает
            # уже обработанные части PDF (устойчивость к паузе на балансе).
            await self._save_progress_data({
                "chunks_done": chunk_idx + 1,
                "total_chunks": total_chunks,
                "items": accumulated_items,
                "_stage": "pass1",
            })

        items = accumulated_items
        if not items:
            raise ValueError("Claude не вернул ни одной позиции. Проверьте содержимое PDF.")

        # Проход 1 завершён — фиксируем стадию, чтобы пауза в проходе 2 не
        # перезапускала дорогой проход 1 при возобновлении.
        if pd_stage != "pass1_done":
            await self._save_progress_data({
                "chunks_done": total_chunks,
                "total_chunks": total_chunks,
                "items": items,
                "_stage": "pass1_done",
            })

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
                except InsufficientBalanceError:
                    # Баланс исчерпан — на паузу. Уже уточнённые объёмы сохранены
                    # чекпоинтом ниже; resume пересчитает лишь оставшиеся null.
                    raise
                except Exception as pass2_err:
                    logger.warning(
                        "Pass2 failed, keeping original null items",
                        task_id=self.task_id,
                        error=str(pass2_err),
                    )

                # Чекпоинт прохода 2: сохраняем items с уже применёнными
                # объёмами. При resume заполненные позиции больше не null и
                # повторно не отправляются в Claude.
                await self._save_progress_data({
                    "chunks_done": total_chunks,
                    "total_chunks": total_chunks,
                    "items": items,
                    "_stage": "pass1_done",
                })

        resolved_count = sum(1 for i in null_indices if items[i].get("quantity") is not None)
        if null_indices:
            await self.update_progress(
                f"Объёмы уточнены: {resolved_count} из {len(null_indices)} заполнено. Формирование Excel..."
            )
        else:
            await self.update_progress(f"Найдено {len(items)} позиций. Формирование Excel...")

        items = normalize_items(items)
        await self._save_progress_data({"items": items})

        excel_data = await asyncio.to_thread(generate_list,items)
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

        all_items = normalize_items(all_items)
        await self.update_progress(f"Проверено {len(all_items)} позиций. Формирование Excel...")
        excel_data = await asyncio.to_thread(generate_list,all_items, changes_summary=changes_summary)
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

        Resume: если progress_data содержит _stage="pre_excel", шаги 0-2 пропускаются —
        данные восстанавливаются из чекпоинта и выполняется только шаг 3.
        """
        from datetime import date as _date

        # ── Resume: восстановление из чекпоинта ─────────────────────────────
        _progress = task.progress_data or {}
        if _progress.get("_stage") == "pre_excel":
            await self.update_progress("Возобновление: данные Claude восстановлены из чекпоинта. Формирование Excel...")
            _items_raw: list[dict] = _progress.get("items", [])
            _matched_raw: dict = _progress.get("matched", {})
            _claude_raw: dict = _progress.get("claude_results", {})
            # JSON serializes int dict keys as strings — restore them
            _matched_restored: dict[int, dict] = {int(k): v for k, v in _matched_raw.items()}
            _claude_restored: dict[int, dict] = {int(k): v for k, v in _claude_raw.items()}
            await self._run_estimate_step3(task, _items_raw, _matched_restored, _claude_restored)
            return

        # Resume (fast/sync): подхватить уже посчитанные Claude-позиции из
        # промежуточного чекпоинта. Захватываем ДО шагов 0-1, т.к. они могут
        # перезаписать progress_data. Шаг 2 продолжит только по необсчитанным.
        _resume_claude_results: dict[int, dict] = {}
        if _progress.get("_stage") == "claude_partial":
            _resume_claude_results = {int(k): v for k, v in (_progress.get("claude_results") or {}).items()}

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
                    # source_task IS the completeness check task — use it directly
                    if source_task.status != "completed":
                        raise ValueError("Задача проверки полноты не найдена или не завершена")
                    items = (source_task.progress_data or {}).get("items", [])
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

        # Списки позиций, не нашедшихся по exact-матчу — пойдут в батч-эмбеддинг.
        need_emb_works: list[tuple[int, str]] = []      # (gidx, name)
        need_emb_materials: list[tuple[int, str]] = []  # (gidx, name)
        enriched_map: dict[int, dict] = {}

        # ── Проход 1: точное совпадение (sync, in-memory) ────────────────────
        for gidx, item in enumerate(items):
            item_type = str(item.get("type", "")).strip()
            name = str(item.get("name", "")).strip()
            enriched = dict(item)
            enriched["_id"] = gidx
            enriched.setdefault("work_price", None)
            enriched.setdefault("material_price", None)
            enriched.setdefault("price_list_name", None)
            enriched.setdefault("sources", None)
            enriched_map[gidx] = enriched

            if item_type == "Работа":
                work_info = _price_svc._exact_match_work(name)
                if work_info is not None and work_info.get("min_price") is not None:
                    enriched["work_price"] = work_info.get("min_price")
                    enriched["price_list_name"] = "Прайс"
                    enriched["_price_source_name"] = work_info.get("name")
                    matched_by_gidx[gidx] = enriched
                    logger.debug("Item MATCHED in price list", task_id=self.task_id, name=name, method="exact", price_entry=work_info.get("name"))
                else:
                    need_emb_works.append((gidx, name))

            elif item_type == "Материал":
                mat_price = _price_svc._exact_match_material(name)
                if mat_price is not None:
                    enriched["material_price"] = mat_price
                    enriched["price_list_name"] = "Прайс"
                    enriched["_price_source_name"] = name
                    matched_by_gidx[gidx] = enriched
                    logger.debug("Material MATCHED in price list", task_id=self.task_id, name=name, method="exact")
                else:
                    need_emb_materials.append((gidx, name))

            else:
                # Неизвестный тип → сразу в unmatched (как и раньше)
                unmatched_by_gidx[gidx] = enriched

        # ── Проход 2: батч-эмбеддинг для работ (1 вызов Cohere) ─────────────
        if need_emb_works:
            work_names = [n for _, n in need_emb_works]
            work_results = await _price_svc.batch_embedding_match_works(work_names)
            for (gidx, name), work_info in zip(need_emb_works, work_results):
                enriched = enriched_map[gidx]
                if work_info is not None and work_info.get("min_price") is not None:
                    enriched["work_price"] = work_info.get("min_price")
                    enriched["price_list_name"] = "Прайс"
                    enriched["_price_source_name"] = work_info.get("name")
                    matched_by_gidx[gidx] = enriched
                    logger.debug("Item MATCHED in price list", task_id=self.task_id, name=name, method="embedding", price_entry=work_info.get("name"))
                else:
                    unmatched_by_gidx[gidx] = enriched
                    logger.debug("Item NOT matched in price list", task_id=self.task_id, name=name, work_info_found=(work_info is not None))

        # ── Проход 3: батч-эмбеддинг для материалов (1 вызов Cohere) ────────
        if need_emb_materials:
            mat_names = [n for _, n in need_emb_materials]
            mat_results = await _price_svc.batch_embedding_match_materials(mat_names)
            for (gidx, name), mat_price in zip(need_emb_materials, mat_results):
                enriched = enriched_map[gidx]
                if mat_price is not None:
                    enriched["material_price"] = mat_price
                    enriched["price_list_name"] = "Прайс"
                    enriched["_price_source_name"] = name
                    matched_by_gidx[gidx] = enriched
                    logger.debug("Material MATCHED in price list", task_id=self.task_id, name=name, method="embedding")
                else:
                    unmatched_by_gidx[gidx] = enriched
                    logger.debug("Material NOT matched in price list", task_id=self.task_id, name=name)

        n_matched = len(matched_by_gidx)
        n_unmatched = len(unmatched_by_gidx)
        # price_loaded — ключ к диагностике «прайс: 0 найдено»: пустой кэш в этом
        # процессе выглядит ровно как «в прайсе ничего нет», и без этого признака
        # причину не отличить (см. worker._warm_price_cache).
        price_loaded = _price_svc.is_cache_loaded()
        logger.info(
            "Price lookup done",
            task_id=self.task_id,
            matched=n_matched,
            unmatched=n_unmatched,
            price_loaded=price_loaded,
        )
        if not price_loaded:
            logger.warning(
                "Прайс не загружен в память — все цены пойдут через ИИ",
                task_id=self.task_id,
                items=len(items),
            )
        await self.update_progress(
            f"Прайс: найдено {n_matched}, не найдено {n_unmatched} из {len(items)} позиций."
        )

        # ── Проход 4: точное совпадение по price_cache ───────────────────────
        await self.update_progress(f"Поиск {n_unmatched} ненайденных позиций в кеше предыдущих задач...")
        need_cache_emb_works: list[tuple[int, str]] = []
        need_cache_emb_materials: list[tuple[int, str]] = []

        for gidx in list(unmatched_by_gidx.keys()):
            enriched = enriched_map[gidx]
            item_type = str(items[gidx].get("type", "")).strip()
            name = str(items[gidx].get("name", "")).strip()

            if item_type == "Работа":
                cache_work_info = _price_svc._exact_match_cache_work(name)
                if cache_work_info is not None and cache_work_info.get("price") is not None:
                    enriched["work_price"] = cache_work_info.get("price")
                    enriched["price_list_name"] = "Кеш"
                    _upd_at = cache_work_info.get("updated_at")
                    enriched["_cache_updated_at"] = _upd_at.isoformat() if hasattr(_upd_at, "isoformat") else _upd_at
                    enriched["sources"] = cache_work_info.get("sources")
                    matched_by_gidx[gidx] = enriched
                    del unmatched_by_gidx[gidx]
                    logger.debug("Item MATCHED in price cache", task_id=self.task_id, name=name, method="exact_cache")
                else:
                    need_cache_emb_works.append((gidx, name))

            elif item_type == "Материал":
                cache_mat_info = _price_svc._exact_match_cache_material(name)
                if cache_mat_info is not None:
                    enriched["material_price"] = cache_mat_info.get("price")
                    enriched["price_list_name"] = "Кеш"
                    _upd_at = cache_mat_info.get("updated_at")
                    enriched["_cache_updated_at"] = _upd_at.isoformat() if hasattr(_upd_at, "isoformat") else _upd_at
                    enriched["sources"] = cache_mat_info.get("sources")
                    matched_by_gidx[gidx] = enriched
                    del unmatched_by_gidx[gidx]
                    logger.debug("Material MATCHED in price cache", task_id=self.task_id, name=name, method="exact_cache")
                else:
                    need_cache_emb_materials.append((gidx, name))

        # ── Проход 5: батч-эмбеддинг для работ в price_cache ─────────────────
        if need_cache_emb_works:
            cache_work_names = [n for _, n in need_cache_emb_works]
            cache_work_results = await _price_svc.batch_embedding_match_cache_works(cache_work_names)
            for (gidx, name), cache_work_info in zip(need_cache_emb_works, cache_work_results):
                enriched = enriched_map[gidx]
                if cache_work_info is not None and cache_work_info.get("price") is not None:
                    enriched["work_price"] = cache_work_info.get("price")
                    enriched["price_list_name"] = "Кеш"
                    _upd_at = cache_work_info.get("updated_at")
                    enriched["_cache_updated_at"] = _upd_at.isoformat() if hasattr(_upd_at, "isoformat") else _upd_at
                    enriched["sources"] = cache_work_info.get("sources")
                    matched_by_gidx[gidx] = enriched
                    del unmatched_by_gidx[gidx]
                    logger.debug("Item MATCHED in price cache", task_id=self.task_id, name=name, method="embedding_cache", price_entry=cache_work_info.get("name"))

        # ── Проход 6: батч-эмбеддинг для материалов в price_cache ────────────
        if need_cache_emb_materials:
            cache_mat_names = [n for _, n in need_cache_emb_materials]
            cache_mat_results = await _price_svc.batch_embedding_match_cache_materials(cache_mat_names)
            for (gidx, name), cache_mat_price in zip(need_cache_emb_materials, cache_mat_results):
                enriched = enriched_map[gidx]
                if cache_mat_price is not None:
                    enriched["material_price"] = cache_mat_price.get("price")
                    enriched["price_list_name"] = "Кеш"
                    _upd_at = cache_mat_price.get("updated_at")
                    enriched["_cache_updated_at"] = _upd_at.isoformat() if hasattr(_upd_at, "isoformat") else _upd_at
                    enriched["sources"] = cache_mat_price.get("sources")
                    matched_by_gidx[gidx] = enriched
                    del unmatched_by_gidx[gidx]
                    logger.debug("Material MATCHED in price cache", task_id=self.task_id, name=name, method="embedding_cache")

        n_matched = len(matched_by_gidx)
        n_unmatched = len(unmatched_by_gidx)
        await self.update_progress(
            f"Кеш: найдено {n_matched}, не найдено {n_unmatched} из {len(items)} позиций."
        )

        # ── Шаг 2: Claude для ненайденных позиций ───────────────────────────
        # Results keyed by int _id (= global index), not by name string.
        # Seed из resume-чекпоинта: уже посчитанные позиции не пересчитываем.
        claude_results: dict[int, dict] = dict(_resume_claude_results)

        async def _fetch_chunk(chunk: list[dict], chunk_label: str) -> list[dict]:
            """Тонкая обёртка: та же оценка чанка, что и в доборе после batch."""
            return await self._fetch_price_chunk(chunk, current_date, chunk_label)

        async def _apply_chunk_items(result_items: list[dict]) -> None:
            """Последовательно (self.db): заполнить claude_results и сохранить цены в кеш."""
            for result_item in result_items:
                item_id = result_item.get("id")
                if item_id is not None:
                    claude_results[int(item_id)] = result_item
                    await self._cache_priced_item(result_item)

        async def _process_chunks(
            chunk_list: list[list[dict]],
            label_prefix: str,
            concurrency: int,
            progress_label: Optional[str] = None,
            progress_offset: int = 0,
            progress_total: Optional[int] = None,
        ) -> None:
            """fast → параллельно (Semaphore) с общим cancel-watcher; иначе последовательно.
            Fetch (Claude) параллельно, применение результатов (self.db) — барьером после.

            Упавший чанк (баланс/таймаут/отмена) НЕ отменяет остальные: их ответы уже
            оплачены Anthropic, поэтому применяем их и сохраняем чекпоинт, и только
            потом падаем. Иначе пауза по балансу обнуляла до ESTIMATE_MAIN_CHECKPOINT_GROUP
            оплаченных чанков, и после пополнения они оплачивались повторно.
            """
            total = len(chunk_list)
            workers = [
                (lambda c=c, k=k: _fetch_chunk(c, f"{label_prefix}{k + 1}/{total}"))
                for k, c in enumerate(chunk_list)
            ]
            results = await self._run_chunks_parallel(
                workers, concurrency=concurrency, return_exceptions=True,
                progress_label=progress_label,
                progress_offset=progress_offset,
                progress_total=progress_total,
                deadline_s=_chunk_stage_deadline(total, concurrency),
            )
            first_error: Optional[BaseException] = None
            applied = 0
            for chunk_result in results:
                if isinstance(chunk_result, BaseException):
                    if first_error is None:
                        first_error = chunk_result
                    continue
                await _apply_chunk_items(chunk_result)
                applied += 1
            if first_error is not None:
                if applied:
                    await self._save_claude_partial(items, matched_by_gidx, claude_results)
                    logger.info(
                        "Saved partial results before chunk failure",
                        task_id=self.task_id,
                        applied_chunks=applied,
                        failed_chunks=len(results) - applied,
                        error=str(first_error),
                    )
                if isinstance(first_error, asyncio.CancelledError):
                    raise TaskCancelledError("Задача остановлена пользователем")
                raise first_error

        if unmatched_by_gidx:
            unmatched_list = list(unmatched_by_gidx.values())
            current_date = _date.today().strftime("%d.%m.%Y")
            chunks = _chunk_by_work_boundaries(unmatched_list, max_chunk_size=10)
            total_chunks = len(chunks)

            mode = getattr(task, "processing_mode", "fast")
            if mode == "batch":
                # Долгий режим: отправить пачку и выйти; смету достроит поллер (Phase 5).
                await self._submit_estimate_batch(
                    task, items, matched_by_gidx, unmatched_by_gidx, current_date, chunks
                )
                return

            await self.update_progress(
                f"Прайс: {n_matched} позиций найдено, {n_unmatched} — нет. "
                f"Отправляем {total_chunks} чанк(а) в Claude..."
            )

            concurrency = FAST_CHUNK_CONCURRENCY if mode == "fast" else 1
            # Главный проход группами: после каждой группы — промежуточный
            # чекпоинт claude_partial (устойчивость к паузе на балансе).
            # Пропускаем позиции, уже посчитанные в предыдущем запуске (resume).
            pending = self._pending_chunks(chunks, set(claude_results.keys()))
            for _gi in range(0, len(pending), ESTIMATE_MAIN_CHECKPOINT_GROUP):
                group = pending[_gi:_gi + ESTIMATE_MAIN_CHECKPOINT_GROUP]
                await self._check_cancelled()
                await _process_chunks(
                    group, label_prefix="", concurrency=concurrency,
                    # Счёт сквозной по всей задаче: группы — деталь реализации
                    # (чекпоинт каждые 8 чанков), пользователю о них знать нечего.
                    progress_label="Расчёт цен: готово {done} из {total} частей...",
                    progress_offset=_gi,
                    progress_total=len(pending),
                )
                await self._save_claude_partial(items, matched_by_gidx, claude_results)

            # Один добор вместо двух проходов: пропущенные Claude и вернувшиеся с
            # нулевой ценой — одна и та же проблема «цены нет». Раньше это были
            # два отдельных прохода чанками по 5, то есть вдвое больше запросов и
            # web-поисков; каждая позиция по-прежнему получает ровно одну
            # дополнительную попытку.
            problem_ids = self._ids_without_price(unmatched_by_gidx, claude_results)
            if problem_ids:
                await self.update_progress(
                    f"Повторная обработка {len(problem_ids)} позиций без цены "
                    f"(батчи по {ESTIMATE_RETRY_CHUNK})..."
                )
                problem_items = [unmatched_by_gidx[gidx] for gidx in problem_ids]
                retry_chunks = [
                    problem_items[i:i + ESTIMATE_RETRY_CHUNK]
                    for i in range(0, len(problem_items), ESTIMATE_RETRY_CHUNK)
                ]
                await self._check_cancelled()
                await _process_chunks(
                    retry_chunks, label_prefix="retry-", concurrency=concurrency,
                    progress_label="Повторный расчёт: готово {done} из {total} частей...",
                )

            still_without_price = self._ids_without_price(unmatched_by_gidx, claude_results)
            if still_without_price:
                logger.warning(
                    "Some items remain unpriced after retry",
                    task_id=self.task_id,
                    count=len(still_without_price),
                    names=[unmatched_by_gidx[g].get("name") for g in still_without_price],
                )

        # ── Чекпоинт: сохранить данные перед генерацией Excel ──────────────
        # Используем независимую сессию — основная сессия может быть в нестабильном состоянии
        # после долгих Claude-вызовов.  При зависании на шаге 3 пользователь может
        # остановить задачу и продолжить с этого чекпоинта.
        try:
            from app.database import AsyncSessionLocal as _ASL
            _checkpoint = TaskProcessor._json_safe({
                "_stage": "pre_excel",
                "items": items,
                "matched": {str(k): v for k, v in matched_by_gidx.items()},
                "claude_results": {str(k): v for k, v in claude_results.items()},
            })
            async with _ASL() as _cp_db:
                from sqlalchemy import update as _upd
                await _cp_db.execute(
                    _upd(Task).where(Task.id == self.task_id).values(progress_data=_checkpoint)
                )
                await _cp_db.commit()
            logger.info("Checkpoint saved before Excel generation", task_id=self.task_id)
        except Exception as _cp_err:
            logger.warning("Failed to save pre_excel checkpoint", task_id=self.task_id, error=str(_cp_err))

        await self._run_estimate_step3(task, items, matched_by_gidx, claude_results)

    async def _run_estimate_step3(
        self,
        task: Task,
        items: list[dict],
        matched_by_gidx: dict,
        claude_results: dict,
    ) -> None:
        """Шаг 3: сборка итогового Excel из уже полученных данных."""
        # ── Шаг 3: Сборка итогового результата в исходном порядке ───────────

        def _fmt_cache_date(updated_at) -> str:
            if updated_at is None:
                return ""
            try:
                from datetime import datetime as _dt
                if isinstance(updated_at, str):
                    updated_at = _dt.fromisoformat(updated_at)
                return updated_at.strftime("%d.%m.%Y")
            except Exception:
                return str(updated_at)

        final_items: list[dict] = []
        for gidx, item in enumerate(items):
            if gidx in matched_by_gidx:
                matched = matched_by_gidx[gidx]
                source = matched.get("price_list_name", "")
                if source == "Прайс":
                    matched["notes"] = matched.get("_price_source_name", "")
                    matched["sources"] = ""
                elif source == "Кеш":
                    cache_date = _fmt_cache_date(matched.get("_cache_updated_at"))
                    cache_sources = matched.get("sources") or ""
                    parts = []
                    if cache_date:
                        parts.append(f"от {cache_date}")
                    if cache_sources:
                        parts.append(cache_sources)
                    matched["notes"] = ", ".join(parts)
                    matched["sources"] = ""
                final_items.append(matched)
                continue
            cr = claude_results.get(gidx)
            if cr:
                # Цены от ИИ приводим здесь, а не только при выводе: иначе
                # непригодное значение уезжает в чекпоинт pre_excel, и
                # возобновление читает его снова. Отбракованная цена = позиция
                # без цены, что видно человеку и правится руками.
                _wp = coerce_price(cr.get("work_price"))
                _mp = coerce_price(cr.get("material_price"))
                _ai_notes = cr.get("sources", "") or cr.get("notes", "")
                if cr.get("work_price") is not None and _wp is None:
                    _ai_notes = (_ai_notes + "; " if _ai_notes else "") + \
                        f"ИИ вернул непригодную цену работ ({cr.get('work_price')!r}) — отброшена"
                if cr.get("material_price") is not None and _mp is None:
                    _ai_notes = (_ai_notes + "; " if _ai_notes else "") + \
                        f"ИИ вернул непригодную цену материала ({cr.get('material_price')!r}) — отброшена"
                enriched = {
                    "type": item.get("type", ""),
                    "name": str(item.get("name", "")).strip(),
                    "unit": cr.get("unit") or item.get("unit", ""),
                    "quantity": item.get("quantity"),
                    "work_price": _wp,
                    "material_price": _mp,
                    "price_list_name": "Интернет",
                    "sources": "",
                    "notes": _ai_notes,
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
            claude_priced=len(claude_results),
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

    async def _enrich_rows_with_gesn_norms(self, rows: list[dict]) -> list[dict]:
        """Enrich parsed estimate rows with GESN norms via Claude API.

        Sends work+material pairs to Claude in chunks of 25, gets back
        qty_per_work_unit and norm_reference for each material row.
        On Claude errors the rows are returned without norms — import is not blocked.
        """
        # Only process rows that have materials linked to works
        has_linked_materials = any(
            r.get("type") == "material" and r.get("work_row_id")
            for r in rows
        )
        if not has_linked_materials:
            return rows

        rows_by_id = {r["id"]: r for r in rows}

        # Chunk by work boundaries using "work" type (distinct from LIST_FROM_GRAND "Работа")
        chunks: list[list[dict]] = []
        current_chunk: list[dict] = []
        for row in rows:
            if row.get("type") == "work" and current_chunk and len(current_chunk) >= 25:
                chunks.append(current_chunk)
                current_chunk = []
            current_chunk.append(row)
        if current_chunk:
            chunks.append(current_chunk)

        for chunk in chunks:
            chunk_json = json.dumps({"items": chunk}, ensure_ascii=False, indent=2)
            messages = [{"role": "user", "content": f"{chunk_json}\n\n{PROMPT_ENRICH_NORMS}"}]
            try:
                data = await self._interruptible_claude_json_with_retry(
                    messages, system_prompt=SYSTEM_BASE, processing_timeout=120.0
                )
            except Exception:
                # Non-fatal: rows stay without norms, import continues
                continue

            for item in data.get("materials", []):
                row = rows_by_id.get(item.get("row_id"))
                if row is not None and item.get("qty_per_work_unit") is not None:
                    row["qty_per_work_unit"] = item["qty_per_work_unit"]
                    row["norm_reference"] = item.get("norm_reference")

        return rows

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
        await self.update_progress("Определяем нормативы ГЭСН для материалов...")
        rows = await self._enrich_rows_with_gesn_norms(rows)

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
                    await self.update_progress("Определяем нормативы ГЭСН для сметы заказчика...")
                    client_rows = await self._enrich_rows_with_gesn_norms(client_rows)
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

        # Set estimation_status = optimized — ESTIMATE_OPTIMIZATION manages its own status
        task_res2 = await self.db.execute(select(Task).where(Task.id == self.task_id))
        task2 = task_res2.scalar_one_or_none()
        if task2:
            task2.estimation_status = "optimized"
            task2.updated_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.update_progress("Смета загружена. Редактор готов к работе.")


async def process_task(
    task_id: str,
    db: AsyncSession,
    job_id: Optional[int] = None,
    job_attempt: Optional[int] = None,
) -> None:
    """Wrapper function for backward compatibility with routers.

    `job_id` + `job_attempt` — какой именно прогон идёт (передаёт worker). По ним
    прогон понимает, что его сменили — перезапуском, деплоем или reclaim'ом — и не
    считает параллельно новому.
    """
    processor = TaskProcessor(task_id, db, job_id=job_id, job_attempt=job_attempt)
    await processor.process()


async def fix_empty_prices_background(task_id: str, session_factory) -> None:
    """Background runner: open own DB session, fix empty prices, save results."""
    async with session_factory() as db:
        processor = TaskProcessor(task_id, db)
        await processor.fix_empty_prices()


class _FixEmptyResult:
    def __init__(self, fixed: int, still_empty: int, grand_total: float):
        self.fixed = fixed
        self.still_empty = still_empty
        self.grand_total = grand_total


# Attach fix_empty_prices to TaskProcessor
async def _fix_empty_prices(self: "TaskProcessor") -> None:
    """Find items with empty prices, send to Claude, merge back, regen xlsx."""
    from datetime import date as _date
    from decimal import Decimal as _Decimal
    from app.utils.xlsx_exporter import generate_estimate_xlsx

    task_res = await self.db.execute(select(Task).where(Task.id == self.task_id))
    task = task_res.scalar_one_or_none()
    if not task:
        return

    items: list[dict] = (task.progress_data or {}).get("items", [])
    if not items:
        task.status = "completed"
        task.progress_message = None
        task.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return

    def _has_empty_price(item: dict) -> bool:
        if item.get("type") == "Работа":
            return not item.get("work_price")
        if item.get("type") == "Материал":
            return not item.get("material_price")
        return False

    empty_indices = [i for i, it in enumerate(items) if _has_empty_price(it)]
    if not empty_indices:
        task.status = "completed"
        task.progress_message = None
        task.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return

    current_date = _date.today().strftime("%d.%m.%Y")
    total_empty = len(empty_indices)
    fixed_count = 0

    # Тот же размер, что и в доборе сметы: мелкий батч заново запускает полный
    # набор платных web-поисков. Обрезка ответа не страшна — батч дробится пополам.
    batches = [
        empty_indices[i:i + ESTIMATE_RETRY_CHUNK]
        for i in range(0, len(empty_indices), ESTIMATE_RETRY_CHUNK)
    ]

    async def _fetch_batch(batch: list[int], label: str) -> list[dict]:
        """DB-free: отправить батч пустых цен в Claude, вернуть result-items ([] при ошибке)."""
        batch_items = [
            {
                "id": idx,
                "type": items[idx].get("type", ""),
                "name": items[idx].get("name", ""),
                "unit": items[idx].get("unit", ""),
                "quantity": items[idx].get("quantity"),
            }
            for idx in batch
        ]
        unmatched_json = json.dumps(batch_items, ensure_ascii=False, indent=2)
        prompt_text = PROMPT_ESTIMATE_FROM_LIST.format(
            current_date=current_date,
            unmatched_items_json=unmatched_json,
        )
        messages = [{"role": "user", "content": prompt_text}]
        try:
            data = await self._call_claude_json_with_retry(
                messages,
                system_prompt=SYSTEM_BASE,
                use_web_search=True,
                processing_timeout=1200.0,
            )
        except (TaskCancelledError, asyncio.TimeoutError):
            raise
        except InsufficientBalanceError:
            # Баланс исчерпан — ретраи не помогут. Раньше эта ошибка попадала в
            # общий except ниже, батч молча терялся и задача завершалась с
            # пустыми ценами вместо паузы. Пробрасываем на паузу, как в основном
            # проходе сметы (_fetch_chunk).
            raise
        except ResponseTruncatedError:
            # Ответ не поместился — режем батч пополам вместо бессмысленного
            # повтора того же запроса (тот же приём, что в _fetch_chunk).
            if len(batch) < 2:
                logger.warning(
                    "Single item response truncated in fix_empty_prices, skipping",
                    task_id=self.task_id, batch=label,
                )
                return []
            mid = len(batch) // 2
            logger.warning(
                "fix_empty_prices batch truncated, splitting in half",
                task_id=self.task_id, batch=label, size=len(batch),
            )
            return await _fetch_batch(batch[:mid], f"{label}a") + await _fetch_batch(
                batch[mid:], f"{label}b"
            )
        except Exception as e:
            logger.warning(
                "fix_empty_prices batch failed, skipping",
                task_id=self.task_id,
                batch=label,
                error=str(e),
            )
            return []
        return data.get("items", [])

    mode = getattr(task, "processing_mode", "fast")
    concurrency = FAST_CHUNK_CONCURRENCY if mode == "fast" else 1
    await self.update_progress(f"Исправление пустых цен: {len(batches)} батч(ей)...")
    await self._check_cancelled()
    workers = [
        (lambda b=b, k=k: _fetch_batch(b, f"{k + 1}/{len(batches)}"))
        for k, b in enumerate(batches)
    ]
    all_results = await self._run_chunks_parallel(
        workers, concurrency=concurrency, return_exceptions=True,
        progress_label="Исправление пустых цен: готово {done} из {total} батчей...",
        deadline_s=_chunk_stage_deadline(len(batches), concurrency),
    )

    # Применяем результаты последовательно (мутация items / fixed_count).
    empty_set = set(empty_indices)
    first_error: Optional[BaseException] = None
    for result_items in all_results:
        if isinstance(result_items, BaseException):
            if first_error is None:
                first_error = result_items
            continue
        for result_item in result_items:
            raw_id = result_item.get("id")
            try:
                orig_idx = int(raw_id)
            except (TypeError, ValueError):
                continue
            if orig_idx not in empty_set:
                continue
            orig = items[orig_idx]
            wp = result_item.get("work_price")
            mp = result_item.get("material_price")
            if orig.get("type") == "Работа" and wp:
                items[orig_idx] = {**orig, "work_price": wp, "sources": result_item.get("sources", orig.get("sources", "")), "notes": result_item.get("notes", orig.get("notes", ""))}
                fixed_count += 1
            elif orig.get("type") == "Материал" and mp:
                items[orig_idx] = {**orig, "material_price": mp, "sources": result_item.get("sources", orig.get("sources", "")), "notes": result_item.get("notes", orig.get("notes", ""))}
                fixed_count += 1

    if first_error is not None:
        # Успевшие батчи уже оплачены Anthropic — фиксируем найденные цены до
        # падения, иначе перезапуск после паузы по балансу отправит те же
        # позиции в Claude заново (они снова окажутся «пустыми»).
        if fixed_count:
            from sqlalchemy.orm.attributes import flag_modified
            task.progress_data = {**(task.progress_data or {}), "items": items}
            flag_modified(task, "progress_data")
            await self.db.commit()
            logger.info(
                "Saved fixed prices before batch failure",
                task_id=self.task_id,
                fixed=fixed_count,
                error=str(first_error),
            )
        if isinstance(first_error, asyncio.CancelledError):
            raise TaskCancelledError("Задача остановлена пользователем")
        raise first_error

    await self.update_progress(
        f"Исправлено {fixed_count} из {total_empty} пустых цен. Пересчёт сметы..."
    )

    # Regenerate xlsx and update cost
    excel_data, grand_total = generate_estimate_xlsx(items)

    existing_r = await self.db.execute(
        select(TaskResult).where(TaskResult.task_id == self.task_id, TaskResult.slot == "estimate")
    )
    old_result = existing_r.scalar_one_or_none()
    est_key = await storage_service.store_result_file(
        self.task_id, "estimate", "Смета_из_перечня.xlsx", _XLSX_MIME, excel_data
    )
    if old_result:
        old_result.storage_key = est_key
        old_result.size_bytes = len(excel_data)
    else:
        self.db.add(TaskResult(
            task_id=self.task_id,
            file_name="Смета_из_перечня.xlsx",
            mime_type=_XLSX_MIME,
            storage_key=est_key,
            size_bytes=len(excel_data),
            slot="estimate",
        ))

    task_res2 = await self.db.execute(select(Task).where(Task.id == self.task_id))
    task2 = task_res2.scalar_one_or_none()
    if task2:
        if task2.status == "cancelled":
            return
        from sqlalchemy.orm.attributes import flag_modified
        task2.cost = _Decimal(str(round(grand_total, 2)))
        task2.estimation_status = "estimated"
        task2.status = "completed"
        task2.progress_message = None
        task2.progress_data = {**(task2.progress_data or {}), "items": items}
        flag_modified(task2, "progress_data")
        task2.updated_at = datetime.now(timezone.utc)
    await self.db.commit()

    logger.info(
        "fix_empty_prices completed",
        task_id=self.task_id,
        fixed=fixed_count,
        total_empty=total_empty,
        grand_total=grand_total,
    )


# Attach as method
TaskProcessor.fix_empty_prices = _fix_empty_prices
