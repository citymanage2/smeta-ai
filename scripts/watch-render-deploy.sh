#!/usr/bin/env bash
# Мониторинг деплоя smeta-ai-backend на Render.
# Ждёт завершения деплоя, проверяет логи на ошибки,
# при ошибках — запускает Claude для автоматического исправления.

SERVICE_ID="srv-d72523oule4c73bg4vqg"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="/tmp/render-watch-$(date +%Y%m%d-%H%M%S).log"
MAX_WAIT=600  # 10 минут максимум

log() {
    echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Мониторинг деплоя запущен. Лог: $LOG_FILE"

# Даём Render время зарегистрировать новый деплой после push
sleep 15

# Получаем ID и статус последнего деплоя
DEPLOY_JSON=$(render deploys list "$SERVICE_ID" --output json --confirm 2>/dev/null)
DEPLOY_ID=$(echo "$DEPLOY_JSON" | jq -r '.[0].id')
DEPLOY_STATUS=$(echo "$DEPLOY_JSON" | jq -r '.[0].status')

log "Деплой: $DEPLOY_ID, статус: $DEPLOY_STATUS"

# Ждём завершения деплоя
ELAPSED=0
while [ "$DEPLOY_STATUS" != "live" ] && [ "$DEPLOY_STATUS" != "failed" ] && [ "$DEPLOY_STATUS" != "canceled" ]; do
    if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
        log "Таймаут ожидания деплоя (${MAX_WAIT}s). Прерываю."
        exit 1
    fi
    sleep 20
    ELAPSED=$((ELAPSED + 20))
    DEPLOY_STATUS=$(render deploys list "$SERVICE_ID" --output json --confirm 2>/dev/null | jq -r '.[0].status')
    log "Статус: $DEPLOY_STATUS (${ELAPSED}s)"
done

# Деплой упал — собираем логи и запускаем Claude
if [ "$DEPLOY_STATUS" = "failed" ] || [ "$DEPLOY_STATUS" = "canceled" ]; then
    log "❌ Деплой упал! Собираю логи..."

    LOGS=$(render logs --resources "$SERVICE_ID" --output text --confirm --limit 100 2>/dev/null)
    echo "$LOGS" >> "$LOG_FILE"

    log "Запускаю Claude для исправления..."
    cd "$REPO_DIR"
    claude --dangerously-skip-permissions -p "Деплой smeta-ai-backend на Render упал со статусом '$DEPLOY_STATUS'.

Последние логи сервиса:
$LOGS

Найди причину ошибки, исправь код в папке backend/, сделай осмысленный git commit и запушь. Не изменяй ничего лишнего."
    exit 0
fi

# Деплой успешен — проверяем логи на ошибки приложения
log "✅ Деплой успешен. Даю сервису 30с запуститься..."
sleep 30

LOGS=$(render logs --resources "$SERVICE_ID" --output text --confirm --limit 60 2>/dev/null)

# Ищем ошибки, игнорируем штатные INFO-строки
ERRORS=$(echo "$LOGS" | grep -iE "(error|exception|traceback|critical|startup failed)" | grep -viE "(alembic\.runtime|migrations applied|no error)" || true)

if [ -n "$ERRORS" ]; then
    log "⚠️ Найдены ошибки после деплоя:"
    echo "$ERRORS" | tee -a "$LOG_FILE"

    cd "$REPO_DIR"
    claude --dangerously-skip-permissions -p "После успешного деплоя smeta-ai-backend на Render в логах найдены ошибки:

$ERRORS

Полный лог запуска:
$LOGS

Проанализируй ошибки, исправь код в папке backend/, сделай осмысленный git commit и запушь."
else
    log "✅ Ошибок не найдено. Деплой прошёл чисто."
fi
