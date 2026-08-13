"""Позиция, потерянная ИИ, не исчезает молча.

Строки исходной сметы уходят в Claude чанками, и ответ модели — это уже её
пересказ: часть позиций она может не вернуть. Раньше это ничем не проявлялось —
перечень просто оказывался короче сметы, а задача завершалась успешно.

Стало: `attach_source_numbers` возвращает номера позиций исходной сметы, для
которых в ответе ИИ пары не нашлось, а задача пишет о них в ход выполнения.
Автоматически ничего не дописывается: восстановленная позиция с чужим
наименованием хуже видимого предупреждения.

План: plans/2026-08-14-propusk-pozicij-iz-grand-smety.md
"""
from app.utils.source_numbers import attach_source_numbers, lost_positions_warning


def _rows(*pairs) -> list[dict]:
    return [
        {"name": name, "unit": "шт", "quantity": 1.0, "is_section": False, "source_no": no}
        for name, no in pairs
    ]


# ── Что именно потерялось ────────────────────────────────────────────────────

def test_returns_numbers_ai_did_not_return():
    """Позиция сметы, которой нет в ответе ИИ, названа своим номером."""
    items = [{"type": "Работа", "name": "Устройства промежуточные"}]

    lost = attach_source_numbers(items, _rows(
        ("Устройства промежуточные", "2"),
        ("Контроллер Панель-2-ПРО (S3) исп.Л", "3"),
        ("Извещатель ИП 212-141 исп.01", "5"),
    ))

    assert lost == ["3", "5"]


def test_nothing_lost_when_all_positions_returned():
    items = [
        {"type": "Работа", "name": "Устройства промежуточные"},
        {"type": "Материал", "name": "Контроллер Панель-2-ПРО (S3) исп.Л"},
    ]

    lost = attach_source_numbers(items, _rows(
        ("Устройства промежуточные", "2"),
        ("Контроллер Панель-2-ПРО (S3) исп.Л", "3"),
    ))

    assert lost == []


def test_rows_without_numbers_are_not_counted_lost():
    """Файл без нумерации: терять нечего — сверять не с чем."""
    rows = [{"name": "Пробивка гнезд", "unit": "шт", "quantity": 1.0,
             "is_section": False, "source_no": ""}]

    assert attach_source_numbers([], rows) == []


def test_renamed_position_counts_as_found():
    """ИИ обрезал хвост наименования — позиция найдена по началу, не потеряна."""
    items = [{"type": "Материал", "name": "Контроллер радиоканальных устройств"}]

    lost = attach_source_numbers(items, _rows(
        ("Контроллер радиоканальных устройств Панель-2-ПРО (S3) исп.Л", "3"),
    ))

    assert lost == []


# ── Как об этом узнаёт человек ───────────────────────────────────────────────

def test_warning_names_the_numbers():
    text = lost_positions_warning(["3", "5", "7"])

    assert "3 позиции" in text
    assert "№3, №5, №7" in text


def test_warning_uses_singular_for_one():
    assert "1 позицию" in lost_positions_warning(["3"])


def test_warning_lists_at_most_twenty_numbers():
    """Список номеров не должен раздувать строку статуса на весь экран."""
    text = lost_positions_warning([str(n) for n in range(1, 31)])

    assert "30 позиций" in text
    assert "№20" in text
    assert "№21" not in text
    assert "…" in text


def test_no_warning_when_nothing_lost():
    assert lost_positions_warning([]) == ""
