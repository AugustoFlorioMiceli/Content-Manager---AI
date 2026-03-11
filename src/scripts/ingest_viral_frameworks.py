import json
import logging
import re
import time
import uuid

from agents.extractor import run_extractor
from models.content import ExtractionResult
from services.embeddings import generate_embeddings
from services.llm import generate
from services.qdrant import ensure_viral_frameworks_collection, upsert_viral_framework

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COLLECTION_NAME = "viral_frameworks"

ANALYST_SYSTEM_PROMPT = """ROL:
Eres un Ingeniero de Reversa de Contenido de Alto Impacto. Tu especialidad es desmantelar videos virales para extraer su arquitectura lógica y psicológica. Tu objetivo es ignorar el "qué" (el tema) para capturar el "cómo" (el framework).

REGLAS DE ORO PARA EL ANÁLISIS:
- **Abstracción Total de Contenido:** Está estrictamente prohibido mencionar el tema original, marcas o nichos. Debes anonimizar toda la información transformándola en variables genéricas como: [PROBLEMA_ESPECÍFICO], [MÉTODO_X], [RESULTADO_DESEADO], [OBJECIÓN_COMÚN], [HERRAMIENTA_Y].
- **Enfoque en la Estructura:** No resumas lo que se dice; describe por qué se dice cada frase en ese momento exacto y cómo está construida sintácticamente.
- **Diagnóstico Psicológico:** Identifica y explica la función de disparadores emocionales y sesgos cognitivos presentes (ej: Aversión a la pérdida, Prueba Social, Sesgo de Curiosidad, Efecto de Contraste, Autoridad, etc.).

ESQUEMA DE INGENIERÍA REQUERIDO:
1. ARQUITECTURA DEL GANCHO (HOOK - 0 a 5s):
   - Fórmula Sintáctica: La estructura gramatical exacta de la oración inicial.
   - Mecánica de Retención: Cómo detiene el scroll.
   - Gatillo Psicológico: Qué sesgo o emoción dispara inmediatamente.
2. CONSTRUCCIÓN DEL BUCLE (THE LOOP):
   - Open Loops: Qué interrogante o beneficio futuro plantea.
   - Gestión del Ritmo: Conexión entre el hook y el contenido.
3. FRAMEWORK DEL CUERPO (CORE STRUCTURE):
   - Modelo Lógico: (Ej: '3 Pasos hacia el Éxito', 'Antes vs. Después').
   - Secuencia de Entrega: Describe el flujo de argumentos usando variables genéricas.
   - Puntos de Tensión: Momentos de conflicto o validación.
4. EL CIERRE TÁCTICO (THE CLOSE):
   - Trigger de Conversión: Mecanismo de acción (Ej: Reciprocidad, Escasez).
   - Estructura del CTA: Fórmula del llamado a la acción final.
5. ADN DEL FORMATO (PACING & TONE):
   - Densidad Semántica y Tono de Voz.
6. ESTILO DE EDICIÓN Y FORMATO VISUAL (VISUAL CUES):
   - Dinámica de cortes, elementos en pantalla y diseño sonoro.

📥 OUTPUT REQUERIDO (JSON format):
{
  "metadata": {
    "objetivo": "[VIRAL_GROWTH | AUTHORITY_BUILDER | CONVERSION_SALES]",
    "plataforma": "[YouTube | Instagram | TikTok]",
    "tono_predominante": "Nombre del tono",
    "formato_tipo": "Ej: Listicle, Storytelling, Quick Tip"
  },
  "template_maestro": "Genera aquí el ESQUELETO PURO del video. Un guion lleno de espacios en blanco [RECUADROS_CON_VARIABLE] para inyectar contenido de cualquier nicho.",
  "analisis_tecnico": {
    "hook_formula_logic": "Explicación de la lógica detrás del gancho.",
    "psychological_triggers_detail": "Lista de disparadores detectados y CÓMO se manifiestan.",
    "narrative_flow": "Descripción del arco de tensión.",
    "visual_instructions": "Instrucciones detalladas de edición.",
    "sound_design_vibe": "Tipo de música y SFX."
  },
  "referencia_original": "URL_DEL_VIDEO"
}

GUÍA PARA EL LLENADO DEL ANÁLISIS TÉCNICO:
- hook_formula_logic: Define la intención y por qué funciona.
- psychological_triggers_detail: Servirá al agente Critic para validar la carga emocional.
- visual_instructions: Instrucciones claras para el dinamismo visual."""


def _build_raw_content(extraction: ExtractionResult) -> str:
    sorted_items = sorted(
        extraction.items,
        key=lambda item: item.views or 0,
        reverse=True,
    )
    top_items = sorted_items[:3]

    parts = []
    for item in top_items:
        section = f"Title: {item.title or ''}\nDescription: {item.description or ''}\nTranscript: {item.transcript or ''}"
        parts.append(section)

    joined = "\n\n---\n\n".join(parts)
    return f"Analiza el siguiente contenido viral y extrae su framework estructural:\n\n{joined}"


def _parse_framework_json(text: str) -> dict:
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?", "", text.strip())
    cleaned = cleaned.strip()
    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Extract first JSON object from the text (handles prose before/after JSON)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Failed to parse LLM response as JSON: {text}")


def _generate_with_retry(prompt: str, max_retries: int = 5) -> str:
    delay = 10
    for attempt in range(max_retries):
        try:
            return generate(prompt, system_instruction=ANALYST_SYSTEM_PROMPT)
        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            logger.warning("Gemini error (attempt %d/%d): %s — retrying in %ds", attempt + 1, max_retries, exc, delay)
            time.sleep(delay)
            delay *= 2


def ingest(urls: list[str]) -> None:
    ensure_viral_frameworks_collection()

    for url in urls:
        logger.info("Processing URL: %s", url)

        extraction = run_extractor(url)
        raw_text = _build_raw_content(extraction)

        llm_response = _generate_with_retry(raw_text)
        framework = _parse_framework_json(llm_response)

        framework["referencia_original"] = url

        template = framework["template_maestro"]
        if isinstance(template, list):
            template = " ".join(str(x) for x in template)
        embed_text = template + " " + framework["metadata"]["formato_tipo"]
        embedding = generate_embeddings([embed_text])[0]

        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, url))
        upsert_viral_framework(framework, embedding, point_id)

        logger.info("Successfully ingested framework for %s (id=%s)", url, point_id)


if __name__ == "__main__":
    import sys

    urls = sys.argv[1:]
    if not urls:
        print("Usage: python ingest_viral_frameworks.py <url1> [url2] ...")
        sys.exit(1)
    ingest(urls)
