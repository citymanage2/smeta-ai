"""Правила для промпта: включает человек, без правил промпт прежний.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 8.
"""
import pytest
import pytest_asyncio

from app.models.prompt_rule import PromptRule
from app.models.user import User
from app.services import claude_service
from app.services import prompt_rules as svc
from app.services.task_processor import SYSTEM_BASE, TaskProcessor
from app.utils.auth import create_access_token, hash_password


def _auth(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, 'u')}"}


@pytest_asyncio.fixture
async def env(db_session):
    for model in (PromptRule, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()
    head = User(username="head", role="head_of_sales", full_name="Руководитель",
                password_hash=hash_password("p"))
    pm = User(username="pm", role="project_manager", full_name="Менеджер",
              password_hash=hash_password("p"))
    db_session.add_all([head, pm])
    await db_session.commit()
    yield {"head": head.id, "pm": pm.id}
    for model in (PromptRule, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


def test_no_rules_prompt_is_byte_identical():
    """Правил нет — `system` ровно тот же, что до функции. И в batch тоже."""
    before = [{"type": "text", "text": SYSTEM_BASE, "cache_control": {"type": "ephemeral"}}]
    msgs = [{"role": "user", "content": "x"}]

    params = claude_service._build_message_params(msgs, system_prompt=svc.system_for(SYSTEM_BASE, None))
    assert params["system"] == before

    request = claude_service.build_batch_request("c1", msgs, system_prompt=svc.system_for(SYSTEM_BASE, None))
    assert request["params"]["system"] == before


def test_rules_go_as_separate_block_after_base():
    """Правила — вторым блоком; метка кеша одна, на последнем блоке."""
    params = claude_service._build_message_params(
        [{"role": "user", "content": "x"}],
        system_prompt=svc.system_for(SYSTEM_BASE, "ПРАВИЛА"),
    )
    assert params["system"] == [
        {"type": "text", "text": SYSTEM_BASE},
        {"type": "text", "text": "ПРАВИЛА", "cache_control": {"type": "ephemeral"}},
    ]


def test_block_contains_only_enabled_and_applicable_rules():
    rules = [
        PromptRule(id=1, text="Общее правило", scope="ALL", enabled=True),
        PromptRule(id=2, text="Только смета", scope="ESTIMATE_FROM_LIST", enabled=True),
        PromptRule(id=3, text="Выключенное", scope="ALL", enabled=False),
    ]
    estimate = svc.build_block(rules, "ESTIMATE_FROM_LIST")
    listing = svc.build_block(rules, "LIST_FROM_GRAND")

    assert "Общее правило" in estimate and "Только смета" in estimate
    assert "Выключенное" not in estimate
    assert "Только смета" not in listing
    assert svc.build_block([rules[2]], "LIST_FROM_GRAND") is None


@pytest.mark.asyncio
async def test_rules_read_once_per_run(db_session, env):
    """Процессор читает включённые правила в блок и отдаёт их в system."""
    db_session.add(PromptRule(text="Не округляй объём", scope="ALL", enabled=True))
    await db_session.commit()

    processor = TaskProcessor("00000000-0000-0000-0000-000000000000", db_session)
    assert processor._system() == SYSTEM_BASE

    await processor._load_prompt_rules("LIST_FROM_GRAND")
    system = processor._system()
    assert system[0] == SYSTEM_BASE
    assert "Не округляй объём" in system[1]


@pytest.mark.asyncio
async def test_new_rule_is_created_disabled(async_client, env):
    r = await async_client.post("/prompt-rules", json={"text": "Правило"},
                                headers=_auth(env["head"], "head_of_sales"))
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_enable_signs_who_and_when(async_client, env):
    head = _auth(env["head"], "head_of_sales")
    rule_id = (await async_client.post("/prompt-rules", json={"text": "П"}, headers=head)).json()["id"]

    r = await async_client.post(f"/prompt-rules/{rule_id}/enable", headers=head)
    assert r.json()["enabled"] is True
    assert r.json()["enabled_by"] == "Руководитель"
    assert r.json()["enabled_at"]


@pytest.mark.asyncio
async def test_limit_on_active_rules(async_client, db_session, env):
    """Сверх лимита включить нельзя — и отказ объясняет почему."""
    for i in range(svc.MAX_ACTIVE_RULES):
        db_session.add(PromptRule(text=f"п{i}", scope="ALL", enabled=True))
    extra = PromptRule(text="лишнее", scope="ALL", enabled=False)
    db_session.add(extra)
    await db_session.commit()

    r = await async_client.post(f"/prompt-rules/{extra.id}/enable",
                                headers=_auth(env["head"], "head_of_sales"))
    assert r.status_code == 409
    assert "предел" in r.json()["detail"]


@pytest.mark.asyncio
async def test_project_manager_cannot_manage_rules(async_client, env):
    """Правило меняет все расчёты и невидимо в результате — только менеджерам."""
    pm = _auth(env["pm"], "project_manager")
    assert (await async_client.get("/prompt-rules", headers=pm)).status_code == 403
    assert (await async_client.post("/prompt-rules", json={"text": "x"}, headers=pm)).status_code == 403


@pytest.mark.asyncio
async def test_unknown_scope_rejected(async_client, env):
    r = await async_client.post("/prompt-rules", json={"text": "x", "scope": "НЕТ"},
                                headers=_auth(env["head"], "head_of_sales"))
    assert r.status_code == 400
