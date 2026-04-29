/**
 * Converts a raw task error_message (may contain JSON/English API errors) into
 * a user-friendly Russian string.
 */
export function formatTaskError(msg: string | undefined): string {
  if (!msg) return 'Произошла ошибка при обработке задачи. Попробуйте ещё раз.';

  const lower = msg.toLowerCase();

  // Already friendly Cyrillic messages — pass through as-is
  if (
    lower.includes('баланс api') ||
    lower.includes('задача остановлена') ||
    lower.includes('администратор') ||
    lower.includes('обратитесь')
  ) {
    return msg;
  }

  // Anthropic billing
  if (lower.includes('credit balance') || lower.includes('billing')) {
    return 'Баланс API Anthropic меньше 0. Обратитесь к администратору сервиса.';
  }

  // Timeout / processing took too long
  if (lower.includes('timeout') || lower.includes('timed out') || lower.includes('asyncio.timeouterror')) {
    return 'Превышено время ожидания ответа от AI. Попробуйте ещё раз.';
  }

  // Rate limit
  if (lower.includes('rate limit') || lower.includes('too many requests') || lower.includes('ratelimit')) {
    return 'AI-сервис перегружен запросами. Подождите немного и попробуйте ещё раз.';
  }

  // Connection / network errors
  if (lower.includes('connection') || lower.includes('remotedisconnected') || lower.includes('remoteprotocol')) {
    return 'Ошибка соединения с AI-сервисом. Попробуйте ещё раз.';
  }

  // Raw JSON / API error objects from Anthropic
  if (
    msg.includes("'type': 'error'") ||
    msg.includes('"type": "error"') ||
    msg.includes('Error code:') ||
    msg.includes('invalid_request_error') ||
    msg.includes('overloaded_error') ||
    msg.includes('api_error')
  ) {
    return 'Ошибка AI-сервиса. Обратитесь к администратору.';
  }

  // Message is in English without Cyrillic — likely a raw exception, hide it
  const hasCyrillic = /[а-яёА-ЯЁ]/.test(msg);
  if (!hasCyrillic && msg.length > 10) {
    return 'Произошла ошибка при обработке задачи. Попробуйте ещё раз или обратитесь к администратору.';
  }

  return msg;
}

/**
 * Converts a FastAPI `detail` field into a user-friendly message.
 * If detail is in English (auto-generated validation), shows the fallback instead.
 */
export function formatApiDetail(detail: string | undefined, fallback: string): string {
  if (!detail) return fallback;
  const hasCyrillic = /[а-яёА-ЯЁ]/.test(detail);
  return hasCyrillic ? detail : fallback;
}
