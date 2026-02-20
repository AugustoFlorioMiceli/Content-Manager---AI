import json
import logging
from datetime import timedelta

from models.content import IndexResult
from models.strategy import CalendarConfig, ContentBrief, ContentCalendar
from services.embeddings import generate_embeddings
from services.llm import generate
from services.qdrant import search

logger = logging.getLogger(__name__)

NICHE_QUERIES = [
    "contenido viral con más engagement y views",
    "temas educativos y de autoridad en el nicho",
    "estrategias de venta y conversión en contenido",
    "hooks de apertura más efectivos",
    "temas y formatos con mejor rendimiento",
]

SYSTEM_INSTRUCTION = """Eres un estratega de contenido digital experto. Tu trabajo es diseñar calendarios editoriales
de alto rendimiento basados en datos reales de un nicho específico.

CONTEXTO CRÍTICO:
- Los datos que recibes provienen de canales/cuentas de REFERENCIA analizados para entender el nicho.
- El calendario es para un NUEVO creador que quiere posicionarse en ese nicho.
- NUNCA uses nombres, identidades o personas de los creadores de referencia en los briefs.
- Usa los datos como inteligencia de mercado: qué temas funcionan, qué formatos tienen mejor rendimiento, qué ángulos generan engagement.

Reglas clave:
- Cada pieza de contenido debe estar asignada a uno de los tres pilares: viralidad, autoridad o venta
- VIRALIDAD (~40%): Hooks potentes, temas trending, formato corto, máxima retención
- AUTORIDAD (~30%): Contenido educativo profundo basado en datos reales del nicho
- VENTA (~30%): Copywriting persuasivo, CTAs directos, storytelling de transformación
- Los hooks deben ser específicos y provocativos, nunca genéricos
- Cada brief debe estar respaldado por datos reales del nicho analizado

IMPORTANTE: Responde ÚNICAMENTE con un JSON válido, sin texto adicional ni markdown.
"""


def _query_niche_insights(collection_name: str) -> str:
    all_results = []

    for query in NICHE_QUERIES:
        query_embedding = generate_embeddings([query])[0]
        results = search(collection_name, query_embedding, limit=5)
        for r in results:
            text = r.get("text", "")
            if text and text not in all_results:
                all_results.append(text)

    return "\n---\n".join(all_results[:30])


def _build_strategy_prompt(
    niche_context: str,
    config: CalendarConfig,
    platform: str,
    user_context: str | None = None,
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

    user_context_section = ""
    if user_context:
        user_context_section = f"""
## CONTEXTO DEL USUARIO (imagen de marca, ejemplos de guiones, indicaciones):
{user_context}

Usa esta información para alinear la estrategia con la identidad de marca y estilo del usuario.
"""

    return f"""Analiza el siguiente contexto de un nicho en {platform} y genera un calendario editorial.

## CONTEXTO DEL NICHO (datos reales extraídos):
{niche_context}
{user_context_section}

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

    # 1. Query Qdrant for niche insights
    niche_context = _query_niche_insights(index_result.collection_name)
    logger.info("Retrieved niche context (%d chars)", len(niche_context))

    # 2. Build prompt
    prompt = _build_strategy_prompt(niche_context, config, target_platform, user_context)

    # 3. Call Gemini
    response = generate(prompt, system_instruction=SYSTEM_INSTRUCTION)
    logger.info("Received strategy response (%d chars)", len(response))

    # 4. Parse response
    briefs, strategy_summary, distribution = _parse_calendar_response(response, config)

    # Convert config to fresh instance to avoid checkpointer deserialization issues
    clean_config = CalendarConfig(**config.model_dump())

    return ContentCalendar(
        platform=target_platform,
        username=index_result.username,
        config=clean_config,
        briefs=briefs,
        strategy_summary=strategy_summary,
        pillar_distribution=distribution,
    )
