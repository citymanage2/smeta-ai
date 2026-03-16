import base64
import io
import xml.etree.ElementTree as ET
from typing import Any
import openpyxl
import structlog

logger = structlog.get_logger()


def parse_xlsx(data: bytes) -> str:
    """Convert xlsx bytes to readable text representation."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        result_parts = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            result_parts.append(f"=== Лист: {sheet_name} ===")

            rows_data = []
            for row in ws.iter_rows(values_only=True):
                # Skip completely empty rows
                if all(cell is None for cell in row):
                    continue
                row_str = "\t".join(
                    str(cell) if cell is not None else "" for cell in row
                )
                rows_data.append(row_str)

            result_parts.extend(rows_data)
            result_parts.append("")

        return "\n".join(result_parts)
    except Exception as e:
        logger.error("Failed to parse xlsx", error=str(e))
        return f"[Ошибка при разборе Excel файла: {e}]"


def parse_xml(data: bytes) -> str:
    """Parse XML bytes and return formatted text."""
    try:
        # Try to decode as text first
        text = data.decode("utf-8", errors="replace")
        # Try to parse and re-format if it's valid XML
        try:
            root = ET.fromstring(data)
            return _xml_to_text(root)
        except ET.ParseError:
            return text
    except Exception as e:
        logger.error("Failed to parse XML", error=str(e))
        return f"[Ошибка при разборе XML файла: {e}]"


def _xml_to_text(element: ET.Element, indent: int = 0) -> str:
    """Recursively convert XML element to readable text."""
    prefix = "  " * indent
    parts = []

    tag = element.tag
    # Strip namespace
    if "}" in tag:
        tag = tag.split("}")[1]

    attrs = ""
    if element.attrib:
        attr_parts = [f'{k}="{v}"' for k, v in element.attrib.items()]
        attrs = " " + " ".join(attr_parts)

    text = (element.text or "").strip()

    if text:
        parts.append(f"{prefix}<{tag}{attrs}> {text}")
    else:
        parts.append(f"{prefix}<{tag}{attrs}>")

    for child in element:
        parts.append(_xml_to_text(child, indent + 1))

    return "\n".join(parts)


def file_to_base64(data: bytes, mime_type: str) -> dict:
    """Return a base64-encoded content block suitable for Claude Vision."""
    encoded = base64.b64encode(data).decode("utf-8")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime_type,
            "data": encoded,
        },
    }


def extract_text_from_image_for_claude(data: bytes, mime_type: str) -> dict:
    """Return an image content block for Claude to extract text from."""
    return file_to_base64(data, mime_type)


def pdf_to_content_block(data: bytes) -> dict:
    """Return a PDF document content block for Claude."""
    encoded = base64.b64encode(data).decode("utf-8")
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": encoded,
        },
    }


def parse_file(name: str, mime_type: str, content_b64: str) -> Any:
    """
    Parse a file based on its MIME type.
    Returns either a text string or a content block dict for Claude.
    """
    data = base64.b64decode(content_b64)

    if mime_type in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        return file_to_base64(data, mime_type)

    if mime_type == "application/pdf":
        return pdf_to_content_block(data)

    if mime_type in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ):
        return parse_xlsx(data)

    if mime_type == "text/xml" or mime_type == "application/xml" or name.endswith(".xml"):
        return parse_xml(data)

    # Fallback: try to decode as text
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return f"[Не удалось прочитать файл: {name}]"
