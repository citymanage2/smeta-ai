/**
 * Причина падения задачи — словами, а не `repr` исключения.
 *
 * В базе лежит оригинал: по нему группируется журнал ошибок и ведётся
 * диагностика. Человеку показывается перевод — что случилось и что делать;
 * оригинал остаётся рядом, под «Подробности» и в кнопке «Копировать».
 *
 * Разбор идёт по признакам исключения, а не по длине строки: «'unit'» — это
 * `KeyError('unit')`, шесть символов, и прежнее правило «короткое — покажем как
 * есть» выводило в журнал ровно эти шесть символов.
 *
 * Порядок правил значим и закреплён тестами: частное раньше общего. Ошибка
 * базы данных содержит слово connection, но чинится не «попробуйте ещё раз»;
 * отказ по ключу приходит как «Error code: 403» и не должен читаться как общая
 * «ошибка сервиса». Кириллица — последним: русский текст пишем мы сами, и
 * переводить его не нужно.
 */

const CYRILLIC = /[а-яёА-ЯЁ]/;

/** Поля данных, которые человек знает по названию в таблице. */
const FIELD_NAMES: Record<string, string> = {
  unit: 'единица измерения',
  name: 'наименование',
  quantity: 'объём',
  qty: 'объём',
  price: 'цена',
  price_work: 'цена работы',
  price_material: 'цена материала',
  type: 'тип позиции',
  items: 'позиции',
  sheet: 'лист файла',
  total: 'сумма',
};

