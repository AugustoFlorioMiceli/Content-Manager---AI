import logging
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from agents.compiler import run_compiler
from agents.extractor import run_extractor
from agents.indexer import run_indexer
from agents.strategist import run_strategist
from agents.writer import run_writer
from config import CHECKPOINT_DB_PATH
from graph.state import PipelineState

logger = logging.getLogger(__name__)


# --- Node functions: exceptions propagate for proper checkpoint behavior ---


def extract(state: PipelineState) -> dict:
    logger.info("Step 1/5: Extracting content from %s", state["url"])
    extraction = run_extractor(state["url"])
    return {"extraction": extraction, "current_step": "extract"}


def index(state: PipelineState) -> dict:
    logger.info("Step 2/5: Indexing content into Qdrant")
    index_result = run_indexer(state["extraction"])
    return {"index_result": index_result, "current_step": "index"}


def strategize(state: PipelineState) -> dict:
    logger.info("Step 3/5: Generating content strategy")
    config = state.get("calendar_config")
    user_context = state.get("template")
    platforms = state.get("platforms") or [state["index_result"].platform]

    calendars = []
    for platform in platforms:
        calendar = run_strategist(state["index_result"], config, user_context, platform)
        calendars.append(calendar)

    return {"calendars": calendars, "current_step": "strategize"}


def write(state: PipelineState) -> dict:
    logger.info("Step 4/5: Writing scripts")
    collection_name = state["index_result"].collection_name
    template = state.get("template")

    writer_results = []
    for calendar in state["calendars"]:
        writer_result = run_writer(calendar, collection_name, template)
        writer_results.append(writer_result)

    return {"writer_results": writer_results, "current_step": "write"}


def compile_node(state: PipelineState) -> dict:
    logger.info("Step 5/5: Compiling final document")
    output_dir = state.get("output_dir", "output")
    formats = state.get("output_formats", ["markdown", "pdf"])

    compiler_results = []
    for writer_result in state["writer_results"]:
        compiler_result = run_compiler(writer_result, output_dir, formats)
        compiler_results.append(compiler_result)

    return {"compiler_results": compiler_results, "current_step": "compile"}


def build_workflow() -> StateGraph:
    workflow = StateGraph(PipelineState)

    workflow.add_node("extract", extract)
    workflow.add_node("index", index)
    workflow.add_node("strategize", strategize)
    workflow.add_node("write", write)
    workflow.add_node("compile", compile_node)

    workflow.set_entry_point("extract")

    workflow.add_edge("extract", "index")
    workflow.add_edge("index", "strategize")
    workflow.add_edge("strategize", "write")
    workflow.add_edge("write", "compile")
    workflow.add_edge("compile", END)

    return workflow


def get_checkpointer() -> SqliteSaver:
    db_path = Path(CHECKPOINT_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def compile_app():
    workflow = build_workflow()
    checkpointer = get_checkpointer()
    return workflow.compile(checkpointer=checkpointer)
