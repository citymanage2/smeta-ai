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
from app.constants import ESTIMATE_TASK_TYPES
from app.utils.xlsx_cost_parser import extract_total_cost
from app.services.excel_service import generate_list, generate_list_project, generate_smeta, generate_smeta_from_tz_project, generate_smeta_from_project, generate_smeta_detailed, generate_scan_result
from app.services.pdf_service import generate_comparison_report, generate_text_pdf
from app.utils.file_parser import parse_file
from app.utils.json_utils import extract_json

logger = structlog.get_logger()

# ---- System prompts / task prompts ----

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

PROMPT_LIST_FROM_TZ = """Ты — опытный инженер-сметчик со знанием нормативной базы РФ (ГЭСН-2017/ФСНБ-2022, ФЕР/ТЕР по Свердловской области, СП, ГОСТ).

Задача: проанализировать техническое задание и составить полный нормативный перечень работ и материалов.

ПОРЯДОК СТРОК В ПЕРЕЧНЕ — строго соблюдать:
Работа 1
  Материал 1 к Работе 1
  Материал 2 к Работе 1
  ...
Работа 2
  Материал 1 к Работе 2
  Материал 2 к Работе 2
  ...

Каждый вид работы должен идти ПЕРВОЙ строкой, затем сразу все материалы к этой работе.

ТРЕБОВАНИЯ К МАТЕРИАЛАМ:
1. Для каждого вида работы определи полный перечень материалов по нормативной базе:
   - ГЭСН / ФСНБ-2022 — основной источник норм расхода материалов
   - ФЕР/ТЕР Свердловской области — для региональной специфики
   - Технические части сборников ГЭСН — что включено в норму, что учитывается отдельно
   - СП и ГОСТ — для нестандартных решений

2. Один материал может фигурировать в ТЗ одной строкой с суммарным объёмом на несколько видов работ. В этом случае: раздели объём между работами согласно нормам ГЭСН, каждый вид работы получает свою строку материала с соответствующим объёмом.

3. Если в ТЗ указан материал, но не указан объём — рассчитай объём по нормам ГЭСН исходя из объёма работ.

4. Если в ТЗ отсутствует материал, который нормативно необходим для данного вида работ — добавь его с пометкой в примечании.

ФИКСАЦИЯ ИЗМЕНЕНИЙ:
- В поле notes для каждой изменённой позиции указывай:
  * "Добавлено по ГЭСН XX-XX-XXX: [обоснование]"
  * "Объём скорректирован: в ТЗ [X] [ед], распределено между работами по норме ГЭСН [норма]"
  * "Наименование уточнено: в ТЗ '[исходное]', скорректировано на '[новое]' согласно [норматив]"

ПОЯСНИТЕЛЬНЫЙ ТЕКСТ:
После формирования перечня добавь поле "changes_summary" — текст с обоснованием всех изменений по сравнению с ТЗ:
- Что добавлено и почему (ссылка на норматив)
- Что скорректировано по объёмам и почему
- Что разбито на несколько позиций и почему
- Если изменений нет — написать "Перечень соответствует ТЗ, дополнений не требуется"

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
  "changes_summary": "Пояснительный текст обо всех изменениях по сравнению с ТЗ"
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }."""

