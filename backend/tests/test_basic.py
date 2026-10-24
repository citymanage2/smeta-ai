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
    """Test XML parser."""
    from app.utils.file_parser import parse_xml

    xml_data = '<?xml version="1.0" encoding="UTF-8"?><smeta><item name="test" unit="m2" qty="100" price="500"/></smeta>'.encode("utf-8")
    result = parse_xml(xml_data)
    assert "smeta" in result or "item" in result
