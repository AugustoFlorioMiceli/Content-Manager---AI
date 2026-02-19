import logging

from langgraph.graph import END, StateGraph

from agents.compiler import run_compiler
from agents.extractor import run_extractor
from agents.indexer import run_indexer
from agents.strategist import run_strategist
from agents.writer import run_writer
from graph.state import PipelineState
from models.strategy import CalendarConfig, CompilerResult

logger = logging.getLogger(__name__)


def extract(state: PipelineState) -> dict:
    logger.info("Step 1/5: Extracting content from %s", state["url"])
    try:
        extraction = run_extractor(state["url"])
        return {"extraction": extraction, "current_step": "extract"}
    except Exception as e:
        logger.error("Extraction failed: %s", e)
        return {"error": f"Extraction failed: {e}", "current_step": "extract"}


def index(state: PipelineState) -> dict:
    if state.get("error"):
        return {}
    logger.info("Step 2/5: Indexing content into Qdrant")
    try:
        index_result = run_indexer(state["extraction"])
        return {"index_result": index_result, "current_step": "index"}
    except Exception as e:
        logger.error("Indexing failed: %s", e)
        return {"error": f"Indexing failed: {e}", "current_step": "index"}


def strategize(state: PipelineState) -> dict:
    if state.get("error"):
        return {}
    logger.info("Step 3/5: Generating content strategy")
    try:
        config = state.get("calendar_config")
        calendar = run_strategist(state["index_result"], config)
        return {"calendar": calendar, "current_step": "strategize"}
    except Exception as e:
        logger.error("Strategy generation failed: %s", e)
        return {"error": f"Strategy generation failed: {e}", "current_step": "strategize"}


def write(state: PipelineState) -> dict:
    if state.get("error"):
        return {}
    logger.info("Step 4/5: Writing scripts")
    try:
        collection_name = state["index_result"].collection_name
        template = state.get("template")
        writer_result = run_writer(state["calendar"], collection_name, template)
        return {"writer_result": writer_result, "current_step": "write"}
    except Exception as e:
        logger.error("Script writing failed: %s", e)
        return {"error": f"Script writing failed: {e}", "current_step": "write"}


def compile(state: PipelineState) -> dict:
    if state.get("error"):
        return {}
    logger.info("Step 5/5: Compiling final document")
    try:
        output_dir = state.get("output_dir", "output")
        formats = state.get("output_formats", ["markdown", "pdf"])
        compiler_result = run_compiler(state["writer_result"], output_dir, formats)
        return {"compiler_result": compiler_result, "current_step": "compile"}
    except Exception as e:
        logger.error("Compilation failed: %s", e)
        return {"error": f"Compilation failed: {e}", "current_step": "compile"}


def should_continue(state: PipelineState) -> str:
    if state.get("error"):
        return END
    return "continue"


def build_workflow() -> StateGraph:
    workflow = StateGraph(PipelineState)

    workflow.add_node("extract", extract)
    workflow.add_node("index", index)
    workflow.add_node("strategize", strategize)
    workflow.add_node("write", write)
    workflow.add_node("compile", compile)

    workflow.set_entry_point("extract")

    workflow.add_conditional_edges("extract", should_continue, {"continue": "index", END: END})
    workflow.add_conditional_edges("index", should_continue, {"continue": "strategize", END: END})
    workflow.add_conditional_edges("strategize", should_continue, {"continue": "write", END: END})
    workflow.add_conditional_edges("write", should_continue, {"continue": "compile", END: END})
    workflow.add_edge("compile", END)

    return workflow


def run_pipeline(
    url: str,
    calendar_config: CalendarConfig | None = None,
    template: str | None = None,
    output_dir: str = "output",
    output_formats: list[str] | None = None,
) -> CompilerResult:
    if output_formats is None:
        output_formats = ["markdown", "pdf"]

    workflow = build_workflow()
    app = workflow.compile()

    initial_state: PipelineState = {
        "url": url,
        "calendar_config": calendar_config,
        "template": template,
        "output_dir": output_dir,
        "output_formats": output_formats,
        "extraction": None,
        "index_result": None,
        "calendar": None,
        "writer_result": None,
        "compiler_result": None,
        "current_step": "",
        "error": None,
    }

    logger.info("Starting ContentBrain pipeline for %s", url)
    final_state = app.invoke(initial_state)

    if final_state.get("error"):
        raise RuntimeError(
            f"Pipeline failed at step '{final_state.get('current_step')}': {final_state['error']}"
        )

    return final_state["compiler_result"]