PROMPT_LIST_FROM_TZ_PROJECT = """Ты — опытный инженер-сметчик со знанием нормативной базы РФ (ГЭСН-2017/ФСНБ-2022, ФЕР/ТЕР по Свердловской области, СП, ГОСТ).

Задача: проанализировать ТЗ и проектную документацию, провести их сравнение, составить полный нормативный перечень работ и материалов.

ПОРЯДОК СТРОК В ПЕРЕЧНЕ — строго по структуре проекта:
Работа 1 (в порядке как в проекте)
  Материал 1 к Работе 1
  Материал 2 к Работе 1
  ...
Работа 2
  Материал 1 к Работе 2
  ...

ЭТАП 1 — СРАВНЕНИЕ ТЗ И ПРОЕКТА:
Проведи полное тщательное сравнение ТЗ с проектом. Для каждого отличия зафикси:
- Работы/материалы, которые есть в ТЗ, но отсутствуют в проекте
- Работы/материалы, которые есть в проекте, но отсутствуют в ТЗ
- Расхождения в объёмах (ТЗ указывает один объём, проект — другой)
- Расхождения в марках, типах, характеристиках материалов
- Риски выявленных различий (финансовые, технические, юридические)
- Необходимые действия: что нужно уточнить в ТЗ, что скорректировать в проекте

ЭТАП 2 — ФОРМИРОВАНИЕ ПЕРЕЧНЯ:
За основу бери проектную документацию как более детальный источник.
Дополняй данными из ТЗ при необходимости.

Для каждого вида работы определи полный перечень материалов по нормативной базе:
- ГЭСН / ФСНБ-2022 — нормы расхода материалов
- ФЕР/ТЕР Свердловской области — региональная специфика
- Технические части сборников ГЭСН — что включено в норму, что отдельно
- СП и ГОСТ — для нестандартных решений

Один материал может фигурировать в ТЗ/проекте одной строкой с суммарным объёмом на несколько видов работ. В этом случае раздели объём между работами согласно нормам ГЭСН.

ФИКСАЦИЯ ИЗМЕНЕНИЙ в поле notes:
- "Добавлено по ГЭСН XX-XX-XXX: [обоснование]"
- "Объём по проекту [X], в ТЗ [Y], принят по проекту / принято среднее / требует уточнения"
- "Есть в ТЗ, отсутствует в проекте: включено с пометкой — требует согласования"
- "Объём скорректирован: суммарный объём из ТЗ/проекта распределён между работами по норме ГЭСН"

ПОЯСНИТЕЛЬНЫЙ ТЕКСТ (поле changes_summary):
Раздел 1 — Сравнение ТЗ и проекта:
  - Полный список всех выявленных расхождений
  - Риски каждого расхождения
  - Рекомендуемые действия по каждому расхождению

Раздел 2 — Изменения по сравнению с исходными документами:
  - Что добавлено нормативно и почему
  - Что скорректировано по объёмам и почему
  - Что разбито на несколько позиций и почему
  - Если изменений нет — "Перечень соответствует документации, дополнений не требуется"

Верни результат СТРОГО в формате JSON, без markdown блоков, без preamble текста, первый символ {, последний }:
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "section": "Раздел проекта",
      "notes": "Примечание / обоснование изменения"
    }
  ],
  "changes_summary": "Пояснительный текст: Раздел 1 — сравнение ТЗ и проекта, Раздел 2 — изменения по нормативной базе"
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }."""

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

PROMPT_RESEARCH_PROJECT = """Ты профессиональный инженер-сметчик в строительной сфере.

Проведи проверку проектной документации по следующему плану и зафикси результаты.

1. ОБЩАЯ РЕВИЗИЯ ПАКЕТА ДОКУМЕНТОВ
Проверь наличие: задание на проектирование или ТЗ, заключение экспертизы, пояснительная записка (ПЗ), рабочая документация по разделам (АР, КР/КЖ, ОВ, ВК, ЭО, СС, ТХ), ведомость объёмов работ (ВОР), спецификации оборудования и материалов, генплан, геологический отчёт (ИГИ), сметное задание.
Зафикси что присутствует, что отсутствует.

2. АНАЛИЗ ПОЯСНИТЕЛЬНОЙ ЗАПИСКИ И ОБЩИХ ДАННЫХ
Извлеки: класс функциональной пожарной опасности, климатический район, сейсмика, нагрузки снег/ветер, уровень грунтовых вод (УГВ), категория грунта, наличие стеснённых условий, этапы строительства.
Зафикси риски: устаревшая ПЗ, отсутствие ссылок на нормативы, неописанные условия производства работ.

3. АНАЛИЗ АРХИТЕКТУРНО-СТРОИТЕЛЬНЫХ ЧЕРТЕЖЕЙ (АР + КЖ/КМ)
Проверь: соответствие отметок на планах и разрезах, комплектность чертежей, спецификации к чертежам, марки и конструктивные решения, проёмы (размеры и количество), лестницы/пандусы, наружные работы (отмостка, крыльца, козырьки), узлы примыканий кровли, гидроизоляция, утепление.
Контрольный пересчёт: площадь пола, объём земляных работ, объём бетона, площадь кладки, площадь кровли, площадь фасадных работ, площадь внутренней отделки.
Зафикси расхождения объёмов ВОР и чертежей (расхождение > 5% — критично).

4. АНАЛИЗ ИНЖЕНЕРНЫХ РАЗДЕЛОВ (ОВ, ВК, ЭО, СС, ТХ)
По каждому разделу проверь: спецификацию оборудования, схемы, длины трасс, типы труб/кабелей.
Типичные ошибки ВОР: нет изоляции труб, не учтены испытания систем, занижены длины кабелей, нет заземления, отсутствуют марки оборудования в СС.
Зафикси разграничение поставки: что в смете ГП, что — заказчика.

5. АНАЛИЗ ВЕДОМОСТИ ОБЪЁМОВ РАБОТ (ВОР)
Структурная проверка: все разделы представлены, единицы измерения соответствуют ГЭСН, нет нулевых объёмов, нет дублей.
Часто пропускаемое: вывоз мусора, временные здания и сооружения (гл.8 ССР), зимнее удорожание (гл.9 ССР), монтаж/демонтаж лесов (ГЭСН 08-07), водоотлив, уплотнение обратной засыпки, перемычки над проёмами, антикоррозионная обработка, испытания и промывки систем, ПНР.

6. ПРОВЕРКА СПЕЦИФИКАЦИЙ НА МАТЕРИАЛЫ И ОБОРУДОВАНИЕ
Проверь: указаны ли марки и типоразмеры, класс бетона, марка стали/арматуры, плотность утеплителя, профиль окон/дверей, артикулы оборудования ОВ/ВК, наличие аналогов.
Риски: материал без марки (разброс цен 2-5 раз), спецификация не совпадает с ВОР.

7. ОЦЕНКА УСЛОВИЙ ПРОИЗВОДСТВА РАБОТ
Выяви применимые коэффициенты: стеснённые условия (МДС 81-35.2004, до 1,35), зимнее удорожание (ГСН 81-05-02-2007), высотные работы, подземные работы/водоотлив, работа в действующем цехе (до 1,5).

8. ИТОГОВЫЙ ПРОТОКОЛ ЗАМЕЧАНИЙ
Таблица: Раздел ПД | Описание замечания | Запрашиваемое уточнение | Критичность (высокая/средняя/низкая)
Реестр допущений: позиции где данных нет и принято допущение.

Верни результат в виде структурированного текста на русском языке.
Это вспомогательный анализ — он будет использован на следующем этапе для составления перечня работ и материалов."""

