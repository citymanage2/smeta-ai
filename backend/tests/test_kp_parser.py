"""ИИ-разбор файла КП (план 2026-09-14-zapros-kp.md, фаза 6; критерии 16–17).

Claude замокан. Проверяется:
* загрузка КП с файлом ставит разбор в очередь, воркер его выполняет;
* ИИ возвращает цены только для позиций запроса — чужой id отброшен;
* распознанная цена — черновик (`ai`, не подтверждена), ручная цена цела;
* «только сумма» → цена = сумма / количество, уверенность низкая;
* ошибка API → `failed` с текстом, ручной ввод доступен;
* повторный разбор заменяет только неподтверждённые цены ИИ;
* догадки заполняют только пустые поля КП, НДС и «включает материалы» —
  подсказкой;
* брошенный разбор (`processing` > 15 мин) при чтении становится `failed`;
* вызов попадает в журнал стоимости, сумма — в `parse_cost`.
"""
import io
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import openpyxl
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.api_call_log import ApiCallLog
from app.models.job import Job
from app.models.kp_request import KpOffer, KpOfferPrice, KpRequest
from app.services import kp_parser
from tests.helpers.anthropic_api import claude_message, prompt_text
from tests.helpers.kp import CONTRACTOR, PM, SUPPLY, create_offer, headers, pdf, upload_offer


def _xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Прайс"
    ws.append(["Наименование", "Ед.", "Цена"])
    ws.append(["Арматура А500С d12", "т", 54900])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, format="PNG")
    return buf.getvalue()


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest_asyncio.fixture
async def env(make_kp_env):
    return await make_kp_env()


class FakeClaude:
    """Подмена `kp_parser.call_claude`: отдаёт заготовленный ответ и платит."""

    def __init__(self, answer=None, error=None, cost="0.0125"):
        self.answer = answer
        self.error = error
        self.cost = Decimal(cost)
        self.calls = []

    async def __call__(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if kwargs.get("on_cost"):
            kwargs["on_cost"](self.cost)
        if self.error is not None:
            raise self.error
        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer, ensure_ascii=False)


def _short_ids(fake: FakeClaude) -> dict:
    """Имя позиции → id, под которым она ушла в промпт."""
    text = _prompt_text(fake.calls[-1]["messages"])
    listing = json.loads(text.split("<positions>")[1].split("</positions>")[0])
    return {p["name"]: p["id"] for p in listing}


def _prompt_text(messages) -> str:
    content = messages[0]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", "") for block in content if isinstance(block, dict))


async def _run(db_session, monkeypatch, offer_id, answer_fn=None, **fake_kw):
    """Прогнать разбор. `answer_fn(ids)` строит ответ по id позиций из промпта."""
    fake = FakeClaude(**fake_kw)
    if answer_fn is not None:
        original = fake.__call__

        async def call(messages, **kwargs):
            fake.calls.append({"messages": messages, **kwargs})
            fake.answer = answer_fn(_short_ids(fake))
            fake.calls.pop()
            return await original(messages, **kwargs)

        monkeypatch.setattr(kp_parser, "call_claude", call)
    else:
        monkeypatch.setattr(kp_parser, "call_claude", fake)
    await kp_parser.process_offer(db_session, offer_id)
    db_session.expire_all()
    return fake


def _ids_in(kwargs: dict) -> dict:
    """Имя позиции → id, под которым она ушла в настоящий запрос к ИИ."""
    text = prompt_text(kwargs)
    listing = json.loads(text.split("<positions>")[1].split("</positions>")[0])
    return {p["name"]: p["id"] for p in listing}


async def _prices(db_session, offer_id):
    rows = (await db_session.execute(
        select(KpOfferPrice).where(KpOfferPrice.offer_id == offer_id)
    )).scalars().all()
    return {str(r.item_id): r for r in rows}


