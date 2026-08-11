"""Предохранитель на дообучении модели эмбеддингов.

План: plans/2026-08-07-obuchenie-na-korrektirovkah.md, Фаза 6 (подготовка).

Зачем предохранитель: обучение сохраняет модель в `/tmp/smeta-finetuned`, а на
Timeweb постоянных томов нет — при перезапуске контейнера она исчезает. Но
эмбеддинги всего прайса к тому моменту уже пересчитаны ею и остаются в базе.
Дальше поиск цен сравнивает векторы, посчитанные разными моделями, — величины
несопоставимые, и подбор цены деградирует, ничем этого не показывая.

Поэтому запуск закрыт в двух местах: в роутере и в самом обработчике задания
(задание могло встать в очередь, пока обучение было открыто). Разметка пар при
этом работает — они копятся и не пропадают.
"""
import uuid

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.training_job import TrainingJob
from app.models.training_pair import TrainingPair


@pytest.mark.asyncio
async def test_train_is_closed_while_model_has_nowhere_to_live(
    async_client, admin_token, db_session
):
    """Запуск обучения отклоняется, и в ответе — причина по-человечески."""
    assert settings.RETRAINING_ENABLED is False

    r = await async_client.post(
        "/retraining/train", headers={"Authorization": admin_token})

    assert r.status_code == 409, r.text
    assert "перезапуск" in r.json()["detail"]

    # Задание не создано: очередь не должна копить то, что не выполнится.
    jobs = await db_session.execute(select(TrainingJob))
    assert jobs.scalars().all() == []


@pytest.mark.asyncio
async def test_queued_job_is_rejected_by_the_handler_too(async_client, db_session):
    """Второй рубеж: задание из очереди тоже не запустит обучение.

    Оно могло встать в очередь, пока обучение было открыто, и дождаться
    выполнения уже после того, как его закрыли.
    """
    from app.services import retraining_service

    job = TrainingJob(id=uuid.uuid4(), status="pending", pairs_count=0)
    db_session.add(job)
    await db_session.commit()

    await retraining_service.run_training_job(str(job.id), db_session)

    refreshed = await db_session.get(TrainingJob, job.id)
    assert refreshed.status == "failed"
    assert "перезапуск" in (refreshed.error or "")


@pytest.mark.asyncio
async def test_pairs_are_still_collected(async_client, admin_token, db_session):
    """Разметка пар не закрыта: знание копится, обучение подождёт."""
    r = await async_client.post(
        "/retraining/pairs",
        json={
            "anchor_text": "Разработка грунта вручную",
            "candidate_text": "Разработка грунта",
            "candidate_type": "work",
            "is_positive": True,
            "similarity_score": 0.91,
        },
        headers={"Authorization": admin_token},
    )
    assert r.status_code == 200, r.text

    pairs = await db_session.execute(select(TrainingPair))
    assert len(pairs.scalars().all()) == 1

    stats = await async_client.get(
        "/retraining/stats", headers={"Authorization": admin_token})
    assert stats.status_code == 200
    assert stats.json()["retraining_enabled"] is False
