import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

from models.strategy import CompilerResult, Script, WriterResult

logger = logging.getLogger(__name__)


def _strip_emoji(text: str) -> str:
    return re.sub(
        r'[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b50\u200d\ufe0f]',
        '',
        text,
    ).strip()

PILLAR_LABELS = {
    "viralidad": "Viralidad",
    "autoridad": "Autoridad",
    "venta": "Venta",
}


def _render_markdown(result: WriterResult) -> str:
    lines = []
    calendar = result.calendar
    config = calendar.config

    # --- Portada ---
    lines.append("# ContentBrain - Plan de Contenido")
    lines.append("")
    lines.append(f"**Plataforma:** {calendar.platform.capitalize()}")
    lines.append(f"**Cuenta:** @{calendar.username}")
    lines.append(f"**Periodo:** {config.period_weeks} semanas desde {config.start_date.isoformat()}")
    lines.append(f"**Frecuencia:** {config.posts_per_week} publicaciones/semana ({config.total_posts} total)")
    lines.append(f"**Generado:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # Resumen ejecutivo
    lines.append("## Resumen Ejecutivo")
    lines.append("")
    lines.append(calendar.strategy_summary)
    lines.append("")

    # Distribucion de pilares
    lines.append("**Distribucion de pilares:**")
    lines.append("")
    for pillar, count in calendar.pillar_distribution.items():
        label = PILLAR_LABELS.get(pillar, pillar.capitalize())
        pct = round(count / config.total_posts * 100)
        lines.append(f"- {label}: {count} piezas ({pct}%)")
    lines.append("")

    # --- Calendario ---
    lines.append("---")
    lines.append("")
    lines.append("## Calendario Editorial")
    lines.append("")
    lines.append("| # | Fecha | Pilar | Tema | Tipo |")
    lines.append("|---|---|---|---|---|")

    for script in result.scripts:
        b = script.brief
        pillar_label = PILLAR_LABELS.get(b.pillar, b.pillar.capitalize())
        lines.append(f"| {b.day} | {b.date.isoformat()} | {pillar_label} | {b.topic} | {b.content_type} |")
    lines.append("")

    # --- Guiones ---
    lines.append("---")
    lines.append("")
    lines.append("## Guiones Detallados")
    lines.append("")

    current_week = -1
    for script in result.scripts:
        b = script.brief
        week = (b.date - config.start_date).days // 7 + 1
        if week != current_week:
            current_week = week
            lines.append(f"### Semana {week}")
            lines.append("")

        _render_script_md(lines, script)

    # --- Apendice ---
    lines.append("---")
    lines.append("")
    lines.append("## Apendice")
    lines.append("")
    lines.append("### Datos de Referencia del Nicho")
    lines.append("")

    refs_seen = set()
    for script in result.scripts:
        for ref in script.brief.reference_data:
            if ref not in refs_seen:
                refs_seen.add(ref)
                lines.append(f"- {ref}")

    if not refs_seen:
        lines.append("_No se incluyeron datos de referencia._")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_Documento generado por ContentBrain_")
    lines.append("")

    return "\n".join(lines)


def _render_script_md(lines: list[str], script: Script) -> None:
    b = script.brief
    pillar_label = PILLAR_LABELS.get(b.pillar, b.pillar.capitalize())

    lines.append(f"#### Dia {b.day} - {b.topic} ({pillar_label})")
    lines.append("")
    lines.append(f"**Fecha:** {b.date.isoformat()} | **Tipo:** {b.content_type} | **Objetivo:** {b.objective}")
    lines.append("")

    lines.append(f"> **Hook:** {script.hook}")
    lines.append("")

    for section in script.sections:
        lines.append(f"**{section.title}**")
        lines.append("")
        lines.append(section.content)
        lines.append("")
        if section.notes:
            lines.append(f"_Nota de produccion: {section.notes}_")
            lines.append("")

    if script.cta:
        lines.append(f"> **CTA:** {script.cta}")
        lines.append("")

    if script.retention_tips:
        lines.append("**Tips de retencion:**")
        lines.append("")
        for tip in script.retention_tips:
            lines.append(f"- {tip}")
        lines.append("")

    if script.strategic_justification:
        lines.append(f"**Justificacion estrategica:** {script.strategic_justification}")
        lines.append("")

    lines.append("")


def _save_markdown(content: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    logger.info("Saved Markdown to %s", output_path)
    return output_path


def _render_pdf(result: WriterResult, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    calendar = result.calendar
    config = calendar.config

    # --- Portada ---
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 15, "ContentBrain", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 16)
    pdf.cell(0, 10, "Plan de Contenido", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)

    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, f"Plataforma: {calendar.platform.capitalize()}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Cuenta: @{calendar.username}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Periodo: {config.period_weeks} semanas desde {config.start_date.isoformat()}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Frecuencia: {config.posts_per_week}/semana ({config.total_posts} total)", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # --- Resumen ---
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Resumen Ejecutivo", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, _strip_emoji(calendar.strategy_summary))
    pdf.ln(3)

    # Distribucion de pilares
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Distribucion de pilares:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    for pillar, count in calendar.pillar_distribution.items():
        label = PILLAR_LABELS.get(pillar, pillar.capitalize())
        pct = round(count / config.total_posts * 100)
        pdf.cell(0, 7, f"  {label}: {count} piezas ({pct}%)", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # --- Calendario (tabla) ---
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Calendario Editorial", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    col_widths = [12, 30, 30, 75, 25]
    headers = ["#", "Fecha", "Pilar", "Tema", "Tipo"]

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(37, 99, 235)
    pdf.set_text_color(255, 255, 255)
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 8, header, border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(0, 0, 0)
    for j, script in enumerate(result.scripts):
        b = script.brief
        pillar_label = PILLAR_LABELS.get(b.pillar, b.pillar.capitalize())
        row = [str(b.day), b.date.isoformat(), pillar_label, _strip_emoji(b.topic), b.content_type]
        if j % 2 == 0:
            pdf.set_fill_color(249, 250, 251)
        else:
            pdf.set_fill_color(255, 255, 255)
        for i, val in enumerate(row):
            pdf.cell(col_widths[i], 7, val[:30], border=1, fill=True)
        pdf.ln()

    # --- Guiones ---
    current_week = -1
    for script in result.scripts:
        b = script.brief
        week = (b.date - config.start_date).days // 7 + 1
        if week != current_week:
            current_week = week
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 10, f"Semana {week}", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

        _render_script_pdf(pdf, script)

    pdf.output(str(output_path))
    logger.info("Saved PDF to %s", output_path)
    return output_path


def _render_script_pdf(pdf: FPDF, script: Script) -> None:
    b = script.brief
    pillar_label = PILLAR_LABELS.get(b.pillar, b.pillar.capitalize())

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, _strip_emoji(f"Dia {b.day} - {b.topic} ({pillar_label})"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, _strip_emoji(f"Fecha: {b.date.isoformat()}  |  Tipo: {b.content_type}  |  Objetivo: {b.objective}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    # Hook
    pdf.set_fill_color(239, 246, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(15, 7, "Hook: ", fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 7, _strip_emoji(script.hook), fill=True)
    pdf.ln(3)

    # Secciones
    for section in script.sections:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, _strip_emoji(section.title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, _strip_emoji(section.content))
        if section.notes:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 6, _strip_emoji(f"Nota: {section.notes}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    # CTA
    if script.cta:
        pdf.set_fill_color(239, 246, 255)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(13, 7, "CTA: ", fill=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 7, _strip_emoji(script.cta), fill=True)
        pdf.ln(2)

    # Tips de retencion
    if script.retention_tips:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 7, "Tips de retencion:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        for tip in script.retention_tips:
            pdf.cell(0, 6, _strip_emoji(f"  - {tip}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    # Justificacion
    if script.strategic_justification:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(0, 5, _strip_emoji(f"Justificacion: {script.strategic_justification}"))
        pdf.set_text_color(0, 0, 0)

    pdf.ln(5)


def run_compiler(
    result: WriterResult,
    output_dir: str = "output",
    formats: list[str] | None = None,
) -> CompilerResult:
    if formats is None:
        formats = ["markdown", "pdf"]

    logger.info(
        "Compiling %d scripts for @%s (formats: %s)",
        len(result.scripts),
        result.username,
        ", ".join(formats),
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = f"contentbrain_{result.platform}_{result.username}_{timestamp}"
    output_path = Path(output_dir)

    md_path = None
    pdf_path = None

    if "markdown" in formats:
        markdown_content = _render_markdown(result)
        md_file = output_path / f"{base_name}.md"
        _save_markdown(markdown_content, md_file)
        md_path = str(md_file)

    if "pdf" in formats:
        pdf_file = output_path / f"{base_name}.pdf"
        _render_pdf(result, pdf_file)
        pdf_path = str(pdf_file)

    return CompilerResult(
        markdown_path=md_path,
        pdf_path=pdf_path,
        platform=result.platform,
        username=result.username,
        total_scripts=len(result.scripts),
    )