PROMPT_LIST_FROM_PROJECT = """Ты — опытный инженер-сметчик со знанием нормативной базы РФ (ГЭСН-2017/ФСНБ-2022, ФЕР/ТЕР по Свердловской области, СП, ГОСТ).

Задача: на основе проведённой проверки проекта и проектной документации составить полный нормативный перечень работ и материалов.

Результаты проверки проекта:
{research_result}

ПОРЯДОК СТРОК В ПЕРЕЧНЕ — строго по структуре проекта:
Работа 1 (в порядке как в проекте)
  Материал 1 к Работе 1
  Материал 2 к Работе 1
  ...
Работа 2
  Материал 1 к Работе 2
  ...

ЭТАП 1 — ФОРМИРОВАНИЕ ПЕРЕЧНЯ:
Для каждого вида работы определи полный перечень материалов по нормативной базе:
- ГЭСН / ФСНБ-2022 — нормы расхода материалов
- ФЕР/ТЕР Свердловской области — региональная специфика
- Технические части сборников ГЭСН — что включено в норму, что отдельно
- СП и ГОСТ — для нестандартных решений

Один материал может фигурировать в проекте одной строкой с суммарным объёмом на несколько видов работ. В этом случае раздели объём между работами согласно нормам ГЭСН.

ФИКСАЦИЯ ИЗМЕНЕНИЙ в поле notes:
- "Добавлено по ГЭСН XX-XX-XXX: [обоснование]"
- "Объём скорректирован: суммарный объём из проекта распределён между работами по норме ГЭСН"
- "Замечание из проверки: [суть]"

ПОЯСНИТЕЛЬНЫЙ ТЕКСТ (поле changes_summary):
Раздел 1 — Ключевые замечания к проекту (из проверки):
  - Критичные замечания, требующие уточнения до начала работ
  - Риски выявленных несоответствий
Раздел 2 — Изменения перечня по сравнению с проектом:
  - Что добавлено нормативно и почему
  - Что скорректировано по объёмам и почему
  - Если изменений нет — "Перечень соответствует документации, дополнений не требуется"

Верни результат СТРОГО в формате JSON, без markdown блоков, без preamble текста, первый символ {, последний }:
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "section": "Раздел проекта",
      "notes": "Примечание / обоснование изменения"
    }
  ],
  "changes_summary": "Пояснительный текст: Раздел 1 — замечания к проекту, Раздел 2 — изменения перечня"
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }."""

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


SMETA_BATCH_SIZE = 5            # items per Claude call for SMETA_FROM_LIST
SMETA_BATCH_TIMEOUT_SECS = 180  # processing_timeout passed to each main-batch call
SMETA_INTER_BATCH_DELAY = 4     # seconds to sleep between main batches

