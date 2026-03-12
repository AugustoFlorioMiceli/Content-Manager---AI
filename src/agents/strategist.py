import json
import logging
from datetime import timedelta

from models.content import IndexResult
from models.strategy import CalendarConfig, ContentBrief, ContentCalendar
from services.embeddings import generate_embeddings
from services.llm import generate
from services.qdrant import search, search_viral_frameworks

logger = logging.getLogger(__name__)

# Mapping from internal pillar names to viral_frameworks metadata values
PILLAR_TO_OBJETIVO = {
    "viralidad": "VIRAL_GROWTH",
    "autoridad": "AUTHORITY_BUILDER",
    "venta": "CONVERSION_SALES",
}

# Mapping from internal platform keys to viral_frameworks metadata values
PLATFORM_DISPLAY_MAP = {
    "instagram": "Instagram",
    "youtube": "YouTube",
    "tiktok": "TikTok",
}

NICHE_QUERIES = [
    "contenido viral con más engagement y views",
    "temas educativos y de autoridad en el nicho",
    "estrategias de venta y conversión en contenido",
    "hooks de apertura más efectivos",
    "temas y formatos con mejor rendimiento",
]

PLATFORM_GUIDELINES = {
    "youtube": """DIRECTRICES PARA YOUTUBE (formato largo/horizontal):
- Videos de 8-20 minutos ideales para autoridad y profundidad
- Estructura: hook impactante + desarrollo con datos + CTA claro
- Contenido educativo, tutoriales, análisis profundos, casos de estudio
- Pattern interrupts cada 30-60 segundos (cambio de ángulo, gráficos, preguntas)
- Los temas pueden ser complejos y detallados, el formato lo permite
- content_type debe ser "video"
""",
    "instagram": """DIRECTRICES PARA INSTAGRAM (formato vertical/corto):
- Reels de 30-90 segundos, dinámicos y visualmente atractivos
- Hook en los primeros 2 segundos (pregunta provocativa, dato impactante, controversia)
- UNA sola idea potente por reel, no intentar cubrir todo
- Ritmo rápido: frases cortas, cortes rápidos, texto en pantalla
- Contenido que genere guardados y compartidos
- Buscar ideas llamativas, controversiales o sorprendentes del nicho
- content_type debe ser "reel" o "carousel"
""",
    "tiktok": """DIRECTRICES PARA TIKTOK (formato vertical/corto):
- Videos de 15-60 segundos, ultra dinámicos
- Hook inmediato en el primer segundo
- Tendencias y formatos virales del momento
- Storytelling rápido, datos impactantes en formato snackable
- content_type debe ser "short"
""",
}

_SYSTEM_BASE = """Eres un estratega de contenido digital experto. Tu trabajo es diseñar calendarios editoriales
de alto rendimiento basados en datos reales de un nicho específico.

{context}

Reglas clave:
- Cada pieza de contenido debe estar asignada a uno de los tres pilares: viralidad, autoridad o venta
- VIRALIDAD (~40%): Hooks potentes, temas trending, formato corto, máxima retención
- AUTORIDAD (~30%): Contenido educativo profundo basado en datos reales del nicho
- VENTA (~30%): Copywriting persuasivo, CTAs directos, storytelling de transformación
- Los hooks deben ser específicos y provocativos, nunca genéricos
- Cada brief debe estar respaldado por datos reales del nicho analizado

IMPORTANTE: Responde ÚNICAMENTE con un JSON válido, sin texto adicional ni markdown.
"""

_CONTEXT_OWN_ACCOUNT = """CONTEXTO CRÍTICO:
- Los datos que recibes provienen de la PROPIA cuenta del creador.
- El calendario es una CONTINUACIÓN Y EXPANSIÓN de su línea editorial actual.
- Identifica qué temas, formatos y ángulos ya han funcionado para este creador y potencíalos.
- Introduce variaciones y evoluciones naturales sobre los contenidos existentes, no repitas exactamente lo mismo.
- ADAPTA el contenido al formato de la plataforma de destino."""

_CONTEXT_NICHE_DESCRIPTION = """CONTEXTO CRÍTICO:
- El creador está comenzando desde cero: los datos provienen de su descripción de negocio/nicho.
- Diseña una estrategia optimizada para posicionarse en ese nicho desde el inicio.
- Basa los briefs en las mejores prácticas del nicho descrito y las directrices de la plataforma.
- ADAPTA el contenido al formato de la plataforma de destino."""


def _get_system_instruction(input_mode: str) -> str:
    context = _CONTEXT_OWN_ACCOUNT if input_mode == "own_account" else _CONTEXT_NICHE_DESCRIPTION
    return _SYSTEM_BASE.format(context=context)


# --- Search 1: User identity (own collection) ---

