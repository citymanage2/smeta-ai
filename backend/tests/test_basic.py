"""Basic smoke tests for Smeta AI backend."""


def test_create_access_token():
    """Test JWT token creation and verification."""
    from app.utils.auth import create_access_token, verify_token
    token = create_access_token(1, "user", "ivan")
    payload = verify_token(token)
    assert payload["role"] == "user"
    assert payload["sub"] == "1"
    assert payload["username"] == "ivan"


def test_normalize_text():
    """Test text normalization for price lookup."""
    from app.services.price_service import normalize_text
    assert normalize_text("  Штукатурка стен  ") == "штукатурка стен"
    assert normalize_text("Ёлка") == "елка"


def test_parse_xlsx_empty():
    """Test xlsx parser with minimal data."""
    import io
    import openpyxl
    from app.utils.file_parser import parse_xlsx

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Test"
    ws["A1"] = "Наименование"
    ws["B1"] = "Количество"
    ws["A2"] = "Бетон М200"
    ws["B2"] = 10

    buf = io.BytesIO()
    wb.save(buf)
    result = parse_xlsx(buf.getvalue())
    assert "Наименование" in result
    assert "Бетон М200" in result


def test_parse_xml():
    """XML сметы с пространством имён: в текст для ИИ идут теги без URI
    пространства, атрибуты и текст позиции — как есть, вложенность — отступом."""
    from app.utils.file_parser import parse_xml

    xml_data = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Smeta xmlns="urn:grandsmeta:2.0">'
        '<Position Number="12" Unit="м3" Quantity="2.164">Разработка грунта</Position>'
        '</Smeta>'
    ).encode("utf-8")

    lines = parse_xml(xml_data).splitlines()

    assert lines[0] == "<Smeta>"
    assert lines[1].startswith("  <Position ")
    assert 'Number="12"' in lines[1]
    assert 'Unit="м3"' in lines[1]
    assert 'Quantity="2.164"' in lines[1]
    assert lines[1].endswith("> Разработка грунта")
    assert len(lines) == 2
