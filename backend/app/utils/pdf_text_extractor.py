import base64

import fitz  # pymupdf
import structlog

logger = structlog.get_logger()

_MIN_WORDS_FOR_TEXT_PAGE = 30


def extract_pdf_hybrid(pdf_bytes: bytes) -> dict:
    """
    Разбирает PDF на текстовые и визуальные страницы.

    Страницы с >= 30 словами embedded-текста → текст.
    Остальные (чертежи, сканы, пустые) → PNG image_block для Claude.

    Возвращает:
        {
            "text_content": "--- Страница 1 ---\\n...",
            "image_pages": [<content_block>, ...]
        }
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_parts: list[str] = []
    image_blocks: list[dict] = []

    for i, page in enumerate(doc):
        text = page.get_text().strip()
        word_count = len(text.split())

        if word_count >= _MIN_WORDS_FOR_TEXT_PAGE:
            text_parts.append(f"--- Страница {i + 1} ---\n{text}")
        else:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            image_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(img_bytes).decode(),
                },
            })

    doc.close()

    return {
        "text_content": "\n\n".join(text_parts),
        "image_pages": image_blocks,
    }