def _query_niche_insights(collection_name: str) -> str:
    """Query the user's Qdrant collection for their existing content patterns.
    Returns empty string if the collection has no real content.
    """
    all_results = []

    for query in NICHE_QUERIES:
        query_embedding = generate_embeddings([query])[0]
        results = search(collection_name, query_embedding, limit=5)
        for r in results:
            text = r.get("text", "")
            if text and text not in all_results:
                all_results.append(text)

    return "\n---\n".join(all_results[:30])


def _extract_user_tone(niche_context: str) -> str | None:
    """Extract the predominant tone from the user's content via a short Gemini call."""
    if not niche_context.strip():
        return None

    prompt = (
        "Lee el siguiente contenido de un creador y describe su tono predominante "
        "en 2-4 palabras (ejemplos: 'Motivacional y Directo', 'Educativo y Cercano', "
        "'Humorístico y Casual', 'Profesional y Analítico', 'Inspiracional y Empático'):\n\n"
        f"{niche_context[:2000]}\n\n"
        "Responde ÚNICAMENTE con el nombre del tono, sin explicaciones ni puntuación extra."
    )
    try:
        tone = generate(prompt).strip().strip(".")
        return tone[:60] if tone else None
    except Exception as exc:
        logger.warning("Could not extract user tone: %s", exc)
        return None


# --- Search 2: Viral frameworks library ---

def _query_viral_frameworks_for_pillar(
    pillar: str,
    platform: str,
    user_tone: str | None,
    niche_snippet: str,
) -> str:
    """Fetch viral framework templates for a given pillar, filtered by objetivo + plataforma (+ tone)."""
    objetivo = PILLAR_TO_OBJETIVO.get(pillar.lower(), "VIRAL_GROWTH")
    plataforma = PLATFORM_DISPLAY_MAP.get(platform.lower(), platform.capitalize())

    query_text = f"{pillar} {platform} {niche_snippet[:300]}"
    query_embedding = generate_embeddings([query_text])[0]

    results = search_viral_frameworks(
        query_embedding=query_embedding,
        objetivo=objetivo,
        plataforma=plataforma,
        tono=user_tone,
        limit=2,
    )

    if not results:
        return ""

    parts = []
    for r in results:
        template = r.get("template_maestro", "")
        if isinstance(template, list):
            template = " ".join(str(x) for x in template)
        fmt = r.get("metadata", {}).get("formato_tipo", "desconocido")
        hook_logic = r.get("analisis_tecnico", {}).get("hook_formula_logic", "")
        section = f"[{fmt}]\nEsqueleto:\n{template}"
        if hook_logic:
            section += f"\nLógica del hook: {hook_logic}"
        parts.append(section)

    return "\n\n".join(parts)


def _build_viral_frameworks_section(
    platform: str,
    user_tone: str | None,
    niche_snippet: str,
) -> str:
    """Build the full viral frameworks block for the 3 pillars."""
    lines = ["## FRAMEWORKS VIRALES (estructuras probadas — úsalas como molde para los briefs):"]
    found_any = False

    for pillar, label in [
        ("viralidad", "VIRALIDAD"),
        ("autoridad", "AUTORIDAD"),
        ("venta", "VENTA"),
    ]:
        frameworks = _query_viral_frameworks_for_pillar(pillar, platform, user_tone, niche_snippet)
        if frameworks:
            found_any = True
            lines.append(f"\n### Para piezas de {label}:\n{frameworks}")

    if not found_any:
        return ""

    lines.append(
        "\nINSTRUCCIÓN: Usa estos esqueletos como base estructural para los briefs del pilar "
        "correspondiente. Adapta el tema y el ángulo al nicho del usuario, pero mantén la "
        "arquitectura de hook, loop y cierre de cada framework."
    )
    return "\n".join(lines)


# --- Prompt builder ---

