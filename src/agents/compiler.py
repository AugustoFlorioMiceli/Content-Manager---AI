import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

from models.strategy import CompilerResult, Script, WriterResult

logger = logging.getLogger(__name__)

# Script color coding (matches template: green=interviewer, red=directions, black=response)
_GREEN = (46, 125, 50)
_RED = (198, 40, 40)
_BLACK = (0, 0, 0)
_GREEN_HEX = "#2e7d32"
_RED_HEX = "#c62828"


def _sanitize_latin1(text: str) -> str:
    """Replace characters outside Latin-1 range with safe equivalents."""
    replacements = {
        "\u2026": "...",   # …
        "\u2018": "'",     # '
        "\u2019": "'",     # '
        "\u201c": '"',     # "
        "\u201d": '"',     # "
        "\u2014": "-",     # —
        "\u2013": "-",     # –
        "\u2022": "-",     # •
    }
    for char, repl in replacements.items():
        text = text.replace(char, repl)
    # Strip any remaining non-Latin-1 characters (emojis, etc.)
    return text.encode("latin-1", errors="ignore").decode("latin-1").strip()

PILLAR_LABELS = {
    "viralidad": "Viralidad",
    "autoridad": "Autoridad",
    "venta": "Venta",
}


def _classify_line(line: str) -> str:
    """Classify a script content line for color coding.

    Returns 'green' (interviewer/question), 'red' (stage direction), or 'black' (response).
    """
    s = line.strip()
    if not s:
        return "empty"
    if s.startswith("-"):
        return "green"
    if re.match(r"^\(.*\)$", s):
        return "red"
    if re.match(r"^Plano\s+\d+", s, re.IGNORECASE):
        return "red"
    return "black"


def _render_content_pdf(pdf: FPDF, content: str, epw: float) -> None:
    """Render script dialogue content with color differentiation per line."""
    for raw_line in content.split("\n"):
        s = raw_line.strip()
        if not s:
            pdf.ln(3)
            continue

        kind = _classify_line(s)
        if kind == "green":
            pdf.set_text_color(*_GREEN)
            pdf.set_font("Helvetica", "B", 10)
        elif kind == "red":
            pdf.set_text_color(*_RED)
            pdf.set_font("Helvetica", "I", 10)
        else:
            pdf.set_text_color(*_BLACK)
            pdf.set_font("Helvetica", "", 10)

        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(epw, 6, _sanitize_latin1(s))

    # Reset to defaults after block
    pdf.set_text_color(*_BLACK)
    pdf.set_font("Helvetica", "", 10)


def _color_content_md(content: str) -> str:
    """Wrap content lines in HTML color spans for markdown rendering."""
    result = []
    for raw_line in content.split("\n"):
        s = raw_line.strip()
        if not s:
            result.append("")
            continue

        kind = _classify_line(s)
        if kind == "green":
            result.append(f'<span style="color: {_GREEN_HEX}">**{s}**</span>')
        elif kind == "red":
            result.append(f'<span style="color: {_RED_HEX}">*{s}*</span>')
        else:
            # Color inline parentheticals red within black lines
            colored = re.sub(
                r"(\([^)]+\))",
                lambda m: f'<span style="color: {_RED_HEX}"><em>{m.group(1)}</em></span>',
                s,
            )
            result.append(colored)

    return "\n\n".join(result)


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
        lines.append(_color_content_md(section.content))
        lines.append("")
        if section.notes:
            lines.append(f'<span style="color: {_RED_HEX}">*Nota de produccion: {section.notes}*</span>')
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
    epw = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Resumen Ejecutivo", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(epw, 6, _sanitize_latin1(calendar.strategy_summary))
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
        row = [str(b.day), b.date.isoformat(), pillar_label, _sanitize_latin1(b.topic), b.content_type]
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
    epw = pdf.w - pdf.l_margin - pdf.r_margin

    # Titulo del guion (multi_cell para que no se corte)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(epw, 9, _sanitize_latin1(f"Dia {b.day} - {b.topic} ({pillar_label})"))

    # Metadata (multi_cell para textos largos)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(epw, 6, _sanitize_latin1(f"Fecha: {b.date.isoformat()}  |  Tipo: {b.content_type}  |  Objetivo: {b.objective}"))
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    # Hook
    pdf.set_fill_color(239, 246, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(epw, 7, _sanitize_latin1(f"Hook: {script.hook}"), fill=True)
    pdf.ln(3)

    # Secciones
    for section in script.sections:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_BLACK)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(epw, 7, _sanitize_latin1(section.title))
        _render_content_pdf(pdf, section.content, epw)
        if section.notes:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(*_RED)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(epw, 6, _sanitize_latin1(f"Nota: {section.notes}"))
            pdf.set_text_color(*_BLACK)
        pdf.ln(2)

    # CTA
    if script.cta:
        pdf.set_fill_color(239, 246, 255)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(epw, 7, _sanitize_latin1(f"CTA: {script.cta}"), fill=True)
        pdf.ln(2)

    # Tips de retencion
    if script.retention_tips:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(epw, 7, "Tips de retencion:")
        pdf.set_font("Helvetica", "", 9)
        for tip in script.retention_tips:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(epw, 6, _sanitize_latin1(f"  - {tip}"))
        pdf.ln(2)

    # Justificacion
    if script.strategic_justification:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(epw, 5, _sanitize_latin1(f"Justificacion: {script.strategic_justification}"))
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
