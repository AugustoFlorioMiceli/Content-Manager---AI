import json
import logging

from src.models.strategy import (
    ContentBrief,
    ContentCalendar,
    Script,
    ScriptSection,
    WriterResult,
)
from src.services.embeddings import generate_embeddings
from src.services.llm import generate
from src.services.qdrant import search

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """Eres un redactor de guiones de contenido digital de élite. Tu trabajo es escribir guiones
completos, listos para grabar, basados en briefs estratégicos y datos reales de un nicho.

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
## PLANTILLA DEL USUARIO (respeta esta estructura):
{template}

Inyecta el contenido nuevo dentro de esta estructura, manteniendo el estilo y formato.
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

## DATOS DEL NICHO (información real extraída):
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


def _parse_script_response(response: str, brief: ContentBrief) -> Script:
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    data = json.loads(cleaned)

    sections = [ScriptSection(**s) for s in data.get("sections", [])]

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

        # 3. Generate script with Gemini
        response = generate(prompt, system_instruction=SYSTEM_INSTRUCTION)

        # 4. Parse response
        try:
            script = _parse_script_response(response, brief)
            scripts.append(script)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse script for brief %d: %s", brief.day, e)
            # Create a minimal script with the raw response
            scripts.append(Script(
                brief=brief,
                hook=brief.hook,
                sections=[ScriptSection(
                    title="Guión completo",
                    content=response,
                )],
                cta="",
            ))

    return WriterResult(
        platform=calendar.platform,
        username=calendar.username,
        scripts=scripts,
        calendar=calendar,
    )
