# ContentBrain — Resumen del Proyecto

**ContentBrain** es una pipeline de generación de contenido impulsada por IA. Dado uno o más perfiles de redes sociales (YouTube, Instagram, TikTok), analiza el nicho, diseña una estrategia editorial y escribe guiones listos para grabar, exportando el resultado en PDF y Markdown.

**Stack:** Python · LangGraph · Qdrant · Gemini 2.5 Flash · sentence-transformers (all-MiniLM-L6-v2)

---

## Pipeline LangGraph — Flujo de nodos

```
extract → index → strategize → write → critic ──→ compile
                                            ↓        ↑
                                          rewrite ───┘
```

---

## Agentes

### 1. Extractor — `src/agents/extractor.py`
Detecta la plataforma a partir de la URL e invoca el scraper correspondiente:
- **YouTube**: `get_channel_videos` + `get_video_metadata` (título, descripción, transcript, métricas)
- **Instagram**: Apify scraper → posts con descripción, hashtags y engagement
- **TikTok**: Apify scraper → videos con descripción, hashtags, shares y duración

Soporta múltiples URLs; los resultados se combinan en un único `ExtractionResult`.

---

### 2. Indexer — `src/agents/indexer.py`
Convierte los items extraídos en chunks y los almacena en Qdrant:
- YouTube: chunk de metadatos (título + descripción) + chunks de transcript
- Instagram/TikTok: un chunk por post (descripción + hashtags)
- Genera embeddings con all-MiniLM-L6-v2 (384 dims) y hace upsert en una colección `{platform}_{username}`

---

### 3. Strategist — `src/agents/strategist.py`
Diseña el calendario editorial. Consulta Qdrant con 5 queries semánticas sobre el nicho, construye un prompt con directrices de plataforma y distribución de pilares (40% viralidad / 30% autoridad / 30% venta) y llama a Gemini para obtener los **briefs**: tema, ángulo, hook, objetivo, tipo de contenido y fecha.

En el futuro consultará también la colección `viral_frameworks` filtrando por `objetivo`, `plataforma` y `tono_predominante` para inyectar patrones estructurales probados en los briefs.

---

### 4. Writer — `src/agents/writer.py`
Escribe un guión completo por cada brief. Para cada uno:
1. Recupera datos del nicho desde Qdrant (búsqueda semántica por tema+ángulo)
2. Construye el prompt con directrices de plataforma y, opcionalmente, ejemplos del usuario
3. Llama a Gemini (con un reintento en caso de fallo de parseo)

También expone `rewrite_script()` para reescribir guiones individuales con feedback del crítico.

---

### 5. Critic — `src/agents/critic.py`
Evalúa la calidad de todos los guiones en dos pasos:
1. **Check local rápido**: detecta frases genéricas de IA (lista de 16 patrones hardcodeados)
2. **Evaluación LLM**: Gemini revisa formato vs. ejemplos del usuario, especificidad, longitud, hook e identidad

Devuelve `approved: bool` + feedback por guión. El workflow permite hasta **2 rondas** de corrección antes de forzar la compilación.

---

### 6. Rewriter — `src/agents/writer.py` (`rewrite_script`)
Nodo del grafo que aplica el feedback del crítico. Reconstruye solo los guiones rechazados, mantiene los aprobados intactos, y devuelve la lista completa actualizada para una nueva ronda con el crítico.

---

### 7. Compiler — `src/agents/compiler.py`
Genera el documento final en dos formatos:
- **Markdown**: con color coding HTML (verde = entrevistador, rojo = acotaciones, negro = respuesta)
- **PDF** (fpdf2): portada, resumen ejecutivo, tabla de calendario y guiones con los mismos colores

El nombre del archivo incluye timestamp: `contentbrain_{platform}_{username}_{timestamp}.{ext}`

---

## Scripts de ingesta

### `src/scripts/ingest_viral_frameworks.py`
Pipeline independiente del nicho que construye la **Biblioteca de Frameworks Virales** (`viral_frameworks` en Qdrant):
1. Recibe una lista de URLs (YouTube, Instagram, TikTok) vía CLI
2. Extrae los top-3 posts por views con el `Extractor`
3. Envía el contenido crudo a Gemini actuando como **Analista de Ingeniería Inversa** para extraer el framework estructural y psicológico abstracto (hook, loop, core structure, close, pacing, visual cues)
4. Almacena el JSON resultante en Qdrant con embedding del `template_maestro`

La colección tiene índices de payload en `metadata.objetivo`, `metadata.plataforma` y `metadata.tono_predominante` para filtrado exacto por el Strategist.