# ---------------------------------------------------------------------------
# Постановка разбора
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_with_file_queues_parse_that_worker_runs(async_client, db_session, env, claude_api):
    """Загрузка КП с файлом ставит разбор в очередь; воркер его выполняет — цены черновиком."""
    from app import worker

    offer = await create_offer(async_client, env)
    assert offer["parse_status"] == "queued"
    (job,) = (await db_session.execute(select(Job).where(Job.status == "queued"))).scalars().all()

    claude_api(lambda kwargs: {"prices": [
        {"item_id": _ids_in(kwargs)["Арматура А500"], "unit": "т", "unit_price": 54900,
         "confidence": "high"},
    ]})
    # Как `worker.run_job`: обработчик по виду job, payload с номером job.
    await worker.HANDLERS[job.kind]({**job.payload, "_job_id": job.id, "_job_attempt": 1}, db_session)

    db_session.expire_all()
    stored = await db_session.get(KpOffer, offer["id"])
    assert stored.parse_status == "parsed"
    row = (await _prices(db_session, offer["id"]))[env["armature"]]
    assert (row.price, row.unit, row.source, row.confirmed) == (54900, "т", "ai", False)


@pytest.mark.asyncio
async def test_upload_without_file_has_no_parse(async_client, db_session, env):
    resp = await upload_offer(async_client, env)
    assert resp.status_code == 201, resp.text
    assert resp.json()["parse_status"] is None
    jobs = (await db_session.execute(select(Job))).scalars().all()
    assert jobs == []


# ---------------------------------------------------------------------------
# Разбор: цены, чужие id, ручные цены, «только сумма»
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parse_writes_drafts_and_drops_foreign_ids(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env)

    def answer(ids):
        return {"prices": [
            {"item_id": ids["Арматура А500"], "name_in_offer": "Арматура А500С d12", "unit": "т",
             "unit_price": 54900, "confidence": "high"},
            {"item_id": "999", "name_in_offer": "Выдуманная", "unit": "шт", "unit_price": 10, "confidence": "high"},
            {"item_id": env["plaster"], "name_in_offer": "Чужая позиция", "unit": "м2", "unit_price": 500},
            {"item_id": env["cement"], "name_in_offer": "UUID вместо id", "unit": "кг", "unit_price": 9},
        ]}

    await _run(db_session, monkeypatch, offer["id"], answer)

    prices = await _prices(db_session, offer["id"])
    assert set(prices) == {env["armature"]}
    row = prices[env["armature"]]
    assert row.price == 54900 and row.unit == "т"
    assert row.name_in_offer == "Арматура А500С d12"
    assert row.source == "ai" and row.confirmed is False and row.confidence == "high"
    assert row.includes_materials is None

    stored = await db_session.get(KpOffer, offer["id"])
    assert stored.parse_status == "parsed"
    assert stored.parse_error is None
    assert stored.parse_hints["prices_found"] == 1
    assert stored.parse_hints["dropped_unknown"] == 3

    # Карточка: черновик с приведённой ценой (54 900 с НДС 22 % за т → 45,00 за кг).
    detail = (await async_client.get(f"/kp-requests/{env['material']}", headers=headers(env, SUPPLY))).json()
    cell = detail["items"][0]["cells"][0]
    assert cell["confirmed"] is False and cell["source"] == "ai"
    assert cell["normalized_price"] == 45.0
    assert detail["offers"][0]["parse_status"] == "parsed"


@pytest.mark.asyncio
async def test_prompt_has_positions_without_database_ids(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env)
    fake = await _run(db_session, monkeypatch, offer["id"], answer={"prices": []})
    text = _prompt_text(fake.calls[0]["messages"])
    assert "Арматура А500" in text and "Цемент М500" in text
    assert env["armature"] not in text and env["cement"] not in text
    assert "Штукатурка" not in text  # позиции чужого запроса не уходят
    ids = _short_ids(fake)
    assert sorted(ids.values()) == ["1", "2"]


