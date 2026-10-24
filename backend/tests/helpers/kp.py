"""Окружение запроса КП: пользователи, проект, карточка, запросы, позиции, КП.

Зачем. До 25.10.2026 фикстура `env` и помощники `_auth/_wipe/_upload/_offer`
были скопированы в четыре файла (`test_kp_offers`, `test_kp_parser`,
`test_kp_pricelist`, `test_kp_apply`) и уже начали расходиться: где-то пустое
поле формы выкидывалось, где-то — нет, где-то в токене было имя, где-то — нет.

Как пользоваться.

* Фикстура `make_kp_env` — фабрика окружения: `env = await make_kp_env()`.
  Вызов чистит таблицы КП (и связанные: задачи, версии, проекты, пользователи,
  job, журнал вызовов, прайс) и строит мир; после теста чистит снова. Прайс и
  модель эмбеддингов — через `price_db` (запись цен из КП в прайс идёт по
  настоящему пути, векторы не считаются).
* Без параметров — два запроса к одной карточке: `material` (роль снабжения,
  позиции `armature`, `cement`) и `work` (подрядчики, позиция `plaster`),
  статус `new`, источник — перечень. Параметры: `status`, `stage`,
  `source_kind`, `taken=True` (запрос взят в работу снабжением/подрядчиком),
  `items={ключ: KpItem(...)}`, `requests=False` (только пользователи, проект и
  карточка — запросы тест заводит сам).
* `env` — словарь: `env["pm1"]` — id пользователя, `env["material"]` — id
  запроса, `env["armature"]` — id позиции, `env["project"]`, `env["card"]`.
* Заголовки: `headers(env, SUPPLY)` (кортеж «имя, роль») или
  `auth(user_id, role)`.
* Загрузка КП через API: `await upload_offer(client, env, file=..., **поля)` —
  ответ как есть; `await create_offer(client, env, **поля)` — 201 и JSON
  (по умолчанию с одностраничным PDF). Поле `=None` убирает его из формы.
* КП и цена напрямую в БД: `await add_offer(db, request_id, "ООО Металл")`,
  `await add_price(db, offer_id, item_id, 54900, "т")`.
"""
from dataclasses import dataclass
from typing import Optional

import fitz
import pytest_asyncio

from app.models.api_call_log import ApiCallLog
from app.models.correction_signal import CorrectionSignal
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.job import Job
from app.models.kp_request import (
    KpOffer, KpOfferPrice, KpRequest, KpRequestFile, KpRequestItem,
)
from app.models.price import PriceMaterial, PriceWork
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.utils.auth import create_access_token, hash_password

# bcrypt медленный: один хэш на все тесты КП.
PASSWORD_HASH = hash_password("x1234")

# Порядок — от зависимых к основным.
KP_MODELS = (
    KpOfferPrice, KpRequestItem, KpOffer, KpRequestFile, KpRequest,
    CorrectionSignal, TaskHistory, EstimateVersion, WorkflowCard, Task, Project,
    Job, ApiCallLog, PriceWork, PriceMaterial, User,
)

# Кто есть в окружении: имя → роль.
USERS = {
    "pm1": "project_manager",
    "pm2": "project_manager",
    "supply1": "supply_manager",
    "supply2": "supply_manager",
    "contractor1": "contractor_manager",
}

# Кортежи «имя, роль» для headers().
PM = ("pm1", "project_manager")
PM2 = ("pm2", "project_manager")
SUPPLY = ("supply1", "supply_manager")
SUPPLY2 = ("supply2", "supply_manager")
CONTRACTOR = ("contractor1", "contractor_manager")

_ROLE_BY_CATEGORY = {"material": "supply_manager", "work": "contractor_manager"}
_TAKER_BY_CATEGORY = {"material": "supply1", "work": "contractor1"}


@dataclass(frozen=True)
class KpItem:
    """Позиция запроса КП (снимок строки документа)."""

    category: str  # material | work — в какой запрос попадает
    name: str
    unit: Optional[str]
    qty: Optional[float]
    row_id: str


ITEMS = {
    "armature": KpItem("material", "Арматура А500", "кг", 2000, "r1"),
    "cement": KpItem("material", "Цемент М500", "кг", 500, "r2"),
    "plaster": KpItem("work", "Штукатурка стен", "м2", 100, "r3"),
}


def auth(user_id: int, role: str, username: Optional[str] = None) -> dict:
    """Заголовок авторизации для пользователя с этой ролью."""
    token = create_access_token(user_id, role, username or f"u{user_id}")
    return {"Authorization": f"Bearer {token}"}


