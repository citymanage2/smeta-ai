import { describe, it, expect } from 'vitest';
import { formatTaskError, shortTaskError } from '../utils/formatError';

// Прод 13–14.08.2026: в «Журнале ошибок» четыре записи подряд выглядели как
// «'unit'» — это repr питоновского KeyError. По такой строке не понять ни рода
// ошибки, ни что делать. План: plans/2026-08-18-ponyatnyy-tekst-oshibki.md.
describe('formatTaskError — падение на данных', () => {
  it('голое repr KeyError переводится с расшифровкой поля', () => {
    expect(formatTaskError("'unit'")).toBe(
      'Внутренняя ошибка сервиса: в данных задачи нет поля «единица измерения». ' +
        'Задача остановлена, чтобы не выдать неверную смету. Сообщите разработчику.'
    );
  });

  it('KeyError с типом исключения переводится так же', () => {
    expect(formatTaskError("KeyError: 'unit'")).toBe(formatTaskError("'unit'"));
  });

  it('незнакомое поле называется как есть, а не прячется', () => {
    expect(formatTaskError("KeyError: 'grand_total'")).toContain('«grand_total»');
  });

  it('прочие внутренние исключения Python не выдаются за ошибку пользователя', () => {
    const text = formatTaskError(
      "TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'"
    );
    expect(text).toBe(
      'Внутренняя ошибка сервиса при обработке данных. Задача остановлена. ' +
        'Запустите её заново — если повторится, сообщите разработчику, приложив подробности.'
    );
    expect(formatTaskError("AttributeError: 'NoneType' object has no attribute 'get'")).toBe(text);
    expect(formatTaskError('IndexError: list index out of range')).toBe(text);
  });
});

describe('formatTaskError — ИИ-сервис', () => {
  it('исчерпанный баланс', () => {
    expect(formatTaskError('Error code: 400 - your credit balance is too low')).toBe(
      'Баланс API Anthropic исчерпан. Обратитесь к администратору сервиса.'
    );
  });

  it('отказ по ключу важнее общего «ошибка сервиса»', () => {
    expect(formatTaskError("Ошибка сборки сметы из batch: Error code: 403 - {'type': 'forbidden'}")).toBe(
      'ИИ-сервис отклонил запрос: нет доступа по ключу. Обратитесь к администратору сервиса.'
    );
  });

  it('перегрузка и лимит запросов', () => {
    const text = 'ИИ-сервис перегружен запросами. Подождите несколько минут и запустите задачу заново.';
    expect(formatTaskError('Error code: 429 - rate_limit_error')).toBe(text);
    expect(formatTaskError("{'type': 'overloaded_error'}")).toBe(text);
  });

  it('таймаут', () => {
    expect(formatTaskError('asyncio.TimeoutError')).toBe(
      'Превышено время ожидания ответа от ИИ. Запустите задачу заново.'
    );
  });

  it('неразобранный ответ ИИ', () => {
    expect(formatTaskError('JSONDecodeError: Expecting value: line 1 column 1 (char 0)')).toBe(
      'ИИ вернул ответ в неожиданном формате — разобрать его не удалось. Запустите задачу заново.'
    );
  });

  it('прочая ошибка API', () => {
    expect(formatTaskError("Error code: 500 - {'type': 'api_error'}")).toBe(
      'Ошибка на стороне ИИ-сервиса. Запустите задачу заново — если повторится, обратитесь к администратору.'
    );
  });
});

describe('formatTaskError — окружение', () => {
  it('сертификат отделён от обычного обрыва связи: чинит его администратор', () => {
    expect(
      formatTaskError('SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed')
    ).toBe(
      'Не удалось установить защищённое соединение с ИИ-сервисом: не проверился сертификат. ' +
        'Обратитесь к администратору сервиса.'
    );
  });

  it('обрыв связи', () => {
    expect(formatTaskError('APIConnectionError: Connection error.')).toBe(
      'Не удалось связаться с ИИ-сервисом. Запустите задачу заново — если повторится, обратитесь к администратору.'
    );
  });

  it('база данных', () => {
    expect(formatTaskError('OperationalError: server closed the connection unexpectedly')).toBe(
      'Ошибка базы данных. Запустите задачу заново — если повторится, обратитесь к администратору.'
    );
  });

  it('битый xlsx — единственная ошибка, которую чинит сам пользователь', () => {
    const text =
      'Файл не читается как xlsx: он повреждён или сохранён в другом формате. ' +
      'Пересохраните его в Excel и загрузите заново.';
    expect(formatTaskError('BadZipFile: File is not a zip file')).toBe(text);
    expect(formatTaskError('InvalidFileException: openpyxl does not support the old .xls format')).toBe(text);
  });

  it('нехватка памяти', () => {
    expect(formatTaskError('MemoryError')).toBe(
      'Не хватило памяти на обработку файла — он слишком большой. ' +
        'Разбейте смету на части или обратитесь к администратору.'
    );
  });
});

describe('formatTaskError — наши сообщения', () => {
  it('русский текст идёт как есть', () => {
    const ours = 'Баланс API Anthropic исчерпан. Задача продолжится автоматически после пополнения счёта.';
    expect(formatTaskError(ours)).toBe(ours);
    expect(formatTaskError('Задача остановлена пользователем')).toBe('Задача остановлена пользователем');
    expect(formatTaskError('Обработка прервана и не возобновилась. Запустите задачу заново.')).toBe(
      'Обработка прервана и не возобновилась. Запустите задачу заново.'
    );
  });

  it('пустая причина не показывается пустым местом', () => {
    expect(formatTaskError(undefined)).toBe(
      'Задача остановилась, но причина не записана. Запустите её заново — если повторится, сообщите разработчику.'
    );
    expect(formatTaskError('   ')).toBe(formatTaskError(undefined));
  });

  it('в уведомление идёт первая фраза — что случилось, без «что делать»', () => {
    expect(shortTaskError("'unit'")).toBe(
      'Внутренняя ошибка сервиса: в данных задачи нет поля «единица измерения».'
    );
    expect(shortTaskError('asyncio.TimeoutError')).toBe('Превышено время ожидания ответа от ИИ.');
    expect(shortTaskError('Задача остановлена пользователем')).toBe('Задача остановлена пользователем');
  });

  it('незнакомый английский текст не выдаётся пользователю сырым', () => {
    expect(formatTaskError('Something went terribly wrong in module X')).toBe(
      'Внутренняя ошибка сервиса. Задача остановлена. Сообщите разработчику, приложив подробности.'
    );
  });
});
