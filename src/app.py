import hashlib
import time
from datetime import date
from pathlib import Path

import streamlit as st

from graph.workflow import compile_app
from models.strategy import CalendarConfig

st.set_page_config(
    page_title="ContentBrain",
    page_icon="🧠",
    layout="centered",
)

st.title("ContentBrain")
st.caption(
    "Transforma un perfil de referencia en un calendario editorial "
    "de alto rendimiento, listo para ejecutar."
)

st.divider()

# --- Input principal ---
url = st.text_input(
    "URL del perfil de referencia",
    placeholder="https://www.youtube.com/@canal / instagram.com/cuenta / tiktok.com/@usuario",
)

# --- Plataforma de destino ---
platform_choice = st.radio(
    "Plataforma de destino",
    options=["YouTube", "Instagram", "Ambas"],
    horizontal=True,
    help="Plataforma para la que se generará el calendario editorial. "
    "Si elegís 'Ambas', se generan dos archivos separados.",
)

if platform_choice == "YouTube":
    platforms = ["youtube"]
elif platform_choice == "Instagram":
    platforms = ["instagram"]
else:
    platforms = ["youtube", "instagram"]

# --- Configuracion ---
with st.expander("Configuracion del calendario", expanded=True):
    col1, col2 = st.columns(2)

    with col1:
        posts_per_week = st.slider(
            "Publicaciones por semana",
            min_value=1,
            max_value=7,
            value=3,
        )

    with col2:
        period_weeks = st.slider(
            "Duracion (semanas)",
            min_value=1,
            max_value=8,
            value=4,
        )

    total_posts = posts_per_week * period_weeks
    st.metric("Total de piezas de contenido", total_posts)
    st.info(
        "A mayor volumen de contenido generado y subido, mas eficiente sera "
        "la estrategia. La cantidad de piezas depende del tiempo disponible "
        "para produccion.",
        icon="💡",
    )

# --- Contexto del usuario ---
with st.expander("Ejemplos y contexto de marca (opcional)"):
    template_files = st.file_uploader(
        "Sube ejemplos de guiones, imagen de marca o datos relevantes (.txt, .md o .pdf)",
        type=["txt", "md", "pdf"],
        accept_multiple_files=True,
        help="Podes subir guiones de ejemplo, lineamientos de marca, "
        "tono de voz, o cualquier informacion que ayude a personalizar "
        "la estrategia y los guiones.",
    )

template_text = None
if template_files:
    from pypdf import PdfReader
    parts = []
    for f in template_files:
        if f.name.endswith(".pdf"):
            reader = PdfReader(f)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            text = f.read().decode("utf-8")
        parts.append(f"--- {f.name} ---\n{text}")
    template_text = "\n\n".join(parts)
    st.success(f"{len(template_files)} archivo(s) cargado(s): {', '.join(f.name for f in template_files)}")

# --- Formatos de salida ---
output_formats = st.multiselect(
    "Formatos de salida",
    options=["markdown", "pdf"],
    default=["markdown", "pdf"],
)

st.divider()


# --- Helpers ---


@st.cache_resource
def get_app():
    return compile_app()


def generate_thread_id(url: str) -> str:
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{url_hash}_{int(time.time())}"


def check_resumable(app, url: str):
    prev_thread = st.session_state.get("last_thread_id")
    prev_url = st.session_state.get("last_url")

    if prev_thread and prev_url == url:
        config = {"configurable": {"thread_id": prev_thread}}
        try:
            state = app.get_state(config)
            if state.next:
                return prev_thread, state.values
        except Exception:
            pass
    return None, None


NODE_PROGRESS = {
    "extract": "Extrayendo contenido del perfil...",
    "index": "Indexando contenido en base de datos vectorial...",
    "strategize": "Generando estrategia de contenido...",
    "write": "Escribiendo guiones...",
    "compile": "Compilando documento final...",
}


