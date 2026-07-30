import json
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    # Посредник для обхода геоблока Anthropic с РФ-IP.
    #   ANTHROPIC_BASE_URL пусто → SDK идёт напрямую на api.anthropic.com (локально);
    #   задан → трафик через посредника (агрегатор или свой прокси в ЕС).
    ANTHROPIC_BASE_URL: str = ""
    # Только для СВОЕГО прокси: прокидывается как заголовок X-Proxy-Secret,
    # чтобы прокси не был открытым. Агрегатору не нужен — оставить пустым.
    ANTHROPIC_PROXY_SECRET: str = ""
    # Потолок поисков web_search внутри ОДНОГО вызова Claude. Без него модель
    # гоняет поиск сколько сочтёт нужным: за неделю 22% счёта Anthropic ушло на
    # поиск ($35.88 из $161.06 на 28.07.2026), плюс контент страниц оседает в
    # cache_creation-токенах. Снижать до 5 можно через env, без деплоя кода.
    WEB_SEARCH_MAX_USES: int = 8
    # Порог cosine similarity для поиска позиции в локальном прайсе. Ниже порог →
    # больше позиций находится без обращения к Claude (экономия токенов и платных
    # web-поисков), но выше риск подставить цену от похожей, но не той позиции.
    PRICE_SIMILARITY_THRESHOLD: float = 0.78
    OPENAI_API_KEY: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost/smeta_ai"
    JWT_SECRET: str = "changeme-use-strong-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 168  # 7 days
    # DEPRECATED: общий пароль роли user. Вход по общим паролям удалён — поле
    # оставлено лишь для валидации прод-env, значение не используется.
    USER_PASSWORD: str = "user123"
    ADMIN_PASSWORD: str = "admin123"
    # Логин бутстрап-админа: под ним создаётся именованный аккаунт роли admin
    # (ADMIN_USERNAME + ADMIN_PASSWORD). Нужен, чтобы первым войти и завести
    # остальные аккаунты в UI. Он же — владелец архива legacy-данных.
    ADMIN_USERNAME: str = "admin"
    # DEPRECATED: env-сидинг индивидуальных аккаунтов. Аккаунты сотрудников теперь
    # создаются только через админ-панель. Поле оставлено, чтобы прод-env с ним
    # продолжал валидироваться; значение больше не обрабатывается.
    USERS: str = ""
    # Дефолт поднят 20 → 50 в contract-фазе S3 (035): байты файлов идут в S3,
    # а не в буфер соединения PostgreSQL, поэтому старого ограничения BLOB нет.
    MAX_FILE_SIZE_MB: int = 50
    MAX_FILES_PER_REQUEST: int = 10
    TASK_TIMEOUT_SECONDS: int = 600
    CORS_ORIGINS: str = "*"
    VAT_RATE: float = 0.22
    # Наблюдаемость: включает вывод всех SQL-запросов SQLAlchemy в лог (только для отладки).
    SQL_ECHO: bool = False

    # --- Durable-очередь и worker ---
    WORKER_CONCURRENCY: int = 4          # сколько job worker гонит одновременно
    ANTHROPIC_MAX_CONCURRENCY: int = 6   # глобальный семафор вызовов Anthropic (защита от 429)
    FAST_CHUNK_CONCURRENCY: int = 4      # параллельность чанков внутри задачи (было в task_processor)
    JOB_VISIBILITY_TIMEOUT_S: int = 900  # зависшая running-job (без heartbeat) → reclaim
    # Предельный срок на одну пачку чанков (запросы к ИИ). Без него недоступный
    # API растягивает задачу на часы: автоповтор ждёт до RATE_LIMIT_MAX_WAIT на
    # попытку, и это умножается на число чанков. Пачка — до
    # ESTIMATE_MAIN_CHECKPOINT_GROUP=8 запросов при параллельности 4, то есть
    # 2 волны; штатно это минуты, 30 мин — это уже гарантированная поломка.
    CHUNK_STAGE_DEADLINE_S: int = 1800
    JOB_POLL_INTERVAL_S: float = 2.0     # интервал опроса очереди worker'ом
    JOB_MAX_ATTEMPTS: int = 3            # после стольких attempts job → failed
    # Сколько ждём текущие job при SIGTERM. Остаток грейса Timeweb (~30 с) уходит на
    # отмену обработчиков и возврат job в очередь — см. requeue_after_shutdown.
    JOB_DRAIN_TIMEOUT_S: int = 20
    # Задача «в работе» без живой job дольше этого → считается осиротевшей (failed).
    # 30 мин: заведомо больше окна между enqueue и claim даже при полной очереди.
    TASK_ORPHAN_GRACE_S: int = 1800
    # Порог, после которого worker жалуется на память (лог + событие для
    # диагностики в админке). Не ограничивает работу — только делает видимым то,
    # что раньше не измерялось вообще: 29–30.07.2026 спор «4 задачи параллельно
    # или 1» шёл без единой цифры расхода.
    WORKER_RSS_WARN_MB: int = 1024
    # Порог, при котором worker НЕ берёт новую задачу, пока считает хотя бы одну.
    # Адаптивный тормоз вместо жёсткого WORKER_CONCURRENCY: тяжёлые сметы поедут
    # по одной, лёгкие — все 4 слота. Задачи не теряются, ждут в очереди.
    # 0 — тормоз выключен. Должен быть выше WORKER_RSS_WARN_MB, иначе предупреждение
    # теряет смысл (тормоз сработает раньше, чем жалоба).
    WORKER_RSS_PAUSE_MB: int = 1536
    # Пул asyncpg под число слотов (env, чтобы поднять при масштабировании воркеров).
    # Суммарный потолок = (POOL_SIZE + MAX_OVERFLOW) × число процессов.
    # ИЗМЕРЕНО 30.07.2026 кнопкой «Проверить сейчас»: managed-БД разрешает 200
    # соединений, занято 8. Значит прежний отказ `Connection reset by peer` в логе
    # был разовым обрывом, а НЕ исчерпанием лимита — и ужиматься не нужно: слишком
    # маленький пул даёт свою поломку (ожидание соединения по 30 с под нагрузкой).
    # Overflow возвращён к 10; потолок ≈31 из 200 — с большим запасом.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    # Сколько ждать свободного соединения из пула, прежде чем упасть с внятной
    # ошибкой. Без явного значения SQLAlchemy ждёт 30 с молча.
    DB_POOL_TIMEOUT_S: int = 30
    # SSL к managed Postgres (Phase 4 деплоя):
    #   '' → без TLS (локально);
    #   'require' → TLS без проверки серта (достаточно для managed в приватной сети);
    #   'verify-ca'/'verify-full' → TLS с проверкой серта по системным CA.
    DB_SSL_MODE: str = ""

    # --- S3-хранилище файлов (Timeweb Cloud Storage) ---
    # Бинарь файлов хранится в объектном хранилище, в БД — метаданные + storage_key.
    # S3_ENABLED — исторический feature-flag; после contract-фазы (035) S3 —
    # единственный путь, код на флаг больше не смотрит. Поле оставлено, чтобы
    # прод-env `S3_ENABLED=true` продолжал валидироваться (без правки окружения).
    S3_ENABLED: bool = False
    S3_ENDPOINT_URL: str = "https://s3.twcstorage.ru"
    S3_REGION: str = "ru-1"
    S3_BUCKET: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""

    def get_cors_origins(self) -> List[str]:
        try:
            return json.loads(self.CORS_ORIGINS)
        except Exception:
            return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