def headers(env: dict, who: tuple) -> dict:
    """Заголовок для пользователя окружения: `headers(env, SUPPLY)`."""
    name, role = who
    return auth(env[name], role, name)


def pdf(pages: int = 1) -> bytes:
    """Настоящий PDF из `pages` пустых страниц (лимит страниц проверяется по нему)."""
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


async def wipe(db) -> None:
    for model in KP_MODELS:
        await db.execute(model.__table__.delete())
    await db.commit()


async def seed_kp(
    db,
    *,
    status: str = "new",
    stage: str = "list",
    source_kind: str = "list",
    taken: bool = False,
    items: Optional[dict] = None,
    requests: bool = True,
) -> dict:
    """Построить мир КП в БД и вернуть словарь id (см. описание модуля)."""
    users = {
        name: User(username=name, role=role, full_name=name.upper(), is_active=True,
                   password_hash=PASSWORD_HASH)
        for name, role in USERS.items()
    }
    db.add_all(users.values())
    await db.flush()

    project = Project(name="Объект", owner_id=users["pm1"].id)
    db.add(project)
    await db.flush()
    card = WorkflowCard(project_id=str(project.id), name="КР", stage=stage)
    db.add(card)
    await db.flush()

    env: dict = {name: u.id for name, u in users.items()}
    env.update(project=str(project.id), card=str(card.id))
    if not requests:
        await db.commit()
        return env

    by_category = {}
    for category, role in _ROLE_BY_CATEGORY.items():
        request = KpRequest(
            project_id=str(project.id), card_id=str(card.id), source_kind=source_kind,
            category=category, target_role=role, status=status, author_id=users["pm1"].id,
            taken_by_id=users[_TAKER_BY_CATEGORY[category]].id if taken else None,
        )
        db.add(request)
        by_category[category] = request
    await db.flush()

    positions: dict[str, int] = {}
    rows = {}
    for key, item in (items if items is not None else ITEMS).items():
        request = by_category[item.category]
        pos = positions.get(item.category, 0)
        positions[item.category] = pos + 1
        rows[key] = KpRequestItem(
            request_id=request.id, position=pos, item_type=item.category, name=item.name,
            unit=item.unit, qty=item.qty, source_row_ids=[item.row_id],
        )
    db.add_all(rows.values())
    await db.commit()

    env.update({category: str(r.id) for category, r in by_category.items()})
    env.update({key: str(row.id) for key, row in rows.items()})
    return env


@pytest_asyncio.fixture
async def make_kp_env(db_session, fake_s3, price_db):
    """Фабрика окружения запроса КП: `env = await make_kp_env(status="in_progress")`."""

    async def _make(**options) -> dict:
        await wipe(db_session)
        return await seed_kp(db_session, **options)

    yield _make
    await db_session.rollback()
    await wipe(db_session)


# ---------------------------------------------------------------------------
# КП: через API и напрямую в БД
# ---------------------------------------------------------------------------

async def upload_offer(client, env, request_key="material", who=SUPPLY, file=None, **fields):
    """POST /kp-requests/{id}/offers. Поле со значением None убирается из формы."""
    data = {"supplier_name": "ООО Металл", "vat_mode": "with_vat", "vat_rate": "22"}
    data.update(fields)
    data = {k: v for k, v in data.items() if v is not None}
    files = [("file", file)] if file else []
    return await client.post(
        f"/kp-requests/{env[request_key]}/offers", headers=headers(env, who), data=data, files=files,
    )


async def create_offer(client, env, **kw) -> dict:
    """Загрузить КП (по умолчанию — с одностраничным PDF) и вернуть его JSON."""
    kw.setdefault("file", ("kp.pdf", pdf(), "application/pdf"))
    resp = await upload_offer(client, env, **kw)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def add_offer(db, request_id, supplier, *, vat_mode="without_vat", vat_rate=None,
                    includes_materials=False, offer_date=None) -> str:
    """КП в БД мимо API — когда проверяется не загрузка, а то, что с ценами дальше."""
    offer = KpOffer(request_id=request_id, supplier_name=supplier, vat_mode=vat_mode,
                    vat_rate=vat_rate, includes_materials=includes_materials,
                    offer_date=offer_date)
    db.add(offer)
    await db.commit()
    return str(offer.id)


async def add_price(db, offer_id, item_id, price, unit=None, *, confirmed=True,
                    includes_materials=None, source="manual") -> None:
    """Цена позиции в КП: по умолчанию ручная и подтверждённая."""
    db.add(KpOfferPrice(offer_id=offer_id, item_id=item_id, price=price, unit=unit,
                        confirmed=confirmed, includes_materials=includes_materials, source=source))
    await db.commit()