@pytest.mark.asyncio
async def test_manual_price_survives_parse(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env)
    resp = await async_client.put(
        f"/kp-offers/{offer['id']}/prices/{env['cement']}", headers=headers(env, SUPPLY),
        json={"price": 10, "unit": "кг"},
    )
    assert resp.status_code == 200, resp.text

    def answer(ids):
        return {"prices": [
            {"item_id": ids["Цемент М500"], "name_in_offer": "ЦЕМ I", "unit": "т", "unit_price": 9000,
             "confidence": "high"},
            {"item_id": ids["Арматура А500"], "unit": "кг", "unit_price": 45, "confidence": "medium"},
        ]}

    await _run(db_session, monkeypatch, offer["id"], answer)
    prices = await _prices(db_session, offer["id"])
    manual = prices[env["cement"]]
    assert manual.source == "manual" and manual.confirmed is True
    assert manual.price == 10 and manual.unit == "кг"
    assert prices[env["armature"]].source == "ai" and prices[env["armature"]].confidence == "medium"


@pytest.mark.asyncio
async def test_total_only_is_divided_by_quantity_with_low_confidence(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env)

    def answer(ids):
        return {"prices": [
            # Только сумма за 2 т: 108 000 / 2 = 54 000 за т.
            {"item_id": ids["Арматура А500"], "unit": "т", "total_only": True, "total": 108000, "qty": 2,
             "confidence": "high"},
            # Количество не указано в КП — берётся объём позиции: 5000 / 500 = 10.
            {"item_id": ids["Цемент М500"], "unit": "кг", "total_only": True, "total": 5000},
        ]}

    await _run(db_session, monkeypatch, offer["id"], answer)
    prices = await _prices(db_session, offer["id"])
    assert prices[env["armature"]].price == 54000
    assert prices[env["armature"]].confidence == "low"
    assert prices[env["cement"]].price == 10
    assert prices[env["cement"]].confidence == "low"


def test_postprocess_rejects_bad_numbers():
    items = [SimpleNamespace(id="a", name="Арматура", unit="кг", qty=0),
             SimpleNamespace(id="b", name="Цемент", unit="кг", qty=None)]
    ids = {"1": items[0], "2": items[1]}
    data = {"prices": [
        {"item_id": "1", "total_only": True, "total": 1000},          # объём позиции 0 — делить нельзя
        {"item_id": "2", "total_only": True, "total": 1000, "qty": 0},  # количество 0
        {"item_id": "2", "unit_price": -5},
        {"item_id": "2", "unit_price": "abc"},
        "мусор",
    ]}
    result = kp_parser.postprocess(data, ids)
    assert result.prices == {}


def test_postprocess_parses_russian_numbers_and_first_answer_wins():
    item = SimpleNamespace(id="a", name="Арматура", unit="кг", qty=10)
    data = {"prices": [
        {"item_id": "1", "unit_price": "1 250,50", "confidence": "очень"},
        {"item_id": "1", "unit_price": 1},
    ]}
    result = kp_parser.postprocess(data, {"1": item})
    assert result.prices["a"]["price"] == 1250.5
    assert result.prices["a"]["confidence"] == "low"  # неизвестная уверенность — низкая
    assert result.dropped_duplicates == 1