/** Отсутствующее поле: «KeyError: 'unit'» и наследие в виде голого «'unit'». */
const MISSING_FIELD = /\bKeyError\b\s*:?\s*['"]([^'"]+)['"]/;
const BARE_KEY = /^['"]([A-Za-z_][A-Za-z0-9_]*)['"]$/;

/** Внутренние исключения Python: сбой сервиса, а не действие пользователя. */
const PYTHON_EXCEPTION =
  /\b(TypeError|AttributeError|IndexError|ValueError|ZeroDivisionError|UnboundLocalError|NameError|RecursionError|AssertionError|StopIteration|StopAsyncIteration|OverflowError|NotImplementedError)\b/;

export function formatTaskError(msg: string | undefined | null): string {
  const raw = (msg ?? '').trim();
  if (!raw) {
    return 'Задача остановилась, но причина не записана. Запустите её заново — если повторится, сообщите разработчику.';
  }

  const lower = raw.toLowerCase();

  // Наши сообщения о балансе и остановке — со своими указаниями, что делать.
  // Их правила ниже узнали бы по латинским словам и перебили бы своим текстом.
  if (
    lower.includes('баланс api') ||
    lower.includes('задача остановлена') ||
    lower.includes('администратор') ||
    lower.includes('обратитесь')
  ) {
    return raw;
  }

  // Не хватило поля в данных задачи.
  const field = MISSING_FIELD.exec(raw)?.[1] ?? BARE_KEY.exec(raw)?.[1];
  if (field) {
    const human = FIELD_NAMES[field] ?? field;
    return (
      `Внутренняя ошибка сервиса: в данных задачи нет поля «${human}». ` +
      'Задача остановлена, чтобы не выдать неверную смету. Сообщите разработчику.'
    );
  }

  // Деньги и доступ — чинит администратор, перезапуск не поможет.
  if (lower.includes('credit balance') || lower.includes('billing')) {
    return 'Баланс API Anthropic исчерпан. Обратитесь к администратору сервиса.';
  }
  if (
    /error code: 40[13]\b/.test(lower) ||
    lower.includes('authentication_error') ||
    lower.includes('permission_error') ||
    lower.includes('forbidden') ||
    lower.includes('invalid x-api-key')
  ) {
    return 'ИИ-сервис отклонил запрос: нет доступа по ключу. Обратитесь к администратору сервиса.';
  }

  // Перегрузка и таймаут — проходят сами, задачу нужно просто повторить.
  if (
    lower.includes('rate limit') ||
    lower.includes('rate_limit') ||
    lower.includes('too many requests') ||
    lower.includes('overloaded') ||
    /error code: (429|529)\b/.test(lower)
  ) {
    return 'ИИ-сервис перегружен запросами. Подождите несколько минут и запустите задачу заново.';
  }
  if (lower.includes('timeout') || lower.includes('timed out')) {
    return 'Превышено время ожидания ответа от ИИ. Запустите задачу заново.';
  }

  // Ответ ИИ пришёл, но не разобрался.
  if (
    lower.includes('jsondecodeerror') ||
    lower.includes('expecting value') ||
    lower.includes('unterminated string') ||
    lower.includes('validationerror')
  ) {
    return 'ИИ вернул ответ в неожиданном формате — разобрать его не удалось. Запустите задачу заново.';
  }

  // Файл заказчика — единственное, что человек чинит сам.
  if (
    lower.includes('badzipfile') ||
    lower.includes('not a zip file') ||
    lower.includes('invalidfileexception') ||
    lower.includes('openpyxl') ||
    lower.includes('xlrd') ||
    lower.includes('filenotfounderror')
  ) {
    return (
      'Файл не читается как xlsx: он повреждён или сохранён в другом формате. ' +
      'Пересохраните его в Excel и загрузите заново.'
    );
  }

  if (lower.includes('memoryerror')) {
    return (
      'Не хватило памяти на обработку файла — он слишком большой. ' +
      'Разбейте смету на части или обратитесь к администратору.'
    );
  }

  // База данных раньше сети: её ошибка тоже говорит про connection.
  if (
    lower.includes('operationalerror') ||
    lower.includes('integrityerror') ||
    lower.includes('interfaceerror') ||
    lower.includes('sqlalchemy') ||
    lower.includes('asyncpg') ||
    lower.includes('psycopg') ||
    lower.includes('deadlock')
  ) {
    return 'Ошибка базы данных. Запустите задачу заново — если повторится, обратитесь к администратору.';
  }

  // Сертификат раньше сети: перезапуск не поможет, нужен администратор сервера.
  if (
    lower.includes('certificate_verify_failed') ||
    lower.includes('certificate verify failed') ||
    lower.includes('sslcertverificationerror') ||
    lower.includes('ssl:')
  ) {
    return (
      'Не удалось установить защищённое соединение с ИИ-сервисом: не проверился сертификат. ' +
      'Обратитесь к администратору сервиса.'
    );
  }
  if (
    lower.includes('connection') ||
    lower.includes('remotedisconnected') ||
    lower.includes('remoteprotocol') ||
    lower.includes('network')
  ) {
    return 'Не удалось связаться с ИИ-сервисом. Запустите задачу заново — если повторится, обратитесь к администратору.';
  }

  if (lower.includes('cancellederror') || lower.includes('keyboardinterrupt')) {
    return 'Обработка была прервана. Запустите задачу заново.';
  }

  // Прочий отказ API: тип ошибки нам ничего не говорит, но источник известен.
  if (
    raw.includes("'type': 'error'") ||
    raw.includes('"type": "error"') ||
    lower.includes('error code:') ||
    lower.includes('invalid_request_error') ||
    lower.includes('api_error')
  ) {
    return 'Ошибка на стороне ИИ-сервиса. Запустите задачу заново — если повторится, обратитесь к администратору.';
  }

  if (PYTHON_EXCEPTION.test(raw)) {
    return (
      'Внутренняя ошибка сервиса при обработке данных. Задача остановлена. ' +
      'Запустите её заново — если повторится, сообщите разработчику, приложив подробности.'
    );
  }

  // Русский текст — наш, написан для человека.
  if (CYRILLIC.test(raw)) return raw;

  return 'Внутренняя ошибка сервиса. Задача остановлена. Сообщите разработчику, приложив подробности.';
}

/**
 * Первая фраза причины — для всплывающего и системного уведомления.
 *
 * Там видно одну строку и шесть секунд: полный текст с указанием, что делать,
 * обрезается на середине. Что делать — написано в карточке, куда ведёт
 * уведомление; в самом уведомлении важно только «что случилось».
 */
export function shortTaskError(msg: string | undefined | null): string {
  const full = formatTaskError(msg);
  const end = full.search(/[.!?](\s|$)/);
  return end === -1 ? full : full.slice(0, end + 1);
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