def _build_strategy_prompt(
    niche_context: str,
    viral_frameworks_section: str,
    config: CalendarConfig,
    platform: str,
    user_context: str | None = None,
    niche_description: str | None = None,
    input_mode: str = "own_account",
) -> str:
    total = config.total_posts
    virality = round(total * 0.4)
    authority = round(total * 0.3)
    sales = total - virality - authority

    dates = []
    current_date = config.start_date
    posts_scheduled = 0
    while posts_scheduled < total:
        if current_date.weekday() < 7:
            week_num = (current_date - config.start_date).days // 7
            week_posts = sum(1 for d in dates if (d - config.start_date).days // 7 == week_num)
            if week_posts < config.posts_per_week:
                dates.append(current_date)
                posts_scheduled += 1
        current_date += timedelta(days=1)

    dates_str = ", ".join(d.isoformat() for d in dates)

    # Section 1: user identity data (own content or niche description)
    if input_mode == "own_account" and niche_context.strip():
        identity_section = f"## TUS DATOS DE CONTENIDO (historial real de tu cuenta):\n{niche_context}"
    elif niche_description:
        identity_section = f"## DESCRIPCIÓN DE NICHO (información proporcionada por el creador):\n{niche_description}"
    else:
        identity_section = ""

    # Section 2: uploaded brand guidelines / examples
    user_context_section = ""
    if user_context:
        user_context_section = (
            f"\n## CONTEXTO DEL USUARIO (imagen de marca, ejemplos de guiones):\n{user_context}\n"
            "Usa esta información para alinear la estrategia con la identidad de marca y estilo del usuario."
        )

    platform_guide = PLATFORM_GUIDELINES.get(platform, "")

    return f"""Analiza el siguiente contexto y genera un calendario editorial para {platform.upper()}.

## DIRECTRICES DE LA PLATAFORMA:
{platform_guide}

{identity_section}
{user_context_section}

{viral_frameworks_section}

## CONFIGURACIÓN:
- Plataforma: {platform}
- Publicaciones por semana: {config.posts_per_week}
- Período: {config.period_weeks} semanas
- Total de piezas: {total}
- Distribución de pilares: viralidad={virality}, autoridad={authority}, venta={sales}
- Fechas asignadas: {dates_str}

## FORMATO DE RESPUESTA (JSON):
{{
    "strategy_summary": "Resumen de 2-3 oraciones explicando la estrategia general",
    "briefs": [
        {{
            "day": 1,
            "date": "YYYY-MM-DD",
            "pillar": "viralidad|autoridad|venta",
            "topic": "Tema principal de la pieza",
            "angle": "Ángulo o enfoque específico",
            "hook": "Hook de apertura exacto (primeros 3-5 segundos)",
            "objective": "Objetivo específico de esta pieza",
            "content_type": "video|reel|carousel|short",
            "reference_data": ["Dato del nicho que respalda esta decisión"]
        }}
    ]
}}

Genera exactamente {total} briefs, uno para cada fecha. Usa las fechas proporcionadas en orden."""


def _parse_calendar_response(
    response: str,
    config: CalendarConfig,
) -> tuple[list[ContentBrief], str, dict[str, int]]:
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    data = json.loads(cleaned)

    briefs = []
    for item in data["briefs"]:
        briefs.append(ContentBrief(**item))

    strategy_summary = data.get("strategy_summary", "")

    distribution: dict[str, int] = {}
    for brief in briefs:
        pillar = brief.pillar.lower()
        distribution[pillar] = distribution.get(pillar, 0) + 1

    return briefs, strategy_summary, distribution


def run_strategist(
    index_result: IndexResult,
    config: CalendarConfig | None = None,
    user_context: str | None = None,
    platform: str | None = None,
    input_mode: str = "own_account",
    niche_description: str | None = None,
) -> ContentCalendar:
    if config is None:
        config = CalendarConfig()

    target_platform = platform or index_result.platform

    logger.info(
        "Generating strategy for @%s on %s: %d posts/week, %d weeks",
        index_result.username,
        target_platform,
        config.posts_per_week,
        config.period_weeks,
    )

    # --- Search 1: User identity ---
    # For own_account: query Qdrant for existing content patterns + extract tone.
    # For niche_description: skip Qdrant search, use the description directly.
    if input_mode == "own_account" and index_result.chunks_indexed > 0:
        logger.info("Search 1: querying user collection '%s'", index_result.collection_name)
        niche_context = _query_niche_insights(index_result.collection_name)
        logger.info("Search 1: retrieved %d chars of niche context", len(niche_context))

        logger.info("Extracting user tone from niche context")
        user_tone = _extract_user_tone(niche_context)
        logger.info("Detected user tone: %s", user_tone)
    else:
        logger.info("Search 1: skipped (niche_description mode or empty collection)")
        niche_context = ""
        user_tone = None

    # --- Search 2: Viral frameworks (always) ---
    niche_snippet = niche_context or niche_description or ""
    logger.info("Search 2: querying viral_frameworks for platform=%s, tone=%s", target_platform, user_tone)
    viral_frameworks_section = _build_viral_frameworks_section(target_platform, user_tone, niche_snippet)
    if viral_frameworks_section:
        logger.info("Search 2: viral frameworks section built (%d chars)", len(viral_frameworks_section))
    else:
        logger.warning("Search 2: no viral frameworks found (collection may be empty)")

    # --- Build prompt & call Gemini ---
    prompt = _build_strategy_prompt(
        niche_context=niche_context,
        viral_frameworks_section=viral_frameworks_section,
        config=config,
        platform=target_platform,
        user_context=user_context,
        niche_description=niche_description,
        input_mode=input_mode,
    )

    response = generate(prompt, system_instruction=_get_system_instruction(input_mode))
    logger.info("Received strategy response (%d chars)", len(response))

    briefs, strategy_summary, distribution = _parse_calendar_response(response, config)

    clean_config = CalendarConfig(**config.model_dump())

    return ContentCalendar(
        platform=target_platform,
        username=index_result.username,
        config=clean_config,
        briefs=briefs,
        strategy_summary=strategy_summary,
        pillar_distribution=distribution,
    )