# ---------------------------------------------------------------------------
# Ошибки, повторный разбор, догадки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_error_marks_failed_and_manual_input_works(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env)
    fake = await _run(db_session, monkeypatch, offer["id"], error=RuntimeError("HTTP 529 overloaded"))
    stored = await db_session.get(KpOffer, offer["id"])
    assert stored.parse_status == "failed"
    assert "HTTP 529 overloaded" in stored.parse_error
    assert "вручную" in stored.parse_error
    assert stored.parse_cost == float(fake.cost)  # оплаченное до сбоя не теряется
    assert await _prices(db_session, offer["id"]) == {}

    resp = await async_client.put(
        f"/kp-offers/{offer['id']}/prices/{env['cement']}", headers=headers(env, SUPPLY),
        json={"price": 10, "unit": "кг"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_unparsable_answer_marks_failed(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env)
    await _run(db_session, monkeypatch, offer["id"], answer="Извините, не могу прочитать файл")
    stored = await db_session.get(KpOffer, offer["id"])
    assert stored.parse_status == "failed"
    assert stored.parse_error


@pytest.mark.asyncio
async def test_reparse_replaces_only_unconfirmed_ai_prices(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env)
    db_session.add_all([
        # Черновик прошлого разбора по позиции, которой в новом ответе нет, — уходит.
        KpOfferPrice(offer_id=offer["id"], item_id=env["armature"], price=1, unit="кг",
                     source="ai", confidence="low", confirmed=False),
        # Подтверждённая человеком цена ИИ — решение человека, не трогается.
        KpOfferPrice(offer_id=offer["id"], item_id=env["cement"], price=9, unit="кг",
                     source="ai", confidence="high", confirmed=True),
    ])
    stored = await db_session.get(KpOffer, offer["id"])
    stored.parse_status = "failed"
    stored.parse_error = "Разбор не удался"
    await db_session.commit()

    resp = await async_client.post(f"/kp-offers/{offer['id']}/parse", headers=headers(env, SUPPLY))
    assert resp.status_code == 200, resp.text
    assert resp.json()["parse_status"] == "queued"
    assert resp.json()["parse_error"] is None
    jobs = (await db_session.execute(select(Job).where(Job.kind == "kp.parse_offer"))).scalars().all()
    assert len(jobs) == 2  # загрузка + повтор

    def answer(ids):
        return {"prices": [
            {"item_id": ids["Цемент М500"], "unit": "кг", "unit_price": 11, "confidence": "high"},
        ]}

    await _run(db_session, monkeypatch, offer["id"], answer)
    prices = await _prices(db_session, offer["id"])
    assert set(prices) == {env["cement"]}
    assert prices[env["cement"]].price == 9 and prices[env["cement"]].confirmed is True


@pytest.mark.asyncio
async def test_reparse_rules(async_client, db_session, env):
    offer = await create_offer(async_client, env)
    url = f"/kp-offers/{offer['id']}/parse"
    # Разбор уже в очереди — второй не ставится.
    assert (await async_client.post(url, headers=headers(env, SUPPLY))).status_code == 409
    # Продажи разбор не запускают, чужая роль запроса не видит.
    assert (await async_client.post(url, headers=headers(env, PM))).status_code == 403
    assert (await async_client.post(url, headers=headers(env, CONTRACTOR))).status_code == 404

    no_file = (await upload_offer(async_client, env)).json()
    resp = await async_client.post(f"/kp-offers/{no_file['id']}/parse", headers=headers(env, SUPPLY))
    assert resp.status_code == 422

    stored = await db_session.get(KpOffer, offer["id"])
    stored.parse_status = "parsed"
    request = await db_session.get(KpRequest, env["material"])
    request.status = "done"
    await db_session.commit()
    assert (await async_client.post(url, headers=headers(env, SUPPLY))).status_code == 409


@pytest.mark.asyncio
async def test_guesses_fill_only_empty_fields(async_client, db_session, env, monkeypatch):
    # Поставщик не указан, дата пустая, НДС и ставку человек выбрал сам.
    offer = await create_offer(async_client, env, supplier_name=None, vat_mode="with_vat", vat_rate="22")
    answer = {
        "supplier_guess": "ООО «Сталь-Центр»", "date_guess": "2026-09-11",
        "vat_mode_guess": "without_vat", "vat_rate_guess": 20,
        "includes_materials_guess": True, "prices": [],
    }
    await _run(db_session, monkeypatch, offer["id"], answer=answer)
    stored = await db_session.get(KpOffer, offer["id"])
    assert stored.supplier_name == "ООО «Сталь-Центр»"
    assert str(stored.offer_date) == "2026-09-11"
    # Введённые человеком условия не перетёрты — догадка лежит подсказкой.
    assert stored.vat_mode == "with_vat" and stored.vat_rate == 22
    assert stored.parse_hints["vat_mode"] == "without_vat"
    assert stored.parse_hints["vat_rate"] == 20
    # «Включает материалы» — только для работ.
    assert "includes_materials" not in stored.parse_hints
    assert stored.includes_materials is False

    detail = (await async_client.get(f"/kp-requests/{env['material']}", headers=headers(env, SUPPLY))).json()
    assert detail["offers"][0]["parse_hints"]["vat_rate"] == 20


@pytest.mark.asyncio
async def test_guesses_do_not_overwrite_filled_fields(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env, supplier_name="ООО Металл", offer_date="2026-09-01")
    answer = {"supplier_guess": "ИП Другой", "date_guess": "2026-01-01", "prices": []}
    await _run(db_session, monkeypatch, offer["id"], answer=answer)
    stored = await db_session.get(KpOffer, offer["id"])
    assert stored.supplier_name == "ООО Металл"
    assert str(stored.offer_date) == "2026-09-01"


@pytest.mark.asyncio
async def test_includes_materials_guess_is_only_a_hint_for_work(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env, request_key="work", who=CONTRACTOR, supplier_name="ООО Отделка")
    answer = {"includes_materials_guess": True, "prices": [{"item_id": "1", "unit": "м2", "unit_price": 700}]}
    await _run(db_session, monkeypatch, offer["id"], answer=answer)
    stored = await db_session.get(KpOffer, offer["id"])
    assert stored.includes_materials is False  # отметку ставит человек
    assert stored.parse_hints["includes_materials"] is True
    prices = await _prices(db_session, offer["id"])
    assert prices[env["plaster"]].includes_materials is None


@pytest.mark.asyncio
async def test_bad_guesses_are_ignored(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env, supplier_name=None)
    answer = {"supplier_guess": "   ", "date_guess": "11 сентября", "vat_mode_guess": "maybe",
              "vat_rate_guess": 150, "prices": []}
    await _run(db_session, monkeypatch, offer["id"], answer=answer)
    stored = await db_session.get(KpOffer, offer["id"])
    assert stored.parse_status == "parsed"
    assert stored.supplier_name == "" and stored.offer_date is None
    assert "vat_mode" not in stored.parse_hints and "vat_rate" not in stored.parse_hints


# ---------------------------------------------------------------------------
# Состояние запроса и КП во время разбора
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_completed_meanwhile_writes_nothing(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env)
    request = await db_session.get(KpRequest, env["material"])
    request.status = "done"
    await db_session.commit()
    answer = {"supplier_guess": "ИП Другой", "prices": [{"item_id": "1", "unit": "кг", "unit_price": 45}]}
    await _run(db_session, monkeypatch, offer["id"], answer=answer)
    assert await _prices(db_session, offer["id"]) == {}
    stored = await db_session.get(KpOffer, offer["id"])
    assert stored.parse_status == "failed"
    assert "заверш" in stored.parse_error
    assert stored.supplier_name == "ООО Металл"


@pytest.mark.asyncio
async def test_process_skips_offer_not_queued(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env)
    stored = await db_session.get(KpOffer, offer["id"])
    stored.parse_status = "parsed"
    await db_session.commit()
    fake = await _run(db_session, monkeypatch, offer["id"], answer={"prices": []})
    assert fake.calls == []  # платный вызов не повторяется


@pytest.mark.asyncio
async def test_process_deleted_offer_is_noop(async_client, db_session, env, monkeypatch):
    offer = await create_offer(async_client, env)
    resp = await async_client.delete(f"/kp-offers/{offer['id']}", headers=headers(env, SUPPLY))
    assert resp.status_code == 204
    fake = await _run(db_session, monkeypatch, offer["id"], answer={"prices": []})
    assert fake.calls == []


@pytest.mark.asyncio
async def test_abandoned_parse_becomes_failed_on_read(async_client, db_session, env):
    offer = await create_offer(async_client, env)
    stored = await db_session.get(KpOffer, offer["id"])
    stored.parse_status = "processing"
    stored.parse_started_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    await db_session.commit()

    detail = (await async_client.get(f"/kp-requests/{env['material']}", headers=headers(env, SUPPLY))).json()
    assert detail["offers"][0]["parse_status"] == "failed"
    assert "прервался" in detail["offers"][0]["parse_error"]
    db_session.expire_all()
    stored = await db_session.get(KpOffer, offer["id"])
    assert stored.parse_status == "failed"
    # Брошенный разбор можно запустить заново.
    resp = await async_client.post(f"/kp-offers/{offer['id']}/parse", headers=headers(env, SUPPLY))
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_fresh_processing_is_not_abandoned(async_client, db_session, env):
    offer = await create_offer(async_client, env)
    stored = await db_session.get(KpOffer, offer["id"])
    stored.parse_status = "processing"
    stored.parse_started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db_session.commit()
    detail = (await async_client.get(f"/kp-requests/{env['material']}", headers=headers(env, SUPPLY))).json()
    assert detail["offers"][0]["parse_status"] == "processing"
    resp = await async_client.post(f"/kp-offers/{offer['id']}/parse", headers=headers(env, SUPPLY))
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Файлы: что уходит в ИИ
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("file, blocks, text", [
    pytest.param(("kp.pdf", pdf(), "application/pdf"), ["document"], [], id="pdf-документом"),
    pytest.param(("kp.png", _png(), "image/png"), ["image"], [], id="png-картинкой"),
    pytest.param(("kp.xlsx", _xlsx(), XLSX_MIME), [], ["Арматура А500С d12", "54900", "Прайс"],
                 id="xlsx-текстом"),
])
@pytest.mark.asyncio
async def test_offer_file_goes_to_ai_by_its_type(async_client, db_session, env, claude_api,
                                                 file, blocks, text):
    """PDF уходит документом, картинка — изображением, таблица — текстом; веб-поиска нет."""
    offer = await create_offer(async_client, env, file=file)
    ai = claude_api({"prices": []})

    await kp_parser.process_offer(db_session, offer["id"])

    (call,) = ai.calls
    content = call["messages"][0]["content"]
    sent = [b["type"] for b in content if b.get("type") != "text"] if isinstance(content, list) else []
    assert sent == blocks
    assert all(fragment in prompt_text(call) for fragment in text)
    assert "tools" not in call


def test_spreadsheet_text_is_capped():
    wb = openpyxl.Workbook()
    ws = wb.active
    for i in range(20000):
        ws.append([f"Позиция номер {i} с длинным наименованием", "шт", i])
    buf = io.BytesIO()
    wb.save(buf)
    text = kp_parser.spreadsheet_text(buf.getvalue())
    assert len(text) <= kp_parser.MAX_SHEET_CHARS + 200
    assert "обрезан" in text


def test_broken_spreadsheet_raises_readable_error():
    with pytest.raises(kp_parser.OfferFileError) as exc:
        kp_parser.spreadsheet_text(b"not an excel file")
    assert "XLSX" in str(exc.value)


# ---------------------------------------------------------------------------
# Стоимость: журнал вызовов (правило №13) и parse_cost
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parse_cost_in_call_log(async_client, db_session, env, claude_api):
    """Трата на разбор — в журнале вызовов (идёт в остаток денег) и в `parse_cost` КП."""
    offer = await create_offer(async_client, env)
    claude_api(claude_message({"prices": []}, input_tokens=10_000, output_tokens=1_000))

    await kp_parser.process_offer(db_session, offer["id"])

    db_session.expire_all()
    (log,) = (await db_session.execute(select(ApiCallLog))).scalars().all()
    assert log.task_id is None
    stored = await db_session.get(KpOffer, offer["id"])
    assert stored.parse_status == "parsed"
    # Цены модели закреплены в test_api_cost_pricing.py; здесь — что трата одна и та же.
    assert log.cost_usd > 0
    assert stored.parse_cost == pytest.approx(float(log.cost_usd))
