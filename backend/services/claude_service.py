import os
import json
import base64
from typing import Dict, List, Any, Optional
import anthropic
from pathlib import Path
import pandas as pd

class ClaudeService:
    """Сервис для взаимодействия с Claude API"""

    def __init__(self):
        self.api_key = os.getenv("CLAUDE_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = os.getenv("CLAUDE_MODEL", "claude-opus-4-5")

    def create_list_prompt(self, file_contents: Dict[str, Any], user_comment: Optional[str] = None) -> str:
        """Создать промпт для формирования Перечня работ и материалов"""
        
        files_context = self._format_file_contents(file_contents)
        
        prompt = f"""Ты — опытный инженер-сметчик в строительстве. 
На основании предоставленных документов (ТЗ, проект, спецификации, смета) необходимо составить полный и структурированный Перечень работ и материалов.

Требования:
1. Выдели ВСЕ виды работ и материалов из документов
2. Для каждой позиции определи: тип (Работа или Материал), наименование, единицу измерения, количество
3. Группируй позиции по смысловым разделам, если применимо (например: демонтажные работы, устройство полов, отделка стен и т.д.)
4. Используй стандартные строительные единицы измерения (м², м³, м.п., шт., т, кг, компл.)
5. Если количество не указано явно — укажи, что требует уточнения (поставь null в поле quantity и добавь примечание)
6. Не дублируй позиции
7. Если загружена смета ГрандСмета или ЭДЦ — извлеки позиции напрямую из неё, сохраняя наименования
8. Если загружен проект со спецификацией — используй спецификацию для объёмов в приоритете

Документы:
{files_context}

Комментарий пользователя:
{user_comment or "(нет комментария)"}

Формат ответа: только структурированные данные в JSON следующего вида:
[
  {{
    "type": "Работа" или "Материал",
    "name": "Наименование позиции",
    "unit": "Ед. изм.",
    "quantity": число или null
  }},
  ...
]

Возвращай ТОЛЬКО JSON массив, без дополнительных объяснений."""
        
        return prompt

    def create_estimate_prompt(self, list_content: Dict[str, Any], pricelist_works: str, pricelist_materials: str) -> str:
        """Создать промпт для формирования Сметы"""
        
        list_context = self._format_list_content(list_content)
        
        prompt = f"""Ты — снабженец/сметчик с опытом в строительстве. На основании полученного перечня нужно подготовить полную смету в рекомендуемом качестве для закупки/бюджетирования.

Найди позиции материала и работ в соответствующих прайсах. Проставь цены из прайсов, если такие найдены. В колонку «Наименование в прайсе» поставь найденное наименование из прайса.

Для позиций, которых нет в прайсе, найди цены в интернете:
- Регион: Россия, г. Екатеринбург (Свердловская область)
- Период цен: актуальный на дату выполнения
- Нормальные бренды/класс материалов, квалифицированные подрядчики; без демпинга, сомнительных аналогов и бригад без лицензий/допусков

НДС: показывай отдельно «без НДС / НДС / с НДС».
- Если источник даёт цену без НДС — пересчитай «с НДС» (ставка 22%)
- Для работ: если подрядчик на УСН — укажи это, НДС = 0, но отрази в примечании

Перечень:
{list_context}

Прайс на работы (первые 50 строк):
{pricelist_works[:3000]}

Прайс на материалы (первые 50 строк):
{pricelist_materials[:3000]}

Формат ответа: только JSON-массив:
[
  {{
    "type": "Работа" или "Материал",
    "name": "Наименование",
    "unit": "Ед. изм.",
    "quantity": число,
    "price_work_per_unit": число или null,
    "price_material_per_unit": число или null,
    "name_in_pricelist": "Наименование в прайсе или источник",
    "note": "Примечание (НДС, УСН, источник цены и т.д.)"
  }},
  ...
]

Возвращай ТОЛЬКО JSON массив, без дополнительных объяснений."""
        
        return prompt

    def create_comparison_prompt(self, project_content: str, estimate_content: str) -> str:
        """Создать промпт для сравнительного анализа"""
        
        prompt = f"""Ты — опытный строительный эксперт и сметчик. Проведи детальный сравнительный анализ между проектной документацией (спецификация, ТЗ) и сметой/перечнем работ и материалов.

Задача:
1. Найди позиции, которые есть в проекте, но отсутствуют в смете — потенциальные упущения
2. Найди позиции, которые есть в смете, но не фигурируют в проекте — возможные лишние работы
3. Выяви расхождения в объёмах (количествах) по совпадающим позициям — укажи %, разницу
4. Выяви несоответствия единиц измерения
5. Сформируй список из 5–10 критических замечаний, на которые нужно обратить особое внимание
6. Дай итоговую оценку: насколько смета соответствует проекту (в %)

Проект и спецификация:
{project_content[:2000]}

Смета/Перечень:
{estimate_content[:2000]}

Формат ответа: JSON следующей структуры:
{{
  "missing_in_estimate": [ {{ "name": "...", "unit": "...", "quantity": ..., "note": "..." }} ],
  "extra_in_estimate": [ {{ "name": "...", "unit": "...", "quantity": ..., "note": "..." }} ],
  "quantity_discrepancies": [ {{ "name": "...", "project_qty": ..., "estimate_qty": ..., "diff_pct": ..., "note": "..." }} ],
  "unit_discrepancies": [ {{ "name": "...", "project_unit": "...", "estimate_unit": "...", "note": "..." }} ],
  "critical_notes": [ "...", "...", "..." ],
  "compliance_pct": 85,
  "summary": "Общий текстовый вывод"
}}

Возвращай ТОЛЬКО JSON, без дополнительных объяснений."""
        
        return prompt

    def call_claude(self, prompt: str, max_tokens: int = 8000) -> str:
        """Отправить запрос в Claude и получить ответ"""
        
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2
            )
            
            return message.content[0].text
        except Exception as e:
            raise Exception(f"Ошибка при запросе к Claude: {str(e)}")

    def parse_json_response(self, response: str) -> Dict[str, Any]:
        """Парсить JSON ответ от Claude"""
        
        try:
            # Попытка найти JSON в ответе
            start_idx = response.find('[') if response.find('[') != -1 else response.find('{')
            if start_idx == -1:
                raise ValueError("JSON не найден в ответе")
            
            json_str = response[start_idx:]
            # Найти конец JSON
            bracket_count = 0
            for i, char in enumerate(json_str):
                if char in '[{':
                    bracket_count += 1
                elif char in ']}':
                    bracket_count -= 1
                    if bracket_count == 0:
                        json_str = json_str[:i+1]
                        break
            
            return json.loads(json_str)
        except Exception as e:
            raise Exception(f"Ошибка при парсинге JSON ответа: {str(e)}")

    def _format_file_contents(self, file_contents: Dict[str, Any]) -> str:
        """Форматировать содержимое файлов для промпта"""
        
        result = ""
        for file_name, content in file_contents.items():
            result += f"\n--- Файл: {file_name} ---\n"
            
            if isinstance(content, dict):
                if 'text' in content:
                    result += content['text'][:2000]
                elif 'content' in content:
                    if isinstance(content['content'], str):
                        result += content['content'][:2000]
                    else:
                        result += json.dumps(content['content'], ensure_ascii=False)[:2000]
                else:
                    result += json.dumps(content, ensure_ascii=False)[:2000]
            else:
                result += str(content)[:2000]
        
        return result

    def _format_list_content(self, list_content: Dict[str, Any]) -> str:
        """Форматировать содержимое перечня для промпта"""
        
        if isinstance(list_content, list):
            return json.dumps(list_content, ensure_ascii=False, indent=2)
        elif isinstance(list_content, dict):
            return json.dumps(list_content, ensure_ascii=False, indent=2)
        else:
            return str(list_content)

    def _read_pricelist(self, file_path: str) -> str:
        """Прочитать прайс-лист и вернуть в виде текста"""
        
        if not Path(file_path).exists():
            return "(прайс-лист не найден)"
        
        try:
            # Читаем только первые строки
            df = pd.read_excel(file_path, nrows=100)
            return df.to_string()
        except Exception as e:
            return f"(ошибка при чтении прайс-листа: {str(e)})"