SMETA_RETRY_BATCH_SIZE = 2      # items per Claude call in the retry queue
SMETA_RETRY_TIMEOUT_SECS = 600  # processing_timeout for retry-queue calls
SMETA_RETRY_INTER_BATCH_DELAY = 30  # seconds to sleep between retry batches


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
                await self._handle_list_from_tz_project(task)
            elif task_type == "SMETA_FROM_LIST":
                await self._handle_smeta_from_list(task)
            elif task_type == "SMETA_FROM_TZ":
                await self._handle_smeta(task, PROMPT_SMETA_FROM_TZ)
            elif task_type == "SMETA_FROM_TZ_PROJECT":
                await self._handle_smeta_from_tz_project(task)
            elif task_type == "SCAN_TO_EXCEL":
                await self._handle_scan_to_excel(task)
            elif task_type == "COMPARE_PROJECT_SMETA":
                await self._handle_compare(task)
            elif task_type == "RESEARCH_PROJECT":
                await self._handle_research_project(task)
            elif task_type == "LIST_FROM_PROJECT":
                await self._handle_list_from_project(task)
            elif task_type == "SMETA_FROM_PROJECT":
                await self._handle_smeta_from_project(task)
            elif task_type == "SMETA_FROM_EDC_PROJECT":
                await self._handle_smeta_from_edc(task)
            elif task_type == "SMETA_FROM_GRAND_PROJECT":
                await self._handle_smeta_from_grand(task)
            elif task_type == "OPTIMIZE_SMETA":
                await self._handle_optimize_smeta(task)
            else:
                raise ValueError(f"Неизвестный тип задачи: {task.task_type}")

            await self.update_status("completed")
            await self._auto_fill_estimate_slot()
            await self.update_progress("Задача успешно выполнена")

        except TaskCancelledError:
            logger.info("Task was cancelled by user", task_id=self.task_id)
            # Status already set to 'cancelled' by the cancel endpoint — do not overwrite
        except Exception as e:
            logger.error("Task processing failed", task_id=self.task_id, error=str(e))
            await self.update_status("failed", error=str(e))
            await self.update_progress(f"Ошибка: {str(e)[:400]}")
        finally:
            stop_event.set()
            heartbeat_task.cancel()

    async def _heartbeat(self, stop_event: asyncio.Event) -> None:
        """Log a heartbeat every 30 s so it's clear the task is alive, not hung."""
        elapsed = 0
        while not stop_event.is_set():
            await asyncio.sleep(30)
            if stop_event.is_set():
                break
            elapsed += 30
            logger.info("Task still running", task_id=self.task_id, elapsed_seconds=elapsed)
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
        changes_summary = data.get("changes_summary")

        if not items:
            raise ValueError("Claude не вернул позиции. Проверьте содержимое документов.")

        await self.update_progress(f"Найдено {len(items)} позиций. Формирование Excel...")
        excel_data = generate_list(items, changes_summary=changes_summary)

        await self.save_result("Перечень_работ_и_материалов.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               excel_data)
        logger.info("List task completed", items=len(items))

    async def _handle_list_from_tz_project(self, task: Task) -> None:
        await self.update_progress("Анализ ТЗ и проектной документации...")
        messages, image_blocks = self._build_messages_with_files(task, PROMPT_LIST_FROM_TZ_PROJECT)

        await self.update_progress("Сравнение ТЗ и проекта, формирование перечня с помощью ИИ...")
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
        excel_data = generate_list_project(items, changes_summary=changes_summary)

        await self.save_result(
            "Перечень_ТЗ_и_проект.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            excel_data,
        )
        logger.info("List TZ+project task completed", items=len(items))

    async def _handle_smeta_from_tz_project(self, task: Task) -> None:
        from datetime import date

        # Stage 1: extract items list from TZ + project docs
        await self.update_progress("Этап 1: формирование перечня работ и материалов из ТЗ и проекта...")
        messages, image_blocks = self._build_messages_with_files(task, PROMPT_LIST_FROM_TZ_PROJECT)
        stage1_data = await self._call_claude_json(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )

        stage1_items = stage1_data.get("items", [])
        changes_summary = stage1_data.get("changes_summary")

        if not stage1_items:
            raise ValueError("Claude не вернул позиции на этапе 1. Проверьте содержимое документов.")

        logger.info("Stage 1 complete", task_id=self.task_id, items=len(stage1_items))

        await self._check_cancelled()

        # Load price lists
        await self.update_progress("Загрузка базы расценок...")
        await price_service.load_cache(self.db)
        works_text, mats_text = self._format_price_list_text()
        current_date = date.today().strftime("%d.%m.%Y")

        # Stage 2: price the Stage 1 items
        await self.update_progress("Этап 2: составление сметы с ценами (поиск по прайсу и интернету)...")
        stage2_prompt = (
            PROMPT_SMETA_FROM_LIST
            .replace("{price_list_works}", works_text)
            .replace("{price_list_materials}", mats_text)
            .replace("{current_date}", current_date)
        )
        stage1_items_json = json.dumps({"items": stage1_items}, ensure_ascii=False, indent=2)
        stage2_content = f"Перечень работ и материалов:\n\n{stage1_items_json}\n\n{stage2_prompt}"
        if task.user_prompt:
            stage2_content += f"\n\nДополнительные требования: {task.user_prompt}"

        stage2_data = await self._call_claude_json(
            [{"role": "user", "content": stage2_content}],
            system_prompt=SYSTEM_BASE,
            use_web_search=True,
        )

        stage2_items = stage2_data.get("items", [])
        if not stage2_items:
            raise ValueError("Claude не вернул позиции сметы на этапе 2. Проверьте содержимое документов.")

        await self.update_progress(
            f"Формирование Excel (смета: {len(stage2_items)} поз., перечень: {len(stage1_items)} поз.)..."
        )
        excel_data = generate_smeta_from_tz_project(
            stage2_items, stage1_items, changes_summary=changes_summary
        )
        await self.save_result(
            "Смета_ТЗ_и_проект.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            excel_data,
        )
        logger.info(
            "Smeta TZ+project task completed",
            task_id=self.task_id,
            stage1_items=len(stage1_items),
            stage2_items=len(stage2_items),
        )

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

        await self._check_cancelled()

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
        from datetime import date

        # ── Stage 1: research project documentation ───────────────────────
        await self.update_progress("Этап 1: проверка проектной документации...")
        messages, image_blocks = self._build_messages_with_files(task, PROMPT_RESEARCH_PROJECT)
        research_result = await call_claude(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )
        logger.info("Stage 1 (research) complete", task_id=self.task_id, length=len(research_result))

        # Save Stage 1 result immediately so the user can download it now
        await self.update_progress("Этап 1 завершён: сохранение результата проверки проекта...")
        stage1_file_name = f"Этап1_Проверка_проекта_{date.today().strftime('%Y-%m-%d')}.pdf"
        await self.save_result(
            stage1_file_name,
            "application/pdf",
            generate_text_pdf(research_result),
        )

        await self._check_cancelled()

        # ── Stage 2: build normalised items list from project + research ──
        await self.update_progress("Этап 2: формирование перечня работ и материалов...")
        stage2_prompt = PROMPT_LIST_FROM_PROJECT.replace("{research_result}", research_result)
        messages2, image_blocks2 = self._build_messages_with_files(task, stage2_prompt)
        stage2_data = await self._call_claude_json(
            messages2,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks2 if image_blocks2 else None,
        )

        stage2_items = stage2_data.get("items", [])
        changes_summary = stage2_data.get("changes_summary")

        if not stage2_items:
            raise ValueError("Claude не вернул позиции на этапе 2. Проверьте содержимое документов.")

        logger.info("Stage 2 (list) complete", task_id=self.task_id, items=len(stage2_items))

        # Save Stage 2 result immediately so the user can download it now
        await self.update_progress("Этап 2 завершён: сохранение перечня работ и материалов...")
        stage2_excel = generate_list_project(stage2_items, changes_summary)
        stage2_file_name = f"Этап2_Перечень_работ_{date.today().strftime('%Y-%m-%d')}.xlsx"
        await self.save_result(
            stage2_file_name,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            stage2_excel,
        )

        await self._check_cancelled()

        # ── Stage 3: price the items list ────────────────────────────────
        await self.update_progress("Загрузка базы расценок...")
        await price_service.load_cache(self.db)
        works_text, mats_text = self._format_price_list_text()
        current_date = date.today().strftime("%d.%m.%Y")

        await self.update_progress("Этап 3: составление сметы с ценами (поиск по прайсу и интернету)...")
        stage3_prompt = (
            PROMPT_SMETA_FROM_LIST
            .replace("{price_list_works}", works_text)
            .replace("{price_list_materials}", mats_text)
            .replace("{current_date}", current_date)
        )
        stage2_items_json = json.dumps({"items": stage2_items}, ensure_ascii=False, indent=2)
        stage3_content = f"Перечень работ и материалов:\n\n{stage2_items_json}\n\n{stage3_prompt}"
        if task.user_prompt:
            stage3_content += f"\n\nДополнительные требования: {task.user_prompt}"

        stage3_data = await self._call_claude_json(
            [{"role": "user", "content": stage3_content}],
            system_prompt=SYSTEM_BASE,
            use_web_search=True,
        )

        stage3_items = stage3_data.get("items", [])
        if not stage3_items:
            raise ValueError("Claude не вернул позиции сметы на этапе 3. Проверьте содержимое документов.")

        await self.update_progress(
            f"Формирование Excel (смета: {len(stage3_items)} поз., перечень: {len(stage2_items)} поз.)..."
        )
        excel_data = generate_smeta_from_project(
            stage3_items, stage2_items,
            research_result=research_result,
            changes_summary=changes_summary,
        )
        await self.save_result(
            "Смета_из_проекта.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            excel_data,
        )
        logger.info(
            "Smeta from project (3-stage) completed",
            task_id=self.task_id,
            stage2_items=len(stage2_items),
            stage3_items=len(stage3_items),
        )

    # ------------------------------------------------------------------
    # SMETA_FROM_LIST — batched processing
    # ------------------------------------------------------------------

    def _parse_xlsx_items(self, task: Task) -> list[dict]:
        """Extract items from the first XLSX in task.input_file_data as dicts."""
        import base64 as _b64
        import io as _io
        import openpyxl as _xl

        for file_info in task.input_file_data or []:
            mime = file_info.get("mime_type", "")
            if mime not in (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-excel",
            ):
                continue
            try:
                raw = _b64.b64decode(file_info.get("content_b64", ""))
                wb = _xl.load_workbook(_io.BytesIO(raw), data_only=True)
                ws = wb.active
                rows = [
                    row for row in ws.iter_rows(values_only=True)
                    if not all(c is None for c in row)
                ]
                if len(rows) < 2:
                    return []
                headers = [
                    str(h).lower().strip() if h is not None else ""
                    for h in rows[0]
                ]
                col: dict[str, int] = {}
                for idx, h in enumerate(headers):
                    if "тип" in h or h == "type":
                        col.setdefault("type", idx)
                    elif any(k in h for k in ("наименование", "name", "название")):
                        col.setdefault("name", idx)
                    elif any(k in h for k in ("ед", "unit")):
                        col.setdefault("unit", idx)
                    elif any(k in h for k in ("кол", "quantity", "qty", "объём", "объем")):
                        col.setdefault("quantity", idx)
                    elif any(k in h for k in ("прим", "notes", "note")):
                        col.setdefault("notes", idx)

                if "name" not in col:
                    return []

                items: list[dict] = []
                for row in rows[1:]:
                    def _cell(key: str):
                        i = col.get(key)
                        return row[i] if i is not None and i < len(row) else None

                    name = _cell("name")
                    if not name:
                        continue
                    qty = _cell("quantity")
                    try:
                        qty = float(qty) if qty is not None else None
                    except (TypeError, ValueError):
                        qty = None
                    items.append({
                        "type": str(_cell("type") or "Работа"),
                        "name": str(name),
                        "unit": str(_cell("unit") or ""),
                        "quantity": qty,
                        "notes": str(_cell("notes") or ""),
                    })
                return items
            except Exception as exc:
                logger.warning("Failed to parse xlsx items", task_id=self.task_id, error=str(exc))
                return []
        return []

    async def _handle_smeta_from_list(self, task: Task) -> None:
        """Batch-process SMETA_FROM_LIST: split items into SMETA_BATCH_SIZE chunks.

        Design:
        - processing_timeout is passed to each call_claude call; it wraps ONLY the
          actual API call, NOT the rate-limit sleep.  This means a 429 with a long
          retry-after value never causes the batch to time out.
        - asyncio.TimeoutError from a true processing timeout marks the batch items
          as needs_retry (not silently unpriced).
        - After all main batches a retry queue processes needs_retry items in smaller
          sub-batches with a longer timeout.
        - Items that fail even in the retry queue receive a "требует ручной проверки"
          note so they are visible in the final Excel.
        """
        from datetime import date

        # 1. Load price lists
        await self.update_progress("Загрузка базы расценок...")
        await price_service.load_cache(self.db)
        works_text, mats_text = self._format_price_list_text()
        current_date = date.today().strftime("%d.%m.%Y")

        # 2. Extract items from uploaded Excel
        await self.update_progress("Извлечение позиций из файла...")
        items = self._parse_xlsx_items(task)

        if not items:
            logger.warning(
                "No items parsed from xlsx, falling back to single-call mode",
                task_id=self.task_id,
            )
            await self.update_progress("Составление сметы (одиночный запрос)...")
            await self._handle_smeta(task, PROMPT_SMETA_FROM_LIST)
            return

        # 3. Build prompt with price list injected
        base_prompt = (
            PROMPT_SMETA_FROM_LIST
            .replace("{price_list_works}", works_text)
            .replace("{price_list_materials}", mats_text)
            .replace("{current_date}", current_date)
        )

        # 4. Split into batches
        batches = [
            items[i:i + SMETA_BATCH_SIZE]
            for i in range(0, len(items), SMETA_BATCH_SIZE)
        ]
        total_batches = len(batches)
        logger.info(
            "Batched smeta starting",
            task_id=self.task_id,
            total_items=len(items),
            total_batches=total_batches,
        )

        # 5. Main pass — one Claude call per batch
        all_results: list[dict] = []
        needs_retry: list[dict] = []

        for batch_num, batch in enumerate(batches, start=1):
            await self._check_cancelled()
            await self.update_progress(
                f"Обработка батча {batch_num} из {total_batches} ({len(batch)} позиций)..."
            )

            batch_json = json.dumps({"items": batch}, ensure_ascii=False, indent=2)
            content = f"Перечень работ и материалов:\n\n{batch_json}\n\n{base_prompt}"
            if task.user_prompt:
                content += f"\n\nДополнительные требования: {task.user_prompt}"

            try:
                batch_data = await self._call_claude_json(
                    [{"role": "user", "content": content}],
                    system_prompt=SYSTEM_BASE,
                    use_web_search=True,
                    processing_timeout=SMETA_BATCH_TIMEOUT_SECS,
                )
                batch_items = batch_data.get("items", [])
                all_results.extend(batch_items)

                # If Claude returned fewer items than sent, queue the rest for retry.
                unmatched = batch[len(batch_items):]
                if unmatched:
                    logger.warning(
                        "Batch partial response: queuing unmatched items for retry",
                        task_id=self.task_id,
                        batch=batch_num,
                        items_in=len(batch),
                        items_out=len(batch_items),
                        unmatched=len(unmatched),
                    )
                    needs_retry.extend(unmatched)

                logger.info(
                    "Batch processed",
                    task_id=self.task_id,
                    batch=batch_num,
                    total=total_batches,
                    items_in=len(batch),
                    items_out=len(batch_items),
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Batch timed out, queuing items for retry",
                    task_id=self.task_id,
                    batch=batch_num,
                    total=total_batches,
                    timeout=SMETA_BATCH_TIMEOUT_SECS,
                )
                needs_retry.extend(batch)

            # Pause between batches to reduce token-rate pressure (skip after last).
            if batch_num < total_batches:
                await asyncio.sleep(SMETA_INTER_BATCH_DELAY)

        # 6. Retry queue — process needs_retry items with smaller batches / longer timeout
        if needs_retry:
            retried = await self._process_retry_queue(needs_retry, base_prompt, task)
            all_results.extend(retried)

        if not all_results:
            raise ValueError("Не удалось получить ни одной позиции сметы.")

        await self.update_progress(f"Генерация Excel-сметы ({len(all_results)} позиций)...")
        excel_data = generate_smeta(all_results)
        await self.save_result(
            "Смета.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            excel_data,
        )
        logger.info(
            "Batched smeta_from_list completed",
            task_id=self.task_id,
            total_items=len(all_results),
            total_batches=total_batches,
        )

    async def _process_retry_queue(
        self,
        items: list[dict],
        base_prompt: str,
        task: Task,
    ) -> list[dict]:
        """Process items that could not be priced in the main pass.

        Uses smaller batches (SMETA_RETRY_BATCH_SIZE), a longer per-call timeout
        (SMETA_RETRY_TIMEOUT_SECS), and a longer pause between batches
        (SMETA_RETRY_INTER_BATCH_DELAY).

        Items that still time out after the retry are returned with a
        "требует ручной проверки" note so the user can find them in the Excel.
        """
        results: list[dict] = []
        retry_batches = [
            items[i:i + SMETA_RETRY_BATCH_SIZE]
            for i in range(0, len(items), SMETA_RETRY_BATCH_SIZE)
        ]
        total = len(retry_batches)
        logger.info(
            "Starting retry queue",
            task_id=self.task_id,
            needs_retry=len(items),
            retry_batches=total,
        )

        for batch_num, batch in enumerate(retry_batches, start=1):
            await self._check_cancelled()
            await self.update_progress(
                f"Повторная обработка {batch_num} из {total} ({len(batch)} позиций)..."
            )

            batch_json = json.dumps({"items": batch}, ensure_ascii=False, indent=2)
            content = f"Перечень работ и материалов:\n\n{batch_json}\n\n{base_prompt}"
            if task.user_prompt:
                content += f"\n\nДополнительные требования: {task.user_prompt}"

            try:
                batch_data = await self._call_claude_json(
                    [{"role": "user", "content": content}],
                    system_prompt=SYSTEM_BASE,
                    use_web_search=True,
                    processing_timeout=SMETA_RETRY_TIMEOUT_SECS,
                )
                batch_items = batch_data.get("items", [])
                results.extend(batch_items)

                # Any input items not represented in the output → manual check.
                for item in batch[len(batch_items):]:
                    item["notes"] = "требует ручной проверки"
                    results.append(item)

                logger.info(
                    "Retry batch processed",
                    task_id=self.task_id,
                    batch=batch_num,
                    total=total,
                    items_in=len(batch),
                    items_out=len(batch_items),
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Retry batch timed out, marking items for manual check",
                    task_id=self.task_id,
                    batch=batch_num,
                    total=total,
                    timeout=SMETA_RETRY_TIMEOUT_SECS,
                )
                for item in batch:
                    item["notes"] = "требует ручной проверки"
                    results.append(item)

            if batch_num < total:
                await asyncio.sleep(SMETA_RETRY_INTER_BATCH_DELAY)

        return results

    async def _handle_research_project(self, task: Task) -> None:
        """Standalone stage-1 equivalent: review project docs, save plain-text result."""
        from datetime import date

        await self.update_progress("Анализ проектной документации...")
        messages, image_blocks = self._build_messages_with_files(task, PROMPT_RESEARCH_PROJECT)

        await self.update_progress("Проверка проекта с помощью ИИ...")
        result_text = await call_claude(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )

        await self.update_progress("Сохранение результата проверки проекта...")
        file_name = f"Проверка_проекта_{date.today().strftime('%Y-%m-%d')}.pdf"
        await self.save_result(
            file_name,
            "application/pdf",
            generate_text_pdf(result_text),
        )
        logger.info("Research project task completed", task_id=self.task_id, length=len(result_text))

    async def _handle_list_from_project(self, task: Task) -> None:
        """Standalone stage-2 equivalent: build items list from project docs, save Excel."""
        _NO_RESEARCH = (
            "Предварительная проверка проекта не проводилась. "
            "Составляй перечень напрямую по проектной документации."
        )
        prompt = PROMPT_LIST_FROM_PROJECT.replace("{research_result}", _NO_RESEARCH)

        await self.update_progress("Анализ проектной документации...")
        messages, image_blocks = self._build_messages_with_files(task, prompt)

        await self.update_progress("Формирование перечня работ и материалов с помощью ИИ...")
        data = await self._call_claude_json(
            messages,
            system_prompt=SYSTEM_BASE,
            use_web_search=False,
            image_data=image_blocks if image_blocks else None,
        )

        items = data.get("items", [])
        changes_summary = data.get("changes_summary")

        if not items:
            raise ValueError("Claude не вернул позиции. Проверьте содержимое документов.")

        await self.update_progress(f"Найдено {len(items)} позиций. Формирование Excel...")
        excel_data = generate_list_project(items, changes_summary)
        await self.save_result(
            "Перечень_из_проекта.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            excel_data,
        )
        logger.info("List from project task completed", task_id=self.task_id, items=len(items))

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

    async def _handle_optimize_smeta(self, task: Task) -> None:
        """Handle OPTIMIZE_SMETA: parse uploaded xlsx, find analogues, save optimized xlsx."""
        import base64 as _base64
        import uuid as _uuid
        from app.utils.xlsx_optimizer import parse_estimate_xlsx, get_top_items, generate_optimized_xlsx
        from app.models.history import TaskHistory
        from sqlalchemy import select

        if not task.input_file_data:
            raise ValueError("Нет загруженного файла сметы")

        file_entry = task.input_file_data[0]
        file_bytes = _base64.b64decode(file_entry["content_b64"])

        await self.update_progress("Разбираю файл сметы...")
        items = parse_estimate_xlsx(file_bytes)
        top_items = get_top_items(items, categories=["work", "material"], threshold=0.7)

        # Capture previous optimized slot before overwriting
        prev_result_q = await self.db.execute(
            select(TaskResult).where(
                TaskResult.task_id == self.task_id,
                TaskResult.slot == "optimized",
            )
        )
        prev_optimized = prev_result_q.scalar_one_or_none()
        prev_estimation_status = "optimized" if prev_optimized else "estimated"

        await price_service.load_cache(self.db)
        optimization_results = []
        total = len(top_items)

        for i, item in enumerate(top_items):
            name = item["name"]
            item_type = item["type"]
            original_price = item["price_incl_vat"]
            await self.update_progress(f"Поиск аналогов {i + 1}/{total}: {name[:40]}")

            found_price = None
            source = "Не найдено"
            try:
                if item_type == "work":
                    price_data = await price_service.find_work_price(name)
                else:
                    price_data = await price_service.find_material_price(name)
                if price_data and price_data.get("price"):
                    found_price = float(price_data["price"])
                    source = price_data.get("source", "Прайс-лист")
            except Exception:
                pass

            savings_abs = None
            savings_pct = None
            if found_price is not None and found_price < original_price:
                savings_abs = round(original_price - found_price, 4)
                savings_pct = round(savings_abs / original_price * 100, 2)
            elif found_price is not None:
                found_price = None
                source = "Не найдено (цена не ниже)"

            optimization_results.append({
                "row_index": item["row_index"],
                "name": name,
                "original_price": original_price,
                "new_price": found_price,
                "source": source,
                "savings_abs": savings_abs,
                "savings_pct": savings_pct,
                "has_vat": True,
            })

        await self.update_progress("Генерирую оптимизированный файл...")
        optimized_bytes = generate_optimized_xlsx(file_bytes, optimization_results)

        result_record = TaskResult(
            task_id=self.task_id,
            slot="optimized",
            file_name="optimized.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_data=optimized_bytes,
        )
        self.db.add(result_record)
        await self.db.commit()

        # Write history entry
        found_count = sum(1 for r in optimization_results if r["new_price"] is not None)
        previous_value: dict = {}
        if prev_optimized:
            previous_value = {
                "file_name": prev_optimized.file_name,
                "file_data_b64": _base64.b64encode(prev_optimized.file_data).decode(),
                "estimation_status": prev_estimation_status,
            }
        else:
            previous_value = {"estimation_status": prev_estimation_status}

        new_value = {
            "file_name": "optimized.xlsx",
            "file_data_b64": _base64.b64encode(optimized_bytes).decode(),
            "estimation_status": "optimized",
        }

        history = TaskHistory(
            id=str(_uuid.uuid4()),
            task_id=self.task_id,
            operation_type="optimization",
            slot="optimized",
            description=f"Оптимизация: найдено {found_count} из {total} аналогов",
            previous_value=previous_value,
            new_value=new_value,
        )
        self.db.add(history)

        # Override the default update_status call in process() with optimized status
        task.estimation_status = "optimized"
        await self.db.commit()


async def process_task(task_id: str, db: AsyncSession) -> None:
    """Entry point for background task processing."""
    processor = TaskProcessor(task_id, db)
    await processor.process()
