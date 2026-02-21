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

PLATFORM_STYLE = {
    "youtube": """ESTILO YOUTUBE (formato largo/horizontal):
- Guion detallado de 8-20 minutos
- Desarrollo profundo con datos, ejemplos y casos reales
- Estructura clara: hook + introduccion + 3-5 puntos + cierre + CTA
- Pattern interrupts cada 30-60 segundos
- Lenguaje educativo pero conversacional
- Notas de produccion: B-roll, graficos, cambios de plano""",
    "instagram": """ESTILO INSTAGRAM (formato vertical/corto):
- Guion de MAXIMO 60-90 segundos (300-400 palabras max)
- UNA idea potente, NO un resumen de video largo
- Hook en los primeros 2 segundos: pregunta provocativa, dato impactante o controversia
- Frases CORTAS y directas. Ritmo rapido.
- Texto en pantalla sugerido en las notas de produccion
- NO ser enciclopedico. Ser punzante, llamativo, memorable.
- Buscar el angulo mas sorprendente o controversial del tema
- Formato: hook + desarrollo rapido (2-3 puntos max) + CTA en 1 frase""",
    "tiktok": """ESTILO TIKTOK (formato vertical/ultra corto):
- Guion de MAXIMO 30-60 segundos (150-250 palabras max)
- Hook inmediato en el primer segundo
- Una sola idea explosiva
- Lenguaje ultra directo, sin rodeos
- Formato snackable: dato + reaccion + conclusion""",
}

SYSTEM_INSTRUCTION = """Eres un redactor de guiones de contenido digital de élite. Tu trabajo es escribir guiones
completos, listos para grabar, basados en briefs estratégicos y datos reales de un nicho.

CONTEXTO CRÍTICO:
- Los "datos del nicho" que recibes provienen de canales/cuentas de REFERENCIA que fueron analizados.
- NUNCA adoptes la identidad, nombre, o persona de los creadores de esos canales de referencia.
- Los guiones son para un NUEVO creador de contenido que quiere posicionarse en ese nicho.
- Usa los datos de referencia como inspiración, tendencias y conocimiento del nicho, NO como identidad.
- El guión debe estar escrito en primera persona genérica, sin asumir un nombre o título profesional específico.
- ADAPTA la longitud, estructura y tono al formato de la plataforma indicada.

Reglas clave:
- El CTA debe estar alineado al pilar de la pieza (viralidad=compartir, autoridad=seguir/guardar, venta=comprar/link).
- Usa datos reales del nicho cuando sea posible para dar credibilidad.
- El tono debe ser conversacional y directo, como si hablaras a una persona.

PRIORIDAD MAXIMA: Si el usuario proporcionó ejemplos de guiones, REPLICA EXACTAMENTE su estructura,
formato, tono, longitud y estilo. Los ejemplos del usuario son la referencia principal de formato.

FORMATO DE DIÁLOGO EN EL CAMPO "content" (OBLIGATORIO):
El sistema aplica colores automáticamente según estos prefijos — respétalos siempre:
- Líneas del ENTREVISTADOR o temas/categorías: EMPIEZAN CON "-"
  Ejemplo: "-¿Qué opinas sobre Dubai?" o "-España"
- Acotaciones de DIRECCIÓN o staging: entre paréntesis en línea propia o inline
  Ejemplo: "(toma café)" o "Respuesta. (mirando a cámara)"
- Respuestas del PRESENTADOR: texto plano sin prefijo
  Ejemplo: "Honestamente no lo recomiendo si facturas bien."
- Encabezados de sección temática (ej. intro al bloque de preguntas): texto plano sin "-"

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
    platform: str,
    template: str | None = None,
) -> str:
    platform_guide = PLATFORM_STYLE.get(platform, "")

    template_section = ""
    if template:
        template_section = f"""
## EJEMPLOS Y CONTEXTO DEL USUARIO — PRIORIDAD MAXIMA:
{template}

INSTRUCCIONES OBLIGATORIAS (no negociables):
1. ANALIZA la estructura exacta de los ejemplos: cuantas secciones tienen, como se llaman,
   que tipo de contenido va en cada una, que largo tienen, que especificaciones de produccion incluyen.
2. REPLICA esa misma estructura seccion por seccion. Si el ejemplo tiene "Hook", "Desarrollo",
   "Caso de estudio", "CTA" — tu guion debe tener exactamente esas secciones con esos nombres.
3. COPIA el tono, ritmo, longitud y nivel de detalle de cada seccion.
4. Si los ejemplos incluyen especificaciones tecnicas (colores, fuentes, transiciones, texto en pantalla,
   estilo visual), INCLUYELAS en las notas de produccion de cada seccion.
5. El guion resultante debe ser INDISTINGUIBLE en formato de los ejemplos — como si lo hubiera
   escrito la misma persona. Solo cambia el tema segun el brief.
