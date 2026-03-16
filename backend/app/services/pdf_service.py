import io
from typing import Any
import structlog

logger = structlog.get_logger()


def _build_comparison_html(data: dict) -> str:
    """Build HTML for comparison report."""
    summary = data.get("summary", {})
    discrepancies = data.get("discrepancies", [])
    critical_issues = data.get("critical_issues", [])
    recommendations = data.get("recommendations", [])
    title = data.get("title", "Отчёт о сравнении")
    date = data.get("date", "")
    project_name = data.get("project_name", "")

    # Build discrepancies table rows
    disc_rows = ""
    for i, disc in enumerate(discrepancies, start=1):
        severity_class = {
            "critical": "severity-critical",
            "high": "severity-high",
            "medium": "severity-medium",
            "low": "severity-low",
        }.get(disc.get("severity", "").lower(), "")

        disc_rows += f"""
        <tr>
            <td>{i}</td>
            <td>{disc.get('item_name', '')}</td>
            <td>{disc.get('project_value', '')}</td>
            <td>{disc.get('smeta_value', '')}</td>
            <td>{disc.get('difference', '')}</td>
            <td><span class="severity {severity_class}">{disc.get('severity', '')}</span></td>
            <td>{disc.get('comment', '')}</td>
        </tr>"""

    # Build critical issues list
    critical_html = ""
    for issue in critical_issues:
        critical_html += f"<li><strong>{issue.get('title', '')}</strong>: {issue.get('description', '')}</li>"

    # Build recommendations list
    recs_html = ""
    for rec in recommendations:
        recs_html += f"<li>{rec}</li>"

    # Summary cards
    total_items = summary.get("total_items", 0)
    matched = summary.get("matched", 0)
    discrepancies_count = summary.get("discrepancies_count", len(discrepancies))
    match_percent = summary.get("match_percent", 0)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        @page {{
            margin: 2cm;
            size: A4;
        }}
        body {{
            font-family: 'DejaVu Sans', Arial, sans-serif;
            font-size: 11pt;
            color: #333;
            line-height: 1.5;
        }}
        h1 {{
            font-size: 18pt;
            color: #1a5276;
            border-bottom: 3px solid #2e86c1;
            padding-bottom: 8px;
            margin-bottom: 20px;
        }}
        h2 {{
            font-size: 14pt;
            color: #1a5276;
            border-left: 4px solid #2e86c1;
            padding-left: 10px;
            margin-top: 30px;
        }}
        .meta-info {{
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 15px;
            margin-bottom: 25px;
        }}
        .meta-info p {{
            margin: 5px 0;
        }}
        .summary-cards {{
            display: flex;
            gap: 15px;
            margin-bottom: 25px;
            flex-wrap: wrap;
        }}
        .card {{
            background: #f0f7ff;
            border: 1px solid #2e86c1;
            border-radius: 6px;
            padding: 15px 20px;
            text-align: center;
            min-width: 120px;
            flex: 1;
        }}
        .card .value {{
            font-size: 24pt;
            font-weight: bold;
            color: #1a5276;
        }}
        .card .label {{
            font-size: 9pt;
            color: #666;
            margin-top: 5px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
            font-size: 9pt;
        }}
        th {{
            background-color: #2e86c1;
            color: white;
            padding: 8px 6px;
            text-align: center;
            font-weight: bold;
        }}
        td {{
            padding: 6px;
            border: 1px solid #dee2e6;
            vertical-align: top;
        }}
        tr:nth-child(even) {{
            background-color: #f8f9fa;
        }}
        .severity {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 8pt;
            font-weight: bold;
        }}
        .severity-critical {{ background: #f8d7da; color: #721c24; }}
        .severity-high {{ background: #fff3cd; color: #856404; }}
        .severity-medium {{ background: #d1ecf1; color: #0c5460; }}
        .severity-low {{ background: #d4edda; color: #155724; }}
        .critical-issues {{
            background: #fff5f5;
            border: 1px solid #f5c6cb;
            border-radius: 4px;
            padding: 15px;
            margin-bottom: 20px;
        }}
        .critical-issues ul {{
            margin: 10px 0 0 0;
            padding-left: 20px;
        }}
        .critical-issues li {{
            margin-bottom: 8px;
        }}
        .recommendations {{
            background: #f0fff4;
            border: 1px solid #c3e6cb;
            border-radius: 4px;
            padding: 15px;
            margin-bottom: 20px;
        }}
        .recommendations ul {{
            margin: 10px 0 0 0;
            padding-left: 20px;
        }}
        .recommendations li {{
            margin-bottom: 8px;
        }}
        .footer {{
            margin-top: 40px;
            border-top: 1px solid #dee2e6;
            padding-top: 10px;
            font-size: 8pt;
            color: #999;
            text-align: center;
        }}
    </style>
</head>
<body>
    <h1>{title}</h1>

    <div class="meta-info">
        <p><strong>Объект:</strong> {project_name}</p>
        <p><strong>Дата формирования:</strong> {date}</p>
    </div>

    <h2>Сводная информация</h2>
    <div class="summary-cards">
        <div class="card">
            <div class="value">{total_items}</div>
            <div class="label">Всего позиций</div>
        </div>
        <div class="card">
            <div class="value">{matched}</div>
            <div class="label">Совпадений</div>
        </div>
        <div class="card">
            <div class="value">{discrepancies_count}</div>
            <div class="label">Расхождений</div>
        </div>
        <div class="card">
            <div class="value">{match_percent}%</div>
            <div class="label">Совпадение</div>
        </div>
    </div>
"""

    if critical_issues:
        html += f"""
    <h2>Критические замечания</h2>
    <div class="critical-issues">
        <ul>{critical_html}</ul>
    </div>
"""

    if discrepancies:
        html += f"""
    <h2>Таблица расхождений</h2>
    <table>
        <thead>
            <tr>
                <th>№</th>
                <th>Наименование</th>
                <th>По проекту</th>
                <th>По смете</th>
                <th>Разница</th>
                <th>Критичность</th>
                <th>Комментарий</th>
            </tr>
        </thead>
        <tbody>
            {disc_rows}
        </tbody>
    </table>
"""

    if recommendations:
        html += f"""
    <h2>Рекомендации</h2>
    <div class="recommendations">
        <ul>{recs_html}</ul>
    </div>
"""

    html += """
    <div class="footer">
        Сформировано автоматически системой Smeta AI
    </div>
</body>
</html>"""

    return html


def generate_comparison_report(data: dict) -> bytes:
    """
    Generate PDF comparison report using WeasyPrint.
    Returns PDF bytes.
    """
    try:
        from weasyprint import HTML, CSS
    except ImportError:
        logger.error("WeasyPrint not available")
        raise RuntimeError("WeasyPrint не установлен. Установите: pip install weasyprint")

    html_content = _build_comparison_html(data)

    try:
        pdf_bytes = HTML(string=html_content).write_pdf()
        return pdf_bytes
    except Exception as e:
        logger.error("PDF generation failed", error=str(e))
        raise RuntimeError(f"Ошибка генерации PDF: {e}")
