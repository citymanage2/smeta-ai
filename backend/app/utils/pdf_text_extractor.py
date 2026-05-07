import base64

import fitz  # pymupdf
import structlog

logger = structlog.get_logger()

_MIN_WORDS_FOR_TEXT_PAGE = 30
_PROJECT_TEXT_CHUNK_CHARS = 40_000


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


def chunk_project_pdf(pdf_bytes: bytes) -> list[dict]:
    """Разбивает проектный PDF на чанки для обработки по частям.

    Каждый чанк: {"text": str, "image_pages": list}.
    Изображения (чертежи) включаются в каждый чанк — они нужны для определения объёмов
    вне зависимости от того, в какой части текста идёт ссылка на чертёж.

    Если суммарный текст короткий (<= _PROJECT_TEXT_CHUNK_CHARS), возвращает один чанк.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_pages: list[str] = []
    image_blocks: list[dict] = []

    for i, page in enumerate(doc):
        text = page.get_text().strip()
        word_count = len(text.split())

        if word_count >= _MIN_WORDS_FOR_TEXT_PAGE:
            text_pages.append(f"--- Страница {i + 1} ---\n{text}")
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

    full_text = "\n\n".join(text_pages)

    if len(full_text) <= _PROJECT_TEXT_CHUNK_CHARS:
        return [{"text": full_text, "image_pages": image_blocks}]

    # Разбиваем текстовые страницы на чанки по ~_PROJECT_TEXT_CHUNK_CHARS символов
    chunks: list[dict] = []
    current_parts: list[str] = []
    current_len = 0

    for page_text in text_pages:
        current_parts.append(page_text)
        current_len += len(page_text)
        if current_len >= _PROJECT_TEXT_CHUNK_CHARS:
            chunks.append({"text": "\n\n".join(current_parts), "image_pages": image_blocks})
            current_parts = []
            current_len = 0

    if current_parts:
        chunks.append({"text": "\n\n".join(current_parts), "image_pages": image_blocks})

    return chunks
