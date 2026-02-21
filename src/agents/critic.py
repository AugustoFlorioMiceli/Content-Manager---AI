import json
import logging

from models.strategy import Script, WriterResult
from services.llm import generate

logger = logging.getLogger(__name__)

GENERIC_PHRASES = [
    "en el mundo de hoy",
    "en la era digital",
    "en el panorama actual",
    "como todos sabemos",
    "no es ningún secreto",
    "en este artículo",
    "sin más preámbulos",
    "en la actualidad",
    "hoy en día más que nunca",
    "es fundamental entender",
    "a lo largo de la historia",
    "en un mundo cada vez más",
    "it's no secret",
    "in today's world",
    "let's dive in",
    "without further ado",
]

SYSTEM_INSTRUCTION = """Eres un crítico experto de guiones de contenido digital. Tu trabajo es evaluar si un guión
cumple con los estándares de calidad y formato requeridos.

Evalúas con rigor pero de forma constructiva. Tu objetivo es que el guión final sea útil y profesional,
no genérico ni artificial.

IMPORTANTE: Responde ÚNICAMENTE con un JSON válido, sin texto adicional ni markdown.
"""


def _build_critique_prompt(
    script: Script,
    platform: str,
    template: str | None = None,
) -> str:
    # Serialize script content for evaluation
    script_text = f"""HOOK: {script.hook}

"""
    for section in script.sections:
        script_text += f"## {section.title}\n{section.content}\n"
        if section.notes:
            script_text += f"(Nota: {section.notes})\n"
        script_text += "\n"

    if script.cta:
        script_text += f"CTA: {script.cta}\n"

    template_section = ""
    if template:
        template_section = f"""
## EJEMPLOS DE REFERENCIA DEL USUARIO (COMPARACION OBLIGATORIA):
{template}

EVALUACION DE FORMATO — ANALIZA ESTO CON DETALLE:
1. Cuenta las secciones del ejemplo y las del guion. ¿Coinciden?
2. Compara los NOMBRES de las secciones. ¿Usa los mismos titulos?
3. Compara la LONGITUD de cada seccion. ¿Es similar?
4. ¿El ejemplo incluye especificaciones de produccion (colores, fuentes, transiciones,
   texto en pantalla)? Si si, ¿el guion tambien las incluye?
5. ¿El tono y estilo de escritura son consistentes con el ejemplo?

Si el guion NO replica la estructura del ejemplo, DEBE ser rechazado.
"""

    return f"""Evalúa el siguiente guión para {platform.upper()}.

## GUIÓN A EVALUAR:
Tema: {script.brief.topic}
Pilar: {script.brief.pillar}
Tipo: {script.brief.content_type}

{script_text}
{template_section}
## CRITERIOS DE EVALUACIÓN (en orden de prioridad):

1. **Formato vs ejemplos** (CRITICO si hay ejemplos): ¿Las secciones del guion tienen los mismos
   nombres, cantidad y estructura que los ejemplos del usuario? ¿Incluye las mismas especificaciones
   de produccion (colores, fuentes, transiciones, texto en pantalla)? RECHAZAR si no coincide.
2. **Lenguaje genérico de IA**: ¿Usa frases cliché como "En el mundo de hoy", "Es fundamental entender",
   "Sin más preámbulos", "En la era digital"? RECHAZAR si las usa.
3. **Especificidad**: ¿Usa datos concretos del nicho o es vago y genérico?
4. **Longitud apropiada**: Para Instagram/TikTok debe ser corto y dinámico (max 400 palabras).
   Para YouTube puede ser largo y detallado.
5. **Hook**: ¿Es específico y provocativo o es genérico?
6. **Identidad**: ¿Adopta la identidad de algún creador de referencia? NO debe hacerlo.

## FORMATO DE RESPUESTA (JSON):
{{
    "approved": true/false,
    "issues": [
        {{
            "type": "formato|especificaciones|lenguaje_generico|especificidad|longitud|hook|identidad",
            "description": "Descripción específica del problema. Si es de formato, indicar que secciones faltan o sobran.",
            "suggestion": "Cómo corregirlo concretamente. Si faltan especificaciones, indicar cuales."
        }}
    ],
    "summary": "Resumen breve de la evaluación"
}}

Si el guión es aceptable, devuelve approved=true con issues vacío.
Sé estricto: no apruebes guiones con lenguaje genérico de IA o que no sigan el formato de los ejemplos."""


def _check_generic_phrases(script: Script) -> list[dict]:
    """Fast local check for known generic AI phrases."""
    issues = []
    all_text = script.hook.lower()
    for section in script.sections:
        all_text += " " + section.content.lower()
    if script.cta:
        all_text += " " + script.cta.lower()

    for phrase in GENERIC_PHRASES:
        if phrase.lower() in all_text:
            issues.append({
                "type": "lenguaje_generico",
                "description": f"Usa la frase genérica: '{phrase}'",
                "suggestion": f"Reemplazar '{phrase}' con una apertura específica al tema del nicho.",
            })

    return issues


def run_critic(
    writer_results: list[WriterResult],
    template: str | None = None,
) -> dict:
    """Evaluate scripts and return feedback.

    Returns:
        dict with:
        - approved: bool (True if all scripts pass)
        - feedback: dict mapping (platform, script_index) to list of issues
        - summary: str
    """
    all_feedback = {}
    all_approved = True

    for wr in writer_results:
        platform = wr.platform

        for i, script in enumerate(wr.scripts):
            script_key = f"{platform}_{i}"
            issues = []

            # 1. Fast local check for generic phrases
            local_issues = _check_generic_phrases(script)
            issues.extend(local_issues)

            # 2. LLM-based deep evaluation
            try:
                prompt = _build_critique_prompt(script, platform, template)
                response = generate(prompt, system_instruction=SYSTEM_INSTRUCTION)

                # Parse response
                cleaned = response.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[1]
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                    cleaned = cleaned.strip()

                # Find JSON
                if not cleaned.startswith("{"):
                    start = cleaned.find("{")
                    if start != -1:
                        depth = 0
                        for j, c in enumerate(cleaned[start:], start):
                            if c == "{":
                                depth += 1
                            elif c == "}":
                                depth -= 1
                                if depth == 0:
                                    cleaned = cleaned[start:j + 1]
                                    break

                critique = json.loads(cleaned)

                llm_issues = critique.get("issues", [])
                issues.extend(llm_issues)

                if not critique.get("approved", True) or local_issues:
                    all_approved = False

            except (json.JSONDecodeError, Exception) as e:
                logger.warning(
                    "Failed to parse critic response for %s script %d: %s",
                    platform, i, e,
                )
                # If we can't parse the critique but found local issues, still reject
                if local_issues:
                    all_approved = False

            if issues:
                all_feedback[script_key] = issues
                logger.info(
                    "Critic found %d issues in %s script %d: %s",
                    len(issues), platform, i, script.brief.topic,
                )

    return {
        "approved": all_approved,
        "feedback": all_feedback,
        "summary": (
            "Todos los guiones aprobados."
            if all_approved
            else f"Se encontraron problemas en {len(all_feedback)} guion(es). Reescribiendo."
        ),
    }
