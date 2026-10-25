"""Правила для промпта: включает человек, без правил промпт прежний.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 8.

`system` проверяется в настоящем запросе к Anthropic — том, что уходит из
расчёта сметы (обычный вызов и пачка Batch API), а не в сборке параметров.
"""
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.models.prompt_rule import PromptRule
from app.models.user import User
from app.services import prompt_rules as svc
from app.services.task_processor import SYSTEM_BASE
from app.utils.auth import create_access_token, hash_password
from tests.helpers.anthropic_api import ClaudeScript, claude_message


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


# Позиции нет в прайсе — смета спрашивает её цену у ИИ.
ITEM = {"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30}
ANSWER = {"items": [{"id": 0, "type": "Материал", "name": "Смеси сухие", "unit": "кг",
                     "material_price": 70.0, "sources": "источник"}]}


class _Anthropic:
    """Клиент Anthropic: обычные вызовы — по сценарию, пачки Batch API — запоминает."""

    def __init__(self, script: ClaudeScript):
        self.script = script
        self.batches: list[list] = []

    async def create_batch(self, *, requests):
        self.batches.append(list(requests))
        return SimpleNamespace(id="msgbatch_test")

    def systems(self) -> list:
        """`system` каждого ушедшего запроса: сначала обычные вызовы, потом пачки."""
        return [call.get("system") for call in self.script.calls] + [
            request["params"].get("system") for batch in self.batches for request in batch
        ]


@pytest.fixture
def anthropic(patch_claude_create):
    def _install(*steps) -> _Anthropic:
        api = _Anthropic(ClaudeScript(steps))
        client = patch_claude_create(api.script.create)
        client.messages.batches = SimpleNamespace(create=api.create_batch)
        return api

    return _install


async def _estimate(processor_env, mode: str = "fast"):
    task = await processor_env.estimate_task([ITEM], processing_mode=mode)
    return await processor_env.run(task)


@pytest.mark.parametrize("mode", ["fast", "batch"])
async def test_no_rules_prompt_is_byte_identical(processor_env, anthropic, env, mode):
    """Правил нет — `system` ровно тот же, что до функции: основной промпт одним
    блоком с меткой кеша. И в пачке Batch API тоже."""
    api = anthropic(ANSWER)

    await _estimate(processor_env, mode)

    assert api.systems() == [
        [{"type": "text", "text": SYSTEM_BASE, "cache_control": {"type": "ephemeral"}}],
    ]


@pytest.mark.parametrize("mode", ["fast", "batch"])
async def test_rules_go_as_separate_block_after_base(processor_env, anthropic, db_session, env, mode):
    """Правила — вторым блоком; метка кеша одна, на последнем блоке."""
    db_session.add(PromptRule(text="Не округляй объём", scope="ALL", enabled=True))
    await db_session.commit()
    api = anthropic(ANSWER)

    await _estimate(processor_env, mode)

    (system,) = api.systems()
    base, rules = system
    assert base == {"type": "text", "text": SYSTEM_BASE}
    assert "Не округляй объём" in rules["text"]
    assert rules["cache_control"] == {"type": "ephemeral"}


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


async def test_rules_read_once_per_run(processor_env, anthropic, db_session, env):
    """Правило, включённое посреди расчёта, ждёт следующего: один расчёт — один промпт."""
    db_session.add(PromptRule(text="Не округляй объём", scope="ALL", enabled=True))
    await db_session.commit()

    async def skip_and_enable_second_rule(kwargs):
        db_session.add(PromptRule(text="Бери цены Екатеринбурга", scope="ALL", enabled=True))
        await db_session.commit()
        return claude_message({"items": []})  # позиция пропущена — будет повторный запрос

    api = anthropic(skip_and_enable_second_rule, ANSWER)

    task = await _estimate(processor_env)

    assert task.status == "completed"
    first, second = api.systems()
    assert second == first
    assert "Не округляй объём" in first[1]["text"]
    assert "Екатеринбурга" not in json.dumps(second, ensure_ascii=False)


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