# --- Generar ---
if st.button("Generar Plan de Contenido", type="primary", use_container_width=True):
    if not url:
        st.error("Por favor, pega la URL de un perfil de YouTube, Instagram o TikTok.")
    elif not output_formats:
        st.error("Selecciona al menos un formato de salida.")
    else:
        # Clear previous results before a new generation
        st.session_state.pop("compiler_results", None)
        config = CalendarConfig(
            posts_per_week=posts_per_week,
            period_weeks=period_weeks,
            start_date=date.today(),
        )

        app = get_app()

        # Check for resumable state
        resume_thread, resume_state = check_resumable(app, url)

        if resume_thread:
            thread_id = resume_thread
            input_data = None
            completed_step = resume_state.get("current_step", "")
            st.info(f"Reanudando desde el ultimo paso exitoso ({completed_step})")
        else:
            thread_id = generate_thread_id(url)
            input_data = {
                "url": url,
                "platforms": platforms,
                "calendar_config": config,
                "template": template_text,
                "output_dir": "output",
                "output_formats": output_formats,
            }

        run_config = {"configurable": {"thread_id": thread_id}}

        # Save for resume on next run
        st.session_state["last_thread_id"] = thread_id
        st.session_state["last_url"] = url

        with st.status("Generando plan de contenido...", expanded=True) as status:
            try:
                for event in app.stream(
                    input_data, run_config, stream_mode="updates"
                ):
                    for node_name, node_output in event.items():
                        if node_name == "extract" and node_output.get("extraction"):
                            ext = node_output["extraction"]
                            st.write(f"Extraidos {len(ext.items)} items de @{ext.username}")
                        elif node_name == "index" and node_output.get("index_result"):
                            idx = node_output["index_result"]
                            st.write(f"Indexados {idx.chunks_indexed} chunks")
                        elif node_name == "strategize" and node_output.get("calendars"):
                            cals = node_output["calendars"]
                            total_briefs = sum(len(c.briefs) for c in cals)
                            platforms_str = " + ".join(c.platform.capitalize() for c in cals)
                            st.write(f"Calendario(s) generado(s): {total_briefs} piezas ({platforms_str})")
                        elif node_name == "write" and node_output.get("writer_results"):
                            wrs = node_output["writer_results"]
                            total_scripts = sum(len(wr.scripts) for wr in wrs)
                            st.write(f"Redactados {total_scripts} guiones")
                        elif node_name == "compile":
                            st.write("Documento final compilado")

                # Get final state
                final_state = app.get_state(run_config)
                compiler_results = final_state.values.get("compiler_results", [])

                # Persist results in session state so download buttons survive re-runs
                st.session_state["compiler_results"] = [
                    {
                        "platform": cr.platform,
                        "markdown_path": cr.markdown_path,
                        "pdf_path": cr.pdf_path,
                    }
                    for cr in compiler_results
                ]

                # Clear resume state on success
                st.session_state.pop("last_thread_id", None)
                st.session_state.pop("last_url", None)

                status.update(label="Plan generado exitosamente", state="complete")

            except Exception as e:
                status.update(label="Error en el pipeline", state="error")
                st.error(f"Error: {e}")
                st.info(
                    "El progreso se guardo automaticamente. "
                    "Haz clic en 'Generar' de nuevo para reanudar desde el ultimo paso exitoso."
                )
                st.stop()

# --- Resultados (fuera del bloque de generacion para sobrevivir re-runs) ---
saved_results = st.session_state.get("compiler_results", [])
if saved_results:
    st.divider()
    st.subheader("Documentos listos")

    for cr in saved_results:
        platform_label = cr["platform"].capitalize()
        if len(saved_results) > 1:
            st.markdown(f"**{platform_label}**")

        col_dl1, col_dl2 = st.columns(2)

        if cr["markdown_path"]:
            md_path = Path(cr["markdown_path"])
            if md_path.exists():
                with col_dl1:
                    st.download_button(
                        label=f"Descargar Markdown{' - ' + platform_label if len(saved_results) > 1 else ''}",
                        data=md_path.read_text(encoding="utf-8"),
                        file_name=md_path.name,
                        mime="text/markdown",
                        use_container_width=True,
                        key=f"md_{cr['platform']}",
                    )

        if cr["pdf_path"]:
            pdf_path = Path(cr["pdf_path"])
            if pdf_path.exists():
                with col_dl2:
                    st.download_button(
                        label=f"Descargar PDF{' - ' + platform_label if len(saved_results) > 1 else ''}",
                        data=pdf_path.read_bytes(),
                        file_name=pdf_path.name,
                        mime="application/pdf",
                        use_container_width=True,
                        key=f"pdf_{cr['platform']}",
                    )

    # Preview del markdown (primera plataforma)
    first = saved_results[0]
    if first["markdown_path"]:
        md_path = Path(first["markdown_path"])
        if md_path.exists():
            label = "Vista previa del plan"
            if len(saved_results) > 1:
                label += f" ({first['platform'].capitalize()})"
            with st.expander(label, expanded=True):
                st.markdown(md_path.read_text(encoding="utf-8"))