6. DIFERENCIACION VISUAL — CRITICO: El campo "content" de cada seccion DEBE usar este formato:
   - Preguntas o temas del entrevistador: linea que EMPIEZA CON "-" (ej: "-¿Qué opinas?")
   - Acotaciones de staging/direccion: entre paréntesis (ej: "(toma café)", "(mirando al otro personaje)")
   - Respuestas del presentador: texto plano sin prefijo
"""

    return f"""Escribe un guión para {platform.upper()} basado en el siguiente brief.

## DIRECTRICES DE PLATAFORMA:
{platform_guide}

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
    "hook": "Hook de apertura exacto",
    "sections": [
        {{
            "title": "Nombre de la seccion (USA LOS MISMOS NOMBRES que los ejemplos del usuario si los hay)",
            "content": "Texto completo de la seccion tal como se diria en camara",
            "notes": "Especificaciones de produccion: colores, fuentes, transiciones, texto en pantalla, B-roll, graficos, etc."
        }}
    ],
    "cta": "Call-to-action de cierre alineado al pilar",
    "retention_tips": ["Tip de retencion 1", "Tip de retencion 2"],
    "strategic_justification": "Explicacion breve de por que este guion cumple el objetivo del brief"
}}

IMPORTANTE: Las secciones del JSON deben REPLICAR las secciones de los ejemplos del usuario.
Si el usuario tiene 5 secciones con nombres especificos, tu JSON debe tener 5 secciones con esos mismos nombres.
Las notas de produccion deben incluir TODAS las especificaciones visuales y tecnicas relevantes."""


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
        prompt = _build_script_prompt(brief, niche_data, calendar.platform, template)

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


def rewrite_script(
    script: Script,
    feedback: list[dict],
    collection_name: str,
    platform: str,
    template: str | None = None,
) -> Script:
    """Rewrite a single script based on critic feedback."""
    brief = script.brief

    # Build feedback string
    feedback_text = "\n".join(
        f"- [{fb.get('type', 'general')}] {fb.get('description', '')} -> {fb.get('suggestion', '')}"
        for fb in feedback
    )

    niche_data = _get_niche_data_for_brief(collection_name, brief)
    platform_guide = PLATFORM_STYLE.get(platform, "")

    template_section = ""
    if template:
        template_section = f"""
## EJEMPLOS DEL USUARIO — FORMATO OBLIGATORIO:
{template}

REGLA PRINCIPAL: El guion reescrito DEBE usar las MISMAS secciones, nombres, estructura,
especificaciones de produccion (colores, fuentes, transiciones, texto en pantalla) y longitud
que los ejemplos. Analiza los ejemplos seccion por seccion y replicalos.
"""

    rewrite_prompt = f"""REESCRIBE este guión corrigiendo los problemas señalados.

## GUIÓN ORIGINAL:
Hook: {script.hook}
{"".join(f"### {s.title}\n{s.content}\n(Notas: {s.notes})\n" for s in script.sections)}
CTA: {script.cta}

## PROBLEMAS DETECTADOS POR EL CRÍTICO (CORREGIR TODOS):
{feedback_text}

## DIRECTRICES DE PLATAFORMA ({platform.upper()}):
{platform_guide}

## BRIEF ORIGINAL:
- Tema: {brief.topic}
- Pilar: {brief.pillar}
- Tipo: {brief.content_type}
- Objetivo: {brief.objective}

## DATOS DEL NICHO:
{niche_data}
{template_section}
## REGLAS DE REESCRITURA:
- Corrige TODOS los problemas señalados por el crítico.
- ELIMINA cualquier frase genérica de IA (ej: "En el mundo de hoy", "Sin más preámbulos").
- Usa lenguaje natural, directo y conversacional.
- Si hay ejemplos del usuario, las secciones del guion DEBEN tener los mismos nombres y estructura.
- Incluye especificaciones de produccion completas en las notas (colores, fuentes, transiciones, etc.).
- FORMATO DE DIÁLOGO: líneas del entrevistador empiezan con "-", acotaciones van entre paréntesis,
  respuestas del presentador son texto plano sin prefijo.

## FORMATO DE RESPUESTA (JSON):
{{
    "hook": "Hook corregido",
    "sections": [
        {{
            "title": "Nombre de seccion (MISMO que en los ejemplos del usuario)",
            "content": "Contenido corregido",
            "notes": "Especificaciones de produccion: colores, fuentes, transiciones, texto en pantalla, B-roll"
        }}
    ],
    "cta": "CTA corregido",
    "retention_tips": ["Tip 1", "Tip 2"],
    "strategic_justification": "Justificación"
}}"""

    response = generate(rewrite_prompt, system_instruction=SYSTEM_INSTRUCTION)

    try:
        return _parse_script_response(response, brief)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("Failed to parse rewritten script: %s", e)
        return script  # Return original if rewrite fails
