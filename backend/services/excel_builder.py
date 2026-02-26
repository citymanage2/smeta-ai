import io
from datetime import datetime
from typing import List, Dict, Any
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

class ExcelBuilder:
    """Построитель Excel файлов"""

    def __init__(self):
        self.thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )

    def create_list_workbook(self, data: List[Dict[str, Any]]) -> bytes:
        """Создать Excel файл с Перечнем работ и материалов"""
        
        wb = Workbook()
        
        # Лист 1: Полный перечень
        ws_all = wb.active
        ws_all.title = "Перечень работ и материалов"
        self._create_list_sheet(ws_all, data)
        
        # Лист 2: Только работы
        works = [item for item in data if item.get('type') == 'Работа']
        ws_works = wb.create_sheet("Перечень работ")
        self._create_works_sheet(ws_works, works)
        
        # Лист 3: Только материалы
        materials = [item for item in data if item.get('type') == 'Материал']
        ws_materials = wb.create_sheet("Перечень материалов")
        self._create_materials_sheet(ws_materials, materials)
        
        # Сохранить в памяти
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue()

    def create_estimate_workbook(self, data: List[Dict[str, Any]]) -> bytes:
        """Создать Excel файл со сметой"""
        
        wb = Workbook()
        
        # Лист 1: Полная смета
        ws_all = wb.active
        ws_all.title = "Перечень работ и материалов"
        self._create_estimate_sheet(ws_all, data)
        
        # Лист 2: Только работы
        works = [item for item in data if item.get('type') == 'Работа']
        ws_works = wb.create_sheet("Перечень работ")
        self._create_estimate_works_sheet(ws_works, works)
        
        # Лист 3: Только материалы
        materials = [item for item in data if item.get('type') == 'Материал']
        ws_materials = wb.create_sheet("Перечень материалов")
        self._create_estimate_materials_sheet(ws_materials, materials)
        
        # Сохранить в памяти
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue()

    def _create_list_sheet(self, ws, data: List[Dict[str, Any]]):
        """Создать лист с Перечнем"""
        
        # Заголовок
        headers = ["№ п/п", "Работа/Материал", "Наименование", "Ед. изм.", "Кол-во"]
        ws.append(headers)
        
        # Форматирование заголовка
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
        # Данные
        for idx, item in enumerate(data, 1):
            ws.append([
                idx,
                item.get('type', ''),
                item.get('name', ''),
                item.get('unit', ''),
                item.get('quantity', '')
            ])
            
            # Чередующаяся заливка
            if idx % 2 == 0:
                for cell in ws[idx + 1]:
                    cell.fill = PatternFill(start_color="F0F0F0", end_color="F0F0F0", fill_type="solid")
            
            # Границы
            for cell in ws[idx + 1]:
                cell.border = self.thin_border
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        
        # Установить ширину колонок
        ws.column_dimensions['A'].width = 8
        ws.column_dimensions['B'].width = 18
        ws.column_dimensions['C'].width = 40
        ws.column_dimensions['D'].width = 12
        ws.column_dimensions['E'].width = 12
        
        # Закрепить заголовок
        ws.freeze_panes = "A2"

    def _create_works_sheet(self, ws, data: List[Dict[str, Any]]):
        """Создать лист только с работами"""
        
        headers = ["№ п/п", "Наименование", "Ед. изм.", "Кол-во"]
        ws.append(headers)
        
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
        for idx, item in enumerate(data, 1):
            ws.append([
                idx,
                item.get('name', ''),
                item.get('unit', ''),
                item.get('quantity', '')
            ])
            
            if idx % 2 == 0:
                for cell in ws[idx + 1]:
                    cell.fill = PatternFill(start_color="F0F0F0", end_color="F0F0F0", fill_type="solid")
            
            for cell in ws[idx + 1]:
                cell.border = self.thin_border
        
        ws.column_dimensions['A'].width = 8
        ws.column_dimensions['B'].width = 45
        ws.column_dimensions['C'].width = 12
        ws.column_dimensions['D'].width = 12
        ws.freeze_panes = "A2"

    def _create_materials_sheet(self, ws, data: List[Dict[str, Any]]):
        """Создать лист только с материалами"""
        
        headers = ["№ п/п", "Наименование", "Ед. изм.", "Кол-во"]
        ws.append(headers)
        
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
        for idx, item in enumerate(data, 1):
            ws.append([
                idx,
                item.get('name', ''),
                item.get('unit', ''),
                item.get('quantity', '')
            ])
            
            if idx % 2 == 0:
                for cell in ws[idx + 1]:
                    cell.fill = PatternFill(start_color="F0F0F0", end_color="F0F0F0", fill_type="solid")
            
            for cell in ws[idx + 1]:
                cell.border = self.thin_border
        
        ws.column_dimensions['A'].width = 8
        ws.column_dimensions['B'].width = 45
        ws.column_dimensions['C'].width = 12
        ws.column_dimensions['D'].width = 12
        ws.freeze_panes = "A2"

    def _create_estimate_sheet(self, ws, data: List[Dict[str, Any]]):
        """Создать лист со сметой"""
        
        headers = [
            "№ п/п", "Работа/Материал", "Наименование", "Ед. изм.", "Кол-во",
            "Цена за ед. (Работа)", "Стоимость (Работа), руб.",
            "Цена за ед. (Материал)", "Стоимость (Материал), руб.",
            "Наименование в прайсе", "Примечание"
        ]
        ws.append(headers)
        
        for cell in ws[1]:
            cell.font = Font(bold=True, size=9)
            cell.fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
        total_work = 0
        total_material = 0
        
        for idx, item in enumerate(data, 1):
            work_cost = 0
            material_cost = 0
            
            if item.get('type') == 'Работа':
                work_cost = (item.get('quantity', 0) or 0) * (item.get('price_work_per_unit', 0) or 0)
                total_work += work_cost
            else:
                material_cost = (item.get('quantity', 0) or 0) * (item.get('price_material_per_unit', 0) or 0)
                total_material += material_cost
            
            ws.append([
                idx,
                item.get('type', ''),
                item.get('name', ''),
                item.get('unit', ''),
                item.get('quantity', ''),
                item.get('price_work_per_unit', '') if item.get('type') == 'Работа' else '',
                work_cost if item.get('type') == 'Работа' else '',
                item.get('price_material_per_unit', '') if item.get('type') == 'Материал' else '',
                material_cost if item.get('type') == 'Материал' else '',
                item.get('name_in_pricelist', ''),
                item.get('note', '')
            ])
            
            # Выделение строк без цены
            has_price = (item.get('price_work_per_unit') or item.get('price_material_per_unit'))
            if not has_price:
                for cell in ws[idx + 1]:
                    cell.fill = PatternFill(start_color="FFE6E6", end_color="FFE6E6", fill_type="solid")
            elif idx % 2 == 0:
                for cell in ws[idx + 1]:
                    cell.fill = PatternFill(start_color="F0F0F0", end_color="F0F0F0", fill_type="solid")
            
            for cell in ws[idx + 1]:
                cell.border = self.thin_border
        
        # Итоговые строки
        last_row = len(data) + 2
        ws[f"A{last_row}"] = "ИТОГО БЕЗ НДС"
        ws[f"F{last_row}"] = total_work
        ws[f"H{last_row}"] = total_material
        
        ws[f"A{last_row + 1}"] = "НДС 22%"
        ws[f"F{last_row + 1}"] = round(total_work * 0.22, 2)
        ws[f"H{last_row + 1}"] = round(total_material * 0.22, 2)
        
        ws[f"A{last_row + 2}"] = "ИТОГО С НДС"
        ws[f"F{last_row + 2}"] = round(total_work * 1.22, 2)
        ws[f"H{last_row + 2}"] = round(total_material * 1.22, 2)
        
        # Форматирование итогов
        for row in [last_row, last_row + 1, last_row + 2]:
            ws[f"A{row}"].font = Font(bold=True)
            for col in ['F', 'H']:
                ws[f"{col}{row}"].font = Font(bold=True)
                ws[f"{col}{row}"].fill = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")
        
        # Установить ширину колонок
        ws.column_dimensions['A'].width = 6
        ws.column_dimensions['B'].width = 12
        ws.column_dimensions['C'].width = 25
        ws.column_dimensions['D'].width = 10
        ws.column_dimensions['E'].width = 8
        ws.column_dimensions['F'].width = 12
        ws.column_dimensions['G'].width = 15
        ws.column_dimensions['H'].width = 12
        ws.column_dimensions['I'].width = 15
        ws.column_dimensions['J'].width = 25
        ws.column_dimensions['K'].width = 20
        
        ws.freeze_panes = "A2"

    def _create_estimate_works_sheet(self, ws, data: List[Dict[str, Any]]):
        """Создать лист только с работами в смете"""
        
        headers = ["№ п/п", "Наименование", "Ед. изм.", "Кол-во", "Цена за ед.", "Стоимость, руб.", "Наименование в прайсе", "Примечание"]
        ws.append(headers)
        
        for cell in ws[1]:
            cell.font = Font(bold=True, size=9)
            cell.fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
        total = 0
        
        for idx, item in enumerate(data, 1):
            cost = (item.get('quantity', 0) or 0) * (item.get('price_work_per_unit', 0) or 0)
            total += cost
            
            ws.append([
                idx,
                item.get('name', ''),
                item.get('unit', ''),
                item.get('quantity', ''),
                item.get('price_work_per_unit', ''),
                cost,
                item.get('name_in_pricelist', ''),
                item.get('note', '')
            ])
            
            if not item.get('price_work_per_unit'):
                for cell in ws[idx + 1]:
                    cell.fill = PatternFill(start_color="FFE6E6", end_color="FFE6E6", fill_type="solid")
            elif idx % 2 == 0:
                for cell in ws[idx + 1]:
                    cell.fill = PatternFill(start_color="F0F0F0", end_color="F0F0F0", fill_type="solid")
            
            for cell in ws[idx + 1]:
                cell.border = self.thin_border
        
        # Итоги
        last_row = len(data) + 2
        ws[f"A{last_row}"] = "ИТОГО БЕЗ НДС"
        ws[f"F{last_row}"] = total
        
        ws[f"A{last_row + 1}"] = "НДС 22%"
        ws[f"F{last_row + 1}"] = round(total * 0.22, 2)
        
        ws[f"A{last_row + 2}"] = "ИТОГО С НДС"
        ws[f"F{last_row + 2}"] = round(total * 1.22, 2)
        
        for row in [last_row, last_row + 1, last_row + 2]:
            ws[f"A{row}"].font = Font(bold=True)
            ws[f"F{row}"].font = Font(bold=True)
            ws[f"F{row}"].fill = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")
        
        ws.column_dimensions['A'].width = 6
        ws.column_dimensions['B'].width = 40
        ws.column_dimensions['C'].width = 10
        ws.column_dimensions['D'].width = 8
        ws.column_dimensions['E'].width = 12
        ws.column_dimensions['F'].width = 15
        ws.column_dimensions['G'].width = 25
        ws.column_dimensions['H'].width = 20
        ws.freeze_panes = "A2"

    def _create_estimate_materials_sheet(self, ws, data: List[Dict[str, Any]]):
        """Создать лист только с материалами в смете"""
        
        headers = ["№ п/п", "Наименование", "Ед. изм.", "Кол-во", "Цена за ед.", "Стоимость, руб.", "Наименование в прайсе", "Примечание"]
        ws.append(headers)
        
        for cell in ws[1]:
            cell.font = Font(bold=True, size=9)
            cell.fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
        total = 0
        
        for idx, item in enumerate(data, 1):
            cost = (item.get('quantity', 0) or 0) * (item.get('price_material_per_unit', 0) or 0)
            total += cost
            
            ws.append([
                idx,
                item.get('name', ''),
                item.get('unit', ''),
                item.get('quantity', ''),
                item.get('price_material_per_unit', ''),
                cost,
                item.get('name_in_pricelist', ''),
                item.get('note', '')
            ])
            
            if not item.get('price_material_per_unit'):
                for cell in ws[idx + 1]:
                    cell.fill = PatternFill(start_color="FFE6E6", end_color="FFE6E6", fill_type="solid")
            elif idx % 2 == 0:
                for cell in ws[idx + 1]:
                    cell.fill = PatternFill(start_color="F0F0F0", end_color="F0F0F0", fill_type="solid")
            
            for cell in ws[idx + 1]:
                cell.border = self.thin_border
        
        # Итоги
        last_row = len(data) + 2
        ws[f"A{last_row}"] = "ИТОГО БЕЗ НДС"
        ws[f"F{last_row}"] = total
        
        ws[f"A{last_row + 1}"] = "НДС 22%"
        ws[f"F{last_row + 1}"] = round(total * 0.22, 2)
        
        ws[f"A{last_row + 2}"] = "ИТОГО С НДС"
        ws[f"F{last_row + 2}"] = round(total * 1.22, 2)
        
        for row in [last_row, last_row + 1, last_row + 2]:
            ws[f"A{row}"].font = Font(bold=True)
            ws[f"F{row}"].font = Font(bold=True)
            ws[f"F{row}"].fill = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")
        
        ws.column_dimensions['A'].width = 6
        ws.column_dimensions['B'].width = 40
        ws.column_dimensions['C'].width = 10
        ws.column_dimensions['D'].width = 8
        ws.column_dimensions['E'].width = 12
        ws.column_dimensions['F'].width = 15
        ws.column_dimensions['G'].width = 25
        ws.column_dimensions['H'].width = 20
        ws.freeze_panes = "A2"
