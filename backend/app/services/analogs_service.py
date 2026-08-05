"""Поиск более дешёвых аналогов через ИИ.

Фаза 11 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.

Цель — не «похожая позиция», а **дешевле при том же результате**: замена
материала или технологии. Источник цен — интернет, поэтому обращение к Claude
идёт с веб-поиском, а это основная статья расходов (смета ~$10, из них 68% —
поиск).

Что удерживает расходы и данные в порядке:

- прогон один на документ: пока идёт поиск, второй запуск не стартует;
- прогон можно остановить — потолка позиций за запуск нет (решение
  пользователя), значит остановка обязана быть;
- позиции без имени и без цены не отправляются: удешевлять там нечего;
- вариант дороже исходной цены отбрасывается;
- найденное никогда не попадает в документ само — это предложение, которое
  человек принимает кнопкой «Заменить».
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analog_run import (
    ACTIVE_STATUSES,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    AnalogRun,
)
from app.services.claude_service import call_claude
from app.utils.auth import current_user_id
from app.utils.json_utils import extract_json

logger = structlog.get_logger()

# Сколько позиций уходит в один запрос к ИИ. Больше — дешевле по токенам, но
# качество ответа падает: модель начинает отвечать общими словами.
BATCH_SIZE = 5
# Сколько вариантов показываем на позицию (решение пользователя 5.x).
MAX_VARIANTS = 3
# Оценка для человека: примерно столько поисков и времени уходит на позицию.
SEARCHES_PER_POSITION = 2
SECONDS_PER_BATCH = 45
# Потолок ожидания одного запроса. Веб-поиск медленный, но зависать нельзя.
CALL_TIMEOUT_S = 180.0

_PROMPT = (
    "Ты — эксперт по строительным сметам и снабжению.\n\n"
    "Для каждой позиции найди в интернете аналоги, которые дают ТОТ ЖЕ "
    "результат, но стоят дешевле: другой материал, другая технология, другой "
    "поставщик. Цена — за ту же единицу измерения, что у позиции.\n\n"
    "Правила:\n"
    "- до 3 вариантов на позицию, только реально более дешёвые;\n"
    "- цена — число в рублях за единицу, без текста;\n"
    "- обязательно укажи источник (ссылку), откуда взята цена;\n"
    "- в обосновании коротко объясни, почему результат не пострадает;\n"
    "- если достойного аналога нет — верни для позиции пустой список вариантов, "
    "не выдумывай.\n\n"
    "Позиции:\n{positions}\n\n"
    "Верни СТРОГО JSON без markdown:\n"
    '{{"items": [{{"row_id": "...", "variants": [{{"name": "...", "unit": "...", '
    '"price": число, "reason": "...", "source": "..."}}]}}]}}'
)


def estimate_effort(positions: int) -> dict:
    """Во что обойдётся запуск — это человек видит до подтверждения."""
    if positions <= 0:
        return {"positions": 0, "searches": 0, "minutes": 0}
    batches = (positions + BATCH_SIZE - 1) // BATCH_SIZE
    minutes = max(1, round(batches * SECONDS_PER_BATCH / 60))
    return {
        "positions": positions,
        "searches": positions * SEARCHES_PER_POSITION,
        "minutes": minutes,
    }


def _to_number(value: object) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # отсекает NaN


def prepare_positions(rows: list) -> list:
    """Отобрать позиции, для которых поиск имеет смысл."""
    prepared = []
    for raw in rows or []:
        row = raw if isinstance(raw, dict) else {}
        name = str(row.get("name") or "").strip()
        price = _to_number(row.get("price"))
        if not name or price is None or price <= 0:
            continue
        prepared.append({
            "row_id": str(row.get("row_id") or ""),
            "name": name,
            "unit": str(row.get("unit") or ""),
            "qty": _to_number(row.get("qty")) or 0.0,
            "price": price,
            "kind": "material" if row.get("kind") == "material" else "work",
        })
    return prepared


async def active_run(db: AsyncSession, task_id: str, kind: str) -> Optional[AnalogRun]:
    res = await db.execute(
        select(AnalogRun)
        .where(
            AnalogRun.task_id == str(task_id),
            AnalogRun.document_kind == kind,
            AnalogRun.status.in_(ACTIVE_STATUSES),
        )
        .order_by(AnalogRun.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def latest_run(db: AsyncSession, task_id: str, kind: str) -> Optional[AnalogRun]:
    res = await db.execute(
        select(AnalogRun)
        .where(AnalogRun.task_id == str(task_id), AnalogRun.document_kind == kind)
        .order_by(AnalogRun.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


# Сколько прогон может считаться живым без единого признака жизни. Дольше самого
# долгого разумного поиска: 500 позиций — это сто пачек примерно по минуте.
ABANDONED_AFTER_HOURS = 4


def _looks_abandoned(run: AnalogRun) -> bool:
    """Прогон числится идущим, но за ним никого нет."""
    started = run.created_at
    if started is None:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - started).total_seconds() / 3600
    return age_hours >= ABANDONED_AFTER_HOURS


async def mark_failed(db: AsyncSession, run_id: str, error: str) -> None:
    """Пометить прогон несостоявшимся.

    Вызывается обработчиком очереди, когда задача упала на чём-то, чего сервис
    не поймал сам: иначе прогон остался бы «идущим» и заблокировал повторный
    запуск до истечения `ABANDONED_AFTER_HOURS`.
    """
    run = await db.get(AnalogRun, run_id)
    if run is None or run.status not in ACTIVE_STATUSES:
        return
    run.status = STATUS_FAILED
    run.error = f"Поиск аналогов не удался: {error}"
    run.finished_at = datetime.now(timezone.utc)
    await db.commit()


async def start_run(
    db: AsyncSession,
    doc,
    version_id: Optional[str],
    rows: list,
    current_user: dict,
    user_name: str,
) -> AnalogRun:
    """Поставить прогон в очередь. Документ при этом не меняется."""
    from app.services import job_queue

    positions = prepare_positions(rows)
    if not positions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Не выбрано ни одной позиции с наименованием и ценой",
        )

    running = await active_run(db, str(doc.task.id), doc.kind)
    if running is not None and _looks_abandoned(running):
        # Воркер мог упасть или быть перезапущен вместе с сервером. Без этого
        # брошенный прогон навсегда закрыл бы документу поиск аналогов.
        running.status = STATUS_FAILED
        running.error = "Поиск прервался: обработчик не ответил. Запустите заново."
        running.finished_at = datetime.now(timezone.utc)
        await db.commit()
        running = None

    if running is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Поиск аналогов по этому документу уже идёт. Дождитесь окончания "
                "или остановите его."
            ),
        )

    run = AnalogRun(
        task_id=str(doc.task.id),
        document_kind=doc.kind,
        version_id=version_id,
        status=STATUS_QUEUED,
        requested=positions,
        results=[],
        processed=0,
        total=len(positions),
        user_id=current_user_id(current_user),
        user_name=user_name,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    await job_queue.enqueue(
        db,
        kind="document.analogs",
        payload={"run_id": str(run.id)},
        owner_id=current_user_id(current_user),
    )

    logger.info(
        "analogs_run_started",
        run_id=str(run.id), task_id=str(doc.task.id), kind=doc.kind,
        positions=len(positions),
    )
    return run


async def cancel_run(db: AsyncSession, task_id: str, kind: str) -> Optional[AnalogRun]:
    """Остановить идущий прогон. Уже найденное остаётся."""
    run = await active_run(db, task_id, kind)
    if run is None:
        return None
    run.status = STATUS_CANCELLED
    run.finished_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("analogs_run_cancelled", run_id=str(run.id))
    return run


def _clean_variants(position: dict, raw_variants: object) -> list:
    """Оставить только те варианты, ради которых действие и затевалось."""
    if not isinstance(raw_variants, list):
        return []

    base_price = position["price"]
    qty = position["qty"]
    variants = []
    for raw in raw_variants:
        item = raw if isinstance(raw, dict) else {}
        name = str(item.get("name") or "").strip()
        price = _to_number(item.get("price"))
        if not name or price is None or price <= 0:
            continue
        # Дороже исходного — не аналог: смысл действия в удешевлении.
        if price >= base_price:
            continue
        variants.append({
            "name": name,
            "unit": str(item.get("unit") or position["unit"]),
            "price": round(price, 2),
            # Разницу в деньгах считаем сами: у модели она регулярно не сходится
            # с её же ценой, а по этой цифре человек принимает решение.
            "delta": round((base_price - price) * qty, 2),
            "reason": str(item.get("reason") or "").strip(),
            "source": str(item.get("source") or "").strip(),
        })

    variants.sort(key=lambda v: v["delta"], reverse=True)
    return variants[:MAX_VARIANTS]


async def _ask_batch(batch: list, task_id: str, db: AsyncSession) -> dict:
    """Спросить ИИ про пачку позиций. Возвращает row_id → варианты."""
    listing = "\n".join(
        f'- row_id={p["row_id"]}; {p["name"]}; ед. изм.: {p["unit"] or "—"}; '
        f'текущая цена: {p["price"]} ₽ за единицу'
        for p in batch
    )
    response = await call_claude(
        messages=[{"role": "user", "content": _PROMPT.format(positions=listing)}],
        use_web_search=True,
        processing_timeout=CALL_TIMEOUT_S,
        task_id=task_id,
        db=db,
        # Доп: аналоги ищутся по уже сформированному документу стадии.
        is_extra=True,
    )

    try:
        data = extract_json(response)
    except Exception:
        # Модель ответила текстом вместо JSON. Пачка остаётся без вариантов —
        # терять из-за неё уже найденное по другим позициям нельзя.
        logger.warning("analogs_batch_unparsable", task_id=task_id)
        return {}

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("row_id")): item.get("variants")
        for item in items
        if isinstance(item, dict)
    }


async def process_run(db: AsyncSession, run_id: str) -> None:
    """Обработать прогон: пачками, с прогрессом и проверкой отмены."""
    run = await db.get(AnalogRun, run_id)
    if run is None or run.status not in ACTIVE_STATUSES:
        return

    run.status = STATUS_RUNNING
    await db.commit()

    positions = list(run.requested or [])
    results: list = []
    failures = 0
    batches = 0

    for start in range(0, len(positions), BATCH_SIZE):
        # Отмену проверяем перед каждой пачкой: платить за то, от чего человек
        # уже отказался, незачем.
        await db.refresh(run)
        if run.status == STATUS_CANCELLED:
            # Копия, а не сам список: в колонку кладём снимок на этот момент, а
            # рабочий список живёт дальше в цикле.
            run.results = list(results)
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("analogs_run_stopped", run_id=str(run.id), processed=run.processed)
            return

        batch = positions[start:start + BATCH_SIZE]
        batches += 1
        try:
            found = await _ask_batch(batch, str(run.task_id), db)
        except Exception as exc:  # noqa: BLE001 — причину показываем человеку
            failures += 1
            logger.error("analogs_batch_failed", run_id=str(run.id), error=str(exc))
            if failures == batches:
                # Не прошла ещё ни одна пачка — это не «аналогов нет», а поломка.
                run.status = STATUS_FAILED
                run.error = f"Поиск аналогов не удался: {exc}"
                run.results = list(results)
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()
                return
            found = {}

        for position in batch:
            results.append({
                "row_id": position["row_id"],
                "name": position["name"],
                "unit": position["unit"],
                "price": position["price"],
                "variants": _clean_variants(position, found.get(position["row_id"])),
            })

        run.processed = min(len(positions), start + len(batch))
        run.results = list(results)
        await db.commit()

    run.status = STATUS_DONE
    run.results = list(results)
    if failures:
        # Часть пачек не прошла: прогон дошёл до конца, но человек должен знать,
        # что по этим позициям поиска фактически не было.
        run.error = (
            f"Часть позиций обработать не удалось (неудачных запросов: {failures}). "
            "Их можно попробовать ещё раз."
        )
    run.finished_at = datetime.now(timezone.utc)
    await db.commit()

    found_count = sum(len(item["variants"]) for item in results)
    logger.info(
        "analogs_run_done",
        run_id=str(run.id), positions=len(positions), variants=found_count,
    )


def run_to_dict(run: Optional[AnalogRun]) -> dict:
    """Состояние прогона для клиента. Прогона нет — пустой ответ, а не ошибка."""
    if run is None:
        return {
            "run_id": None, "status": None, "processed": 0, "total": 0,
            "results": [], "error": None, "created_at": None,
        }
    return {
        "run_id": str(run.id),
        "status": run.status,
        "processed": run.processed,
        "total": run.total,
        "results": run.results or [],
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
