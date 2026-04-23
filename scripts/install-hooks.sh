#!/usr/bin/env bash
# Устанавливает git post-push hook для мониторинга деплоя на Render.
# Запусти один раз: bash scripts/install-hooks.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_PATH="$REPO_ROOT/scripts/watch-render-deploy.sh"
HOOK_FILE="$REPO_ROOT/.git/hooks/post-push"

chmod +x "$SCRIPT_PATH"

cat > "$HOOK_FILE" << EOF
#!/usr/bin/env bash
echo "🚀 Push отправлен. Запускаю мониторинг деплоя Render в фоне..."
nohup "$SCRIPT_PATH" > /dev/null 2>&1 &
echo "📋 Лог появится в /tmp/render-watch-*.log"
EOF

chmod +x "$HOOK_FILE"
echo "✅ Git hook установлен: $HOOK_FILE"
echo "   Теперь после каждого git push — скрипт автоматически следит за деплоем."
