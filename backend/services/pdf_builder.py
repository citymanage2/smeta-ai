import io
from datetime import datetime
from typing import Dict, List, Any
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

class PDFBuilder:
    """Построитель PDF отчетов"""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._create_custom_styles()

    def _create_custom_styles(self):
        """Создать пользовательские стили"""
        
        self.styles.add(ParagraphStyle(
            name='title_custom',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1f4788'),
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
        
        self.styles.add(ParagraphStyle(
            name='subtitle_custom',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#333333'),
            spaceAfter=20,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold'
        ))
        
        self.styles.add(ParagraphStyle(
            name='text_custom',
            parent=self.styles['Normal'],
            fontSize=11,
            spaceAfter=12,
            alignment=TA_LEFT,
            fontName='Helvetica'
        ))

    def create_comparison_report(self, comparison_data: Dict[str, Any]) -> bytes:
        """Создать PDF отчет о сравнительном анализе"""
        
        output = io.BytesIO()
        doc = SimpleDocTemplate(output, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
        
        story = []
        
        # Заголовок
        title = Paragraph("Сравнительный анализ проекта и сметы", self.styles['title_custom'])
        story.append(title)
        
        subtitle = Paragraph(f"Smeta AI | {datetime.now().strftime('%d.%m.%Y')}", self.styles['subtitle_custom'])
        story.append(subtitle)
        story.append(Spacer(1, 0.3*inch))
        
        # Итоговая оценка соответствия
        compliance_pct = comparison_data.get('compliance_pct', 0)
        
        if compliance_pct >= 85:
            color = colors.HexColor('#008000')  # Зелёный
        elif compliance_pct >= 60:
            color = colors.HexColor('#FFA500')  # Жёлтый
        else:
            color = colors.HexColor('#FF0000')  # Красный
        
        compliance_text = f"<font color='#{color.hexval()}'><b>Соответствие проекту: {compliance_pct}%</b></font>"
        story.append(Paragraph(compliance_text, self.styles['text_custom']))
        story.append(Spacer(1, 0.2*inch))
        
        # Отсутствующие позиции
        missing = comparison_data.get('missing_in_estimate', [])
        if missing:
            story.append(Paragraph("Позиции, отсутствующие в смете", self.styles['subtitle_custom']))
            
            table_data = [["Наименование", "Ед. изм.", "Кол-во", "Примечание"]]
            for item in missing:
                table_data.append([
                    item.get('name', ''),
                    item.get('unit', ''),
                    str(item.get('quantity', '')),
                    item.get('note', '')
                ])
            
            if len(table_data) > 1:
                table = Table(table_data, colWidths=[3*inch, 1*inch, 1*inch, 1.5*inch])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ]))
                story.append(table)
                story.append(Spacer(1, 0.3*inch))
        
        # Лишние позиции
        extra = comparison_data.get('extra_in_estimate', [])
        if extra:
            story.append(Paragraph("Лишние позиции в смете", self.styles['subtitle_custom']))
            
            table_data = [["Наименование", "Ед. изм.", "Кол-во", "Примечание"]]
            for item in extra:
                table_data.append([
                    item.get('name', ''),
                    item.get('unit', ''),
                    str(item.get('quantity', '')),
                    item.get('note', '')
                ])
            
            if len(table_data) > 1:
                table = Table(table_data, colWidths=[3*inch, 1*inch, 1*inch, 1.5*inch])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.orange),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.lightyellow),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ]))
                story.append(table)
                story.append(Spacer(1, 0.3*inch))
        
        # Расхождения в объёмах
        discrepancies = comparison_data.get('quantity_discrepancies', [])
        if discrepancies:
            story.append(Paragraph("Расхождения в объёмах", self.styles['subtitle_custom']))
            
            table_data = [["Наименование", "Проект", "Смета", "Отклонение %", "Примечание"]]
            for item in discrepancies:
                table_data.append([
                    item.get('name', ''),
                    str(item.get('project_qty', '')),
                    str(item.get('estimate_qty', '')),
                    f"{item.get('diff_pct', 0)}%",
                    item.get('note', '')
                ])
            
            if len(table_data) > 1:
                table = Table(table_data, colWidths=[2.5*inch, 1*inch, 1*inch, 1*inch, 1.5*inch])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.lightblue),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ]))
                story.append(table)
                story.append(Spacer(1, 0.3*inch))
        
        story.append(PageBreak())
        
        # Критические замечания
        critical_notes = comparison_data.get('critical_notes', [])
        if critical_notes:
            story.append(Paragraph("Критические замечания", self.styles['subtitle_custom']))
            
            for idx, note in enumerate(critical_notes, 1):
                story.append(Paragraph(f"<b>{idx}.</b> {note}", self.styles['text_custom']))
            
            story.append(Spacer(1, 0.3*inch))
        
        # Итоговый вывод
        summary = comparison_data.get('summary', '')
        if summary:
            story.append(Paragraph("Итоговый вывод", self.styles['subtitle_custom']))
            story.append(Paragraph(summary, self.styles['text_custom']))
        
        # Построить PDF
        doc.build(story)
        output.seek(0)
        return output.getvalue()
