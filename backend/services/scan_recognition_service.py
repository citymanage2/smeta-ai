import os
import base64
import json
from pathlib import Path
from typing import Dict, Any, List
import anthropic


SCAN_PROMPT = """Ты — AI-ассистент строительной компании ООО «Сити Менедж», генерального подрядчика полного цикла. \
Твоя задача — распознать скан сметы и перевести его в структурированный формат.

Проанализируй предоставленный скан сметы и выполни следующее:

1. Определи метаданные документа:
   - Тип сметы (локальная, объектная, сводная, КС-2 и т.д.)
   - Наименование объекта
   - Номер сметы
   - Дату
   - Составителя
   - Систему нормирования (ФЕР, ТЕР, ГЭСН, авторская)

2. Извлеки ВСЕ позиции сметы со следующими полями:
   - № п/п (порядковый номер, сохраняй оригинальный)
   - Шифр/код расценки
   - Наименование работ и затрат (полное описание)
   - Единица измерения
   - Объём/количество (числовое значение)
   - Цена за единицу (стоимость без НДС)
   - Сумма (итоговая стоимость позиции)
   - Раздел/подраздел (группировка по видам работ)

3. Зафиксируй итоговые строки:
   - Промежуточные итоги по разделам (subtotal)
   - Накладные расходы (overhead)
   - Сметная прибыль (profit)
   - НДС (vat)
   - Общий итог (grand_total)

ВАЖНЫЕ ПРАВИЛА:
- Если позиция нечитаема, ставь текст "[нечитаемо]" в соответствующее поле и добавь её в unreadable_positions
- Не додумывай данные — переноси только то, что видишь в скане
- Не округляй числа — переноси в том виде, в каком они указаны
- Сохраняй оригинальную нумерацию позиций без переупорядочивания
- Если нет отдельных разделов — помести все позиции в один раздел с name=null

Верни данные ТОЛЬКО в следующем JSON формате без каких-либо дополнительных объяснений:
{
  "metadata": {
    "object_name": "Наименование объекта или null",
    "estimate_number": "Номер сметы или null",
    "date": "Дата или null",
    "author": "Составитель или null",
    "estimate_type": "Тип сметы",
    "normalization_system": "Система нормирования или null"
  },
  "sections": [
    {
      "name": "Наименование раздела или null",
      "items": [
        {
          "number": "1",
          "code": "Шифр/код или null",
          "name": "Наименование работ",
          "unit": "Ед. изм. или null",
          "quantity": 100.0,
          "price_per_unit": 500.0,
          "total": 50000.0,
          "unreadable": false
        }
      ],
      "subtotal": 50000.0
    }
  ],
  "totals": {
    "subtotal": 100000.0,
    "overhead": null,
    "profit": null,
    "vat": null,
    "grand_total": 100000.0
  },
  "summary": {
    "total_positions": 10,
    "total_sections": 2,
    "total_amount": 100000.0,
    "unreadable_positions": []
  }
}"""


class ScanRecognitionService:
    """Сервис для распознавания сканов смет через Claude Vision API"""

    SUPPORTED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}

    def __init__(self):
        self.api_key = os.getenv("CLAUDE_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = os.getenv("CLAUDE_MODEL", "claude-opus-4-5")

    def is_supported_file(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in self.SUPPORTED_EXTENSIONS

    def _prepare_image_content(self, file_path: str) -> List[Dict]:
        """Конвертировать файл в список блоков контента для Claude Vision API"""
        path = Path(file_path)
        ext = path.suffix.lower()
        content = []

        if ext == '.pdf':
            content = self._pdf_to_image_blocks(file_path)
        elif ext in {'.jpg', '.jpeg'}:
            content = [self._file_to_image_block(file_path, 'image/jpeg')]
        elif ext == '.png':
            content = [self._file_to_image_block(file_path, 'image/png')]

        return content

    def _pdf_to_image_blocks(self, file_path: str, max_pages: int = 10) -> List[Dict]:
        """Конвертировать страницы PDF в блоки изображений"""
        try:
            import fitz  # pymupdf
        except ImportError:
            raise RuntimeError("Для обработки PDF необходима библиотека pymupdf")

        doc = fitz.open(file_path)
        blocks = []
        total_pages = min(len(doc), max_pages)

        for page_num in range(total_pages):
            if page_num > 0:
                blocks.append({
                    "type": "text",
                    "text": f"--- Страница {page_num + 1} ---"
                })
            page = doc[page_num]
            mat = fitz.Matrix(2.0, 2.0)  # 2x масштаб для лучшей читаемости
            pix = page.get_pixmap(matrix=mat)
            img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": img_b64
                }
            })

        doc.close()
        return blocks

    def _file_to_image_block(self, file_path: str, media_type: str) -> Dict:
        """Закодировать файл изображения в base64 блок"""
        with open(file_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": img_b64
            }
        }

    def _parse_json_response(self, response_text: str) -> Dict[str, Any]:
        """Извлечь и распарсить JSON из ответа Claude"""
        start_idx = response_text.find('{')
        if start_idx == -1:
            raise ValueError("JSON не найден в ответе Claude")

        json_str = response_text[start_idx:]
        bracket_count = 0
        end_idx = len(json_str)
        for i, char in enumerate(json_str):
            if char in '[{':
                bracket_count += 1
            elif char in ']}':
                bracket_count -= 1
                if bracket_count == 0:
                    end_idx = i + 1
                    break

        return json.loads(json_str[:end_idx])

    def recognize_scan(self, file_path: str) -> Dict[str, Any]:
        """
        Распознать скан сметы и вернуть структурированные данные.

        Args:
            file_path: Путь к файлу скана (PDF, JPG, PNG)

        Returns:
            Словарь со структурированными данными сметы
        """
        content = self._prepare_image_content(file_path)
        content.append({"type": "text", "text": SCAN_PROMPT})

        message = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            messages=[{"role": "user", "content": content}]
        )

        return self._parse_json_response(message.content[0].text)
