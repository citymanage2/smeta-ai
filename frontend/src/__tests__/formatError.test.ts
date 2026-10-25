import { describe, it, expect } from 'vitest';
import { formatTaskError, shortTaskError } from '../utils/formatError';

// Прод 13–14.08.2026: в «Журнале ошибок» четыре записи подряд выглядели как
// «'unit'» — это repr питоновского KeyError. По такой строке не понять ни рода
// ошибки, ни что делать. План: plans/2026-08-18-ponyatnyy-tekst-oshibki.md.
//
// Тесты не сверяют формулировки: текст перевода можно переписать. Проверяется
// разбор — к какой категории отнесена сырая причина. Причины одной категории
// получают одно объяснение, разных категорий — разные. Порядок правил тоже
// здесь: частное раньше общего (403 внутри «Error code» — это ключ, а не общий
// отказ API; ошибка БД со словом connection — это база, а не сеть).

const CATEGORIES: Record<string, Array<string | undefined>> = {
  'нет поля «unit»': ["'unit'", "KeyError: 'unit'", 'KeyError: "unit"'],
  'баланс API': [
    'Error code: 400 - your credit balance is too low',
    'billing: payment required',
  ],
  'доступ по ключу': [
    "Ошибка сборки сметы из batch: Error code: 403 - {'type': 'forbidden'}",
    "Error code: 401 - {'type': 'authentication_error'}",
    'invalid x-api-key',
  ],
  'перегрузка': [
    'Error code: 429 - rate_limit_error',
    "{'type': 'overloaded_error'}",
    'Error code: 529',
  ],
  'таймаут': ['asyncio.TimeoutError', 'Request timed out'],
  'ответ ИИ не разобран': [
    'JSONDecodeError: Expecting value: line 1 column 1 (char 0)',
    'Unterminated string starting at: line 1 column 5',
  ],
  'отказ API': [
    "Error code: 500 - {'type': 'api_error'}",
    "{'type': 'error', 'error': {'type': 'invalid_request_error'}}",
  ],
  'сертификат': [
    'SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed',
    'certificate verify failed: unable to get local issuer certificate',
  ],
  'нет связи': ['APIConnectionError: Connection error.', 'RemoteDisconnected: closed'],
  'база данных': [
    'OperationalError: server closed the connection unexpectedly',
    'asyncpg.exceptions.DeadlockDetectedError: deadlock detected',
  ],
  'файл не xlsx': [
    'BadZipFile: File is not a zip file',
    'InvalidFileException: openpyxl does not support the old .xls format',
  ],
  'память': ['MemoryError'],
  'внутреннее исключение': [
    "TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'",
    "AttributeError: 'NoneType' object has no attribute 'get'",
    'IndexError: list index out of range',
  ],
  'прочее непонятное': ['Something went terribly wrong in module X'],
  'причина не записана': [undefined, '', '   '],
};

const CASES = Object.entries(CATEGORIES).flatMap(
  ([category, raws]) => raws.map((raw) => [category, raw] as const),
);

/** Объяснение категории — по первой её причине. */
const explanationOf = (category: string) => formatTaskError(CATEGORIES[category][0]);

describe('formatTaskError — разбор причины по категориям', () => {
  it.each(CASES)('%s: %j', (category, raw) => {
    expect(formatTaskError(raw)).toBe(explanationOf(category));
  });

  it('у разных категорий разные объяснения', () => {
    const explanations = Object.keys(CATEGORIES).map(explanationOf);
    expect(new Set(explanations).size).toBe(explanations.length);
  });
});

describe('formatTaskError — инварианты', () => {
  const ENGLISH = CASES
    .map(([, raw]) => raw)
    .filter((raw): raw is string => !!raw && raw.trim() !== '');

  it.each(ENGLISH)('сырая причина не выдаётся человеку как есть: %j', (raw) => {
    const text = formatTaskError(raw);
    expect(text).not.toBe(raw);
    expect(text).toMatch(/[а-яё]/i);
  });

  it.each([
    'Баланс API Anthropic исчерпан. Задача продолжится автоматически после пополнения счёта.',
    'Задача остановлена пользователем',
    'Обработка прервана и не возобновилась. Запустите задачу заново.',
  ])('наш русский текст идёт как есть: %j', (ours) => {
    expect(formatTaskError(ours)).toBe(ours);
  });

  it('отсутствующее поле названо: по-человечески, а незнакомое — как есть', () => {
    expect(formatTaskError("'unit'")).toContain('единица измерения');
    expect(formatTaskError("KeyError: 'grand_total'")).toContain('grand_total');
  });

  it.each(["'unit'", 'asyncio.TimeoutError', 'Error code: 429 - rate_limit_error'])(
    'в уведомление идёт начало объяснения, первая фраза: %j',
    (raw) => {
      const full = formatTaskError(raw);
      const short = shortTaskError(raw);
      expect(full.startsWith(short)).toBe(true);
      expect(short.length).toBeLessThan(full.length);
      expect(short).toMatch(/[.!?]$/);
    },
  );

  it('однофразная причина в уведомлении целиком', () => {
    expect(shortTaskError('Задача остановлена пользователем')).toBe('Задача остановлена пользователем');
  });
});
