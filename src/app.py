from datetime import date
from pathlib import Path

import streamlit as st

from agents.compiler import run_compiler
from agents.extractor import run_extractor
from agents.indexer import run_indexer
from agents.strategist import run_strategist
from agents.writer import run_writer
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

# --- Plantilla opcional ---
with st.expander("Plantilla de guion (opcional)"):
    template_file = st.file_uploader(
        "Sube tu plantilla de guion (.txt o .md)",
        type=["txt", "md"],
        help="Si tienes una estructura de guion que ya te funciona, subela "
        "y el sistema la usara como base para los nuevos guiones.",
    )

template_text = None
if template_file is not None:
    template_text = template_file.read().decode("utf-8")
    st.success(f"Plantilla cargada: {template_file.name}")

# --- Formatos de salida ---
output_formats = st.multiselect(
    "Formatos de salida",
    options=["markdown", "pdf"],
    default=["markdown", "pdf"],
)

st.divider()

# --- Generar ---
if st.button("Generar Plan de Contenido", type="primary", use_container_width=True):
    if not url:
        st.error("Por favor, pega la URL de un perfil de YouTube, Instagram o TikTok.")
    elif not output_formats:
        st.error("Selecciona al menos un formato de salida.")
    else:
        config = CalendarConfig(
            posts_per_week=posts_per_week,
            period_weeks=period_weeks,
            start_date=date.today(),
        )

        with st.status("Generando plan de contenido...", expanded=True) as status:
            try:
                # Step 1: Extract
                st.write("Extrayendo contenido del perfil...")
                extraction = run_extractor(url)
                st.write(f"Extraidos {len(extraction.items)} items de @{extraction.username}")

                # Step 2: Index
                st.write("Indexando contenido en base de datos vectorial...")
                index_result = run_indexer(extraction)
                st.write(f"Indexados {index_result.chunks_indexed} chunks")

                # Step 3: Strategize
                st.write("Generando estrategia de contenido...")
                calendar = run_strategist(index_result, config)
                st.write(f"Calendario generado: {len(calendar.briefs)} piezas")

                # Step 4: Write
                st.write("Escribiendo guiones...")
                writer_result = run_writer(calendar, index_result.collection_name, template_text)
                st.write(f"Redactados {len(writer_result.scripts)} guiones")

                # Step 5: Compile
                st.write("Compilando documento final...")
                compiler_result = run_compiler(writer_result, "output", output_formats)

                status.update(label="Plan generado exitosamente", state="complete")

            except Exception as e:
                status.update(label="Error en el pipeline", state="error")
                st.error(f"Error: {e}")
                st.stop()

        # --- Resultados ---
        st.divider()
        st.subheader("Documentos listos")

        col_dl1, col_dl2 = st.columns(2)

        if compiler_result.markdown_path:
            md_path = Path(compiler_result.markdown_path)
            if md_path.exists():
                with col_dl1:
                    st.download_button(
                        label="Descargar Markdown",
                        data=md_path.read_text(encoding="utf-8"),
                        file_name=md_path.name,
                        mime="text/markdown",
                        use_container_width=True,
                    )

        if compiler_result.pdf_path:
            pdf_path = Path(compiler_result.pdf_path)
            if pdf_path.exists():
                with col_dl2:
                    st.download_button(
                        label="Descargar PDF",
                        data=pdf_path.read_bytes(),
                        file_name=pdf_path.name,
                        mime="application/pdf",
                        use_container_width=True,
                    )

        # Preview del markdown
        if compiler_result.markdown_path:
            md_path = Path(compiler_result.markdown_path)
            if md_path.exists():
                with st.expander("Vista previa del plan", expanded=True):
                    st.markdown(md_path.read_text(encoding="utf-8"))
