# ContentBrain — Resumen del Proyecto

**ContentBrain** es una pipeline de generación de contenido impulsada por IA. El usuario ingresa sus propias cuentas de redes sociales (o describe su nicho desde cero), y el sistema analiza su identidad de contenido, combina esa información con estructuras de contenido viral probadas, diseña una estrategia editorial personalizada y escribe guiones listos para grabar — exportando el resultado en PDF y Markdown.

**Stack:** Python · LangGraph · Qdrant · Gemini 2.5 Flash · sentence-transformers (all-MiniLM-L6-v2) · Apify · Streamlit

---

## Modos de entrada (UI)

El usuario elige uno de dos modos al inicio:

| Modo | Descripción | Input |
|---|---|---|
| **Tengo cuentas activas** | El usuario tiene contenido publicado | URLs de sus propias cuentas (YouTube / Instagram / TikTok) |
| **Estoy empezando desde cero** | El usuario no tiene contenido previo | Nombre de marca + descripción de negocio/nicho en texto libre |

Ambos modos recorren exactamente el mismo pipeline LangGraph. La diferencia está en cómo se construye el contexto inicial y en cómo se adaptan las instrucciones de los agentes.

---

## Pipeline LangGraph — Flujo de nodos

```
extract → index → strategize → write → critic ──→ compile
                                            ↓        ↑
                                          rewrite ───┘
```

**Estado compartido (`PipelineState`):** `input_mode`, `urls`, `niche_description`, `brand_name`, `platforms`, `calendar_config`, `template`, `extraction`, `index_result`, `calendars`, `writer_results`, `critic_approved`, `critic_feedback`, `critic_rounds`, `compiler_results`.

Checkpointing SQLite en cada nodo: si el pipeline falla a mitad, la UI detecta el estado guardado y reanuda desde el último paso exitoso.

---

## Agentes

### 1. Extractor — `src/agents/extractor.py`

Bifurca según el modo de entrada:

**Modo `own_account`:** Detecta la plataforma de la URL e invoca el scraper correspondiente:
- **YouTube**: `get_channel_videos` + `get_video_metadata` → título, descripción, transcript completo, vistas, likes, comentarios, duración
- **Instagram**: Apify actor `instagram-post-scraper` → descripción, hashtags, vistas, likes, comentarios
- **TikTok**: Apify actor → descripción, hashtags, shares, duración, vistas

Soporta múltiples URLs; combina todos los items en un único `ExtractionResult`.

**Modo `niche_description`:** Función `run_text_extractor()` — crea un `ExtractionResult` sintético con un único `ContentItem` que contiene la descripción del usuario como `description` y `transcript`. No realiza ninguna llamada externa.

---

### 2. Indexer — `src/agents/indexer.py`

Convierte los items del `ExtractionResult` en chunks semánticos y los almacena en Qdrant:
- **YouTube**: chunk 1 = título + descripción; chunks 2..N = transcript dividido en bloques de 500 palabras
- **Instagram / TikTok / texto**: un chunk por item (descripción + hashtags)

Genera embeddings con `all-MiniLM-L6-v2` (384 dims) y hace upsert en la colección `{platform}_{username}`.

Devuelve `IndexResult` con `collection_name`, `chunks_indexed`, `platform`, `username`.

---

### 3. Strategist — `src/agents/strategist.py`

El nodo más complejo. Realiza **dos búsquedas en Qdrant** antes de construir el prompt del calendario:

#### Búsqueda 1 — Identidad del usuario (colección propia)
*Solo en modo `own_account` con colección no vacía.*

Ejecuta 5 queries semánticas predefinidas contra la colección `{platform}_{username}` del usuario:
- "contenido viral con más engagement y views"
- "temas educativos y de autoridad en el nicho"
- "estrategias de venta y conversión en contenido"
- "hooks de apertura más efectivos"
- "temas y formatos con mejor rendimiento"

Deduplica y une hasta 30 resultados como bloque de contexto de identidad.

Luego extrae el **tono predominante** del usuario con una llamada corta a Gemini (ej: "Motivacional y Directo", "Educativo y Cercano").

*En modo `niche_description` o colección vacía: esta búsqueda se omite. Se usa la descripción de texto directamente.*

#### Búsqueda 2 — Biblioteca de Frameworks Virales (siempre)
Consulta la colección `viral_frameworks` **por cada uno de los 3 pilares** (viralidad, autoridad, venta):

| Pillar interno | `metadata.objetivo` en Qdrant |
|---|---|
| viralidad | `VIRAL_GROWTH` |
| autoridad | `AUTHORITY_BUILDER` |
| venta | `CONVERSION_SALES` |

Filtros aplicados en cada consulta:
1. `metadata.objetivo` → mapeado desde el pilar
2. `metadata.plataforma` → mapeado desde la plataforma destino (ej: `"instagram"` → `"Instagram"`)
3. `metadata.tono_predominante` → tono extraído del usuario *(opcional, con fallback sin este filtro si no hay resultados)*

La query vectorial usa un texto compuesto de `{pilar} {plataforma} {snippet del nicho}` para maximizar relevancia semántica.

Por cada pilar recupera hasta 2 frameworks: `template_maestro` + `hook_formula_logic` del `analisis_tecnico`.

#### Construcción del prompt

El prompt enviado a Gemini combina:
1. **Directrices de plataforma** (duración, ritmo, content_type)
2. **Datos de identidad del usuario** (historial propio o descripción de nicho)
3. **Ejemplos/lineamientos de marca** opcionales (archivos subidos por el usuario)
4. **Frameworks virales por pilar** (estructuras probadas con instrucción de replicar arquitectura)
5. **Configuración del calendario** (fechas, distribución: 40% viralidad / 30% autoridad / 30% venta)

