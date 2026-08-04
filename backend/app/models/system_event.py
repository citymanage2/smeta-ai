"""Системные события — то, что происходит в воркере, а показать надо в браузере.

Воркер и web — разные процессы, поэтому событие «баланс API пополнен, задачи
возобновлены» нельзя удержать в памяти: web его не увидит. Плюс пауза по балансу
длится часами, и к моменту восстановления вкладка пользователя почти наверняка
перезагружена (`trackedTasks` во фронте не персистентны). Отсюда — строка в БД
и курсорный опрос `GET /notifications/system?since_id=N`.

Payload намеренно хранит только id задач: названия и права видимости берутся из
актуальной таблицы `tasks` в момент отдачи, поэтому рассинхрона не бывает.

План: plans/2026-07-28-balance-restored-notification.md, Фаза 1.
"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy import JSON as _JSON
from sqlalchemy.dialects.postgresql import JSONB as _JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# JSONB на PostgreSQL, JSON на SQLite (тесты) — как в models/job.py
JSONB = _JSON().with_variant(_JSONB(), "postgresql")

# Виды событий — строкой, а не Enum: добавление нового вида не должно требовать
# миграции.
KIND_BALANCE_RESTORED = "balance_restored"
# Обработчик уперся в память. Пишет worker, читает диагностика в админке: web —
# другой контейнер и память воркера измерить не может, а без цифры спор «сколько
# задач считать параллельно» ведётся вслепую. В поток уведомлений браузера такое
# событие не попадает: там показываются только события с `resumed_task_ids`.
KIND_WORKER_MEMORY_HIGH = "worker_memory_high"
# Обработчик запустился. Пишется при каждом старте процесса — включая тот, что
# случился после OOM-kill. Это единственная надёжная улика смерти контейнера:
# жалоба на память при убийстве процесса не пишется, а лог Timeweb пользователю
# недоступен. Череда таких событий за час = «памяти не хватает на столько задач
# параллельно» (plans/2026-07-30-parallelnaya-obrabotka-umiraet.md).
KIND_WORKER_STARTED = "worker_started"
# Сигнал жизни обработчика не записался в БД. Это ровно то, из-за чего живая
# задача показывает «Обработчик молчит N минут»: сам прогон идёт, а продлить
# `claimed_at` не удалось (пул соединений, обрыв, отказ БД). Ошибку heartbeat
# намеренно не считаем фатальной — но раньше она уходила только в лог контейнера,
# и отличить «обработчик умер» от «heartbeat не пишется» было нельзя.
KIND_WORKER_HEARTBEAT_FAILED = "worker_heartbeat_failed"
# API ответил 429 «слишком часто». Пишется на КАЖДЫЙ такой ответ, без троттлинга:
# здесь нужен счёт, а не «последнее событие» — вопрос ровно в том, сколько раз мы
# упёрлись в лимит. Объём строк ограничен самим клиентом: после 429 корутина спит
# минимум 60 с (RATE_LIMIT_BACKOFF_MINIMUMS), а одновременных вызовов не больше
# ANTHROPIC_MAX_CONCURRENCY. Нужно, чтобы отличить лимит ключа от нехватки
# процессора: до 04.08.2026 такие ответы уходили только в лог контейнера, который
# пользователю недоступен (plans/2026-08-04-schetchik-429-v-adminke.md).
KIND_API_RATE_LIMITED = "api_rate_limited"


class SystemEvent(Base):
    __tablename__ = "system_events"
    __table_args__ = (
        # Под выборку «события вида X новее курсора»: WHERE kind=… AND id > N.
        Index("ix_system_events_kind_id", "kind", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
