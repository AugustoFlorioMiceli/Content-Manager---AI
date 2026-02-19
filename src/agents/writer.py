import json
import logging

from models.strategy import (
    ContentBrief,
    ContentCalendar,
    Script,
    ScriptSection,
    WriterResult,
)
from services.embeddings import generate_embeddings
from services.llm import generate
from services.qdrant import search

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """Eres un redactor de guiones de contenido digital de élite. Tu trabajo es escribir guiones
completos, listos para grabar, basados en briefs estratégicos y datos reales de un nicho.

CONTEXTO CRÍTICO:
- Los "datos del nicho" que recibes provienen de canales/cuentas de REFERENCIA que fueron analizados.
- NUNCA adoptes la identidad, nombre, o persona de los creadores de esos canales de referencia.
- Los guiones son para un NUEVO creador de contenido que quiere posicionarse en ese nicho.
- Usa los datos de referencia como inspiración, tendencias y conocimiento del nicho, NO como identidad.
- El guión debe estar escrito en primera persona genérica, sin asumir un nombre o título profesional específico.

Reglas clave:
- El hook de apertura debe capturar atención en los primeros 3-5 segundos. Debe ser específico y provocativo.
- Incluye pattern interrupts cada 30-60 segundos para mantener retención.
- El CTA debe estar alineado al pilar de la pieza (viralidad=compartir, autoridad=seguir/guardar, venta=comprar/link).
- Usa datos reales del nicho cuando sea posible para dar credibilidad.
- Si se proporciona una plantilla del usuario, respeta esa estructura exacta e inyecta el contenido nuevo.
- El tono debe ser conversacional y directo, como si hablaras a una persona.

IMPORTANTE: Responde ÚNICAMENTE con un JSON válido, sin texto adicional ni markdown.
"""


def _get_niche_data_for_brief(collection_name: str, brief: ContentBrief) -> str:
    query = f"{brief.topic} {brief.angle}"
    query_embedding = generate_embeddings([query])[0]
    results = search(collection_name, query_embedding, limit=5)

    texts = []
    for r in results:
        text = r.get("text", "")
        if text:
            texts.append(text)

    return "\n---\n".join(texts) if texts else "No hay datos específicos disponibles."


def _build_script_prompt(
    brief: ContentBrief,
    niche_data: str,
    template: str | None = None,
) -> str:
    template_section = ""
    if template:
        template_section = f"""
## EJEMPLOS Y CONTEXTO DEL USUARIO:
{template}

INSTRUCCIONES SOBRE LOS EJEMPLOS:
- Si hay ejemplos de guiones, REPLICA su estructura, formato, tono y estilo en los nuevos guiones.
- Usa las mismas secciones, transiciones y nivel de detalle que muestran los ejemplos.
- Si hay informacion de marca (tono de voz, valores, publico objetivo), alinea el contenido a esa identidad.
- Adapta el contenido al tema del brief, pero mantene el formato y estilo de los ejemplos.
"""

    return f"""Escribe un guión completo para la siguiente pieza de contenido.

## BRIEF:
- Día: {brief.day} ({brief.date.isoformat()})
- Pilar: {brief.pillar}
- Tema: {brief.topic}
- Ángulo: {brief.angle}
- Hook sugerido: {brief.hook}
- Objetivo: {brief.objective}
- Tipo de contenido: {brief.content_type}
- Datos de referencia: {', '.join(brief.reference_data) if brief.reference_data else 'N/A'}

## DATOS DEL NICHO (extraídos de canales de referencia - usar como inspiración, NO adoptar la identidad de estos creadores):
{niche_data}
{template_section}
## FORMATO DE RESPUESTA (JSON):
{{
    "hook": "Hook de apertura exacto (primeros 3-5 segundos del video/contenido)",
    "sections": [
        {{
            "title": "Nombre de la sección (ej: Introducción, Punto 1, Desarrollo, Cierre)",
            "content": "Texto completo del guión para esta sección, escrito como se diría en cámara",
            "notes": "Notas de producción opcionales (ej: mostrar gráfico, insertar B-roll)"
        }}
    ],
    "cta": "Call-to-action de cierre alineado al pilar",
    "retention_tips": ["Tip de retención 1", "Tip de retención 2"],
    "strategic_justification": "Explicación breve de por qué este guión cumple el objetivo del brief"
}}

Genera un guión completo con al menos 3 secciones. El contenido debe ser específico, no genérico."""