La instrucción de sistema cambia según el modo:
- `own_account` → "Continúa y expande la línea editorial del creador"
- `niche_description` → "Diseña una estrategia óptima para posicionarse en este nicho desde cero"

Devuelve `ContentCalendar` con lista de `ContentBrief` (tema, ángulo, hook, pilar, fecha, content_type).

---

### 4. Writer — `src/agents/writer.py`

Escribe un guión completo por cada brief del calendario. Para cada uno:

1. Búsqueda semántica en la colección del usuario por `{topic} {angle}` → recupera datos contextuales relevantes
2. Construye prompt con: directrices de plataforma + brief + datos del nicho + (opcional) ejemplos del usuario
3. Llama a Gemini con instrucción de sistema adaptada al modo:
   - `own_account` → mantiene voz y estilo del creador, continúa su identidad
   - `niche_description` → primera persona genérica, auténtica para un creador que se posiciona
4. Parsea la respuesta JSON con reintentos ante fallos

**Formato de diálogo** (aplicado con color coding automático):
- Líneas del entrevistador: empiezan con `-`
- Acotaciones de dirección: entre paréntesis
- Respuestas del presentador: texto plano

**`rewrite_script()`**: reescribe guiones rechazados incorporando el feedback del Critic. Acepta `input_mode` para mantener consistencia de instrucciones.

---

### 5. Critic — `src/agents/critic.py`

Evalúa todos los guiones en dos pasos:

1. **Check local rápido**: detecta 16 frases genéricas de IA hardcodeadas ("En el mundo de hoy", "Sin más preámbulos", etc.)
2. **Evaluación LLM**: Gemini revisa especificidad, longitud adecuada a la plataforma, calidad del hook, cumplimiento del formato del usuario (si subió ejemplos)

Devuelve `{ approved: bool, feedback: { "{platform}_{i}": [issues] } }`. El workflow permite hasta **2 rondas** de revisión antes de forzar compilación.

---

### 6. Rewriter — `src/agents/writer.py` (`rewrite_script`)

Nodo del grafo que consume el feedback del Critic. Reconstruye solo los guiones rechazados (los aprobados se mantienen intactos) y devuelve la lista completa para una nueva ronda con el Critic.

---

### 7. Compiler — `src/agents/compiler.py`

Genera el documento final en dos formatos:
- **Markdown**: color coding HTML (verde = entrevistador, rojo = acotaciones, negro = respuesta)
- **PDF** (fpdf2): portada, resumen ejecutivo, tabla de calendario y guiones con los mismos colores

Nombre del archivo: `contentbrain_{platform}_{username}_{timestamp}.{ext}`

---

## Colecciones Qdrant

| Colección | Creada por | Contenido | Índices de payload |
|---|---|---|---|
| `{platform}_{username}` | Indexer | Chunks del contenido del usuario | — |
| `viral_frameworks` | Script de ingesta | Frameworks estructurales abstractos de contenido viral | `metadata.objetivo`, `metadata.plataforma`, `metadata.tono_predominante` |

---

## Scripts de ingesta

### `src/scripts/ingest_viral_frameworks.py`

Pipeline independiente del nicho que construye la **Biblioteca de Frameworks Virales**. Se ejecuta de forma manual (o periódicamente) para alimentar la colección `viral_frameworks`.

**Flujo:**
1. Recibe una lista de URLs (YouTube, Instagram, TikTok) vía CLI
2. Extrae los top-3 posts por views de cada cuenta con el `Extractor`
3. Construye un texto con título + descripción + transcript de cada post
4. Envía el contenido a Gemini con el system prompt del **Analista de Ingeniería Inversa**, que extrae:
   - `metadata`: objetivo, plataforma, tono_predominante, formato_tipo
   - `template_maestro`: esqueleto puro con variables genéricas `[RECUADROS]`
   - `analisis_tecnico`: hook_formula_logic, psychological_triggers, narrative_flow, visual_instructions, sound_design_vibe
   - `referencia_original`: URL de origen
5. Genera embedding del `template_maestro + formato_tipo`
6. Hace upsert en `viral_frameworks` con ID determinístico `uuid5(NAMESPACE_URL, url)`

**Parser robusto:** stripea markdown fences, intenta `json.loads()` directo, si falla extrae el primer objeto JSON del texto. Reintentos con backoff exponencial ante errores 503 de Gemini.

**Uso:**
```bash
cd src
PYTHONPATH=src uv run python scripts/ingest_viral_frameworks.py \
  "https://www.instagram.com/cuenta1/reels/" \
  "https://www.youtube.com/@canal"
```

---

## Servicios de soporte

| Servicio | Archivo | Descripción |
|---|---|---|
| LLM | `src/services/llm.py` | Cliente Gemini 2.5 Flash. `generate(prompt, system_instruction)` |
| Embeddings | `src/services/embeddings.py` | `all-MiniLM-L6-v2` via sentence-transformers. `generate_embeddings(texts)` → 384-dim |
| Qdrant | `src/services/qdrant.py` | `ensure_collection`, `upsert_chunks`, `search`, `search_viral_frameworks` (con filtrado por objetivo/plataforma/tono + fallback), `ensure_viral_frameworks_collection`, `upsert_viral_framework` |
| Apify | `src/services/apify.py` | Scraping de Instagram y TikTok |
| YouTube | `src/services/youtube.py` | `get_channel_videos` + `get_video_metadata` (yt-dlp) |