def _extract_json(text: str) -> str:
    """Extract JSON from response, handling markdown fences and extra text."""
    cleaned = text.strip()

    # Remove markdown code fences
    if "```" in cleaned:
        # Find content between first ``` and last ```
        parts = cleaned.split("```")
        for part in parts[1:]:
            # Skip the language tag (e.g., "json\n")
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            # Check if it looks like JSON
            if candidate.startswith("{"):
                cleaned = candidate
                break

    # If still wrapped in ```, try line-by-line
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        json_lines = []
        inside = False
        for line in lines:
            if line.strip().startswith("```") and not inside:
                inside = True
                continue
            elif line.strip().startswith("```") and inside:
                break
            elif inside:
                json_lines.append(line)
        if json_lines:
            cleaned = "\n".join(json_lines).strip()

    # Find JSON object if there's extra text around it
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        if start != -1:
            # Find matching closing brace
            depth = 0
            for i, c in enumerate(cleaned[start:], start):
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        cleaned = cleaned[start:i + 1]
                        break

    return cleaned


def _parse_script_response(response: str, brief: ContentBrief) -> Script:
    cleaned = _extract_json(response)
    data = json.loads(cleaned)

    sections = []
    for s in data.get("sections", []):
        if isinstance(s.get("notes"), list):
            s["notes"] = " ".join(str(n) for n in s["notes"])
        if isinstance(s.get("content"), list):
            s["content"] = "\n".join(str(c) for c in s["content"])
        sections.append(ScriptSection(**s))

    return Script(
        brief=brief,
        hook=data.get("hook", brief.hook),
        sections=sections,
        cta=data.get("cta", ""),
        retention_tips=data.get("retention_tips", []),
        strategic_justification=data.get("strategic_justification", ""),
    )


def run_writer(
    calendar: ContentCalendar,
    collection_name: str,
    template: str | None = None,
) -> WriterResult:
    logger.info(
        "Writing scripts for @%s: %d briefs",
        calendar.username,
        len(calendar.briefs),
    )

    scripts = []
    for i, brief in enumerate(calendar.briefs):
        logger.info(
            "Writing script %d/%d: %s (%s)",
            i + 1,
            len(calendar.briefs),
            brief.topic,
            brief.pillar,
        )

        # 1. Get niche data for this specific brief
        niche_data = _get_niche_data_for_brief(collection_name, brief)

        # 2. Build prompt
        prompt = _build_script_prompt(brief, niche_data, template)

        # 3. Generate script with Gemini (retry once on parse failure)
        script = None
        for attempt in range(2):
            response = generate(prompt, system_instruction=SYSTEM_INSTRUCTION)
            try:
                script = _parse_script_response(response, brief)
                break
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                if attempt == 0:
                    logger.warning(
                        "Failed to parse script for brief %d (attempt 1), retrying: %s",
                        brief.day, e,
                    )
                else:
                    logger.error(
                        "Failed to parse script for brief %d after retry: %s",
                        brief.day, e,
                    )

        if script is None:
            # Last resort: never show raw JSON, create a placeholder
            script = Script(
                brief=brief,
                hook=brief.hook,
                sections=[ScriptSection(
                    title="Error de generacion",
                    content="No se pudo generar el guion para esta pieza. "
                    "Intenta regenerar el plan.",
                )],
                cta="",
            )

        scripts.append(script)

    return WriterResult(
        platform=calendar.platform,
        username=calendar.username,
        scripts=scripts,
        calendar=calendar,
    )
