import logging
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from agents.compiler import run_compiler
from agents.critic import run_critic
from agents.extractor import run_extractor
from agents.indexer import run_indexer
from agents.strategist import run_strategist
from agents.writer import rewrite_script, run_writer
from config import CHECKPOINT_DB_PATH
from graph.state import PipelineState
from models.strategy import WriterResult

logger = logging.getLogger(__name__)

MAX_CRITIC_ROUNDS = 2


# --- Node functions ---


def extract(state: PipelineState) -> dict:
    from datetime import datetime, timezone
    from models.content import ExtractionResult

    urls = state["urls"]
    logger.info("Step 1/6: Extracting content from %d URL(s)", len(urls))

    all_items = []
    first_result = None
    for url in urls:
        result = run_extractor(url)
        all_items.extend(result.items)
        if first_result is None:
            first_result = result

    combined = ExtractionResult(
        source_url=urls[0],
        platform=first_result.platform,
        username=first_result.username,
        items=all_items,
        extracted_at=datetime.now(timezone.utc),
    )

    return {"extraction": combined, "current_step": "extract"}


def index(state: PipelineState) -> dict:
    logger.info("Step 2/6: Indexing content into Qdrant")
    index_result = run_indexer(state["extraction"])
    return {"index_result": index_result, "current_step": "index"}


def strategize(state: PipelineState) -> dict:
    logger.info("Step 3/6: Generating content strategy")
    config = state.get("calendar_config")
    user_context = state.get("template")
    platforms = state.get("platforms") or [state["index_result"].platform]

    calendars = []
    for platform in platforms:
        calendar = run_strategist(state["index_result"], config, user_context, platform)
        calendars.append(calendar)

    return {"calendars": calendars, "current_step": "strategize"}


def write(state: PipelineState) -> dict:
    logger.info("Step 4/6: Writing scripts")
    collection_name = state["index_result"].collection_name
    template = state.get("template")

    writer_results = []
    for calendar in state["calendars"]:
        writer_result = run_writer(calendar, collection_name, template)
        writer_results.append(writer_result)

    return {
        "writer_results": writer_results,
        "current_step": "write",
        "critic_rounds": 0,
    }


def critic(state: PipelineState) -> dict:
    rounds = state.get("critic_rounds", 0)
    logger.info("Step 5/6: Critic review (round %d)", rounds + 1)
    template = state.get("template")

    result = run_critic(state["writer_results"], template)

    return {
        "critic_approved": result["approved"],
        "critic_feedback": result["feedback"],
        "critic_rounds": rounds + 1,
        "current_step": "critic",
    }


def rewrite(state: PipelineState) -> dict:
    """Rewrite rejected scripts using critic feedback."""
    logger.info("Step 5/6: Rewriting scripts based on critic feedback")
    collection_name = state["index_result"].collection_name
    template = state.get("template")
    feedback = state.get("critic_feedback", {})

    new_writer_results = []
    for wr in state["writer_results"]:
        platform = wr.platform
        new_scripts = []

        for i, script in enumerate(wr.scripts):
            script_key = f"{platform}_{i}"
            script_feedback = feedback.get(script_key)

            if script_feedback:
                logger.info(
                    "Rewriting %s script %d: %s (%d issues)",
                    platform, i, script.brief.topic, len(script_feedback),
                )
                new_script = rewrite_script(
                    script, script_feedback, collection_name, platform, template,
                )
                new_scripts.append(new_script)
            else:
                new_scripts.append(script)

        new_writer_results.append(WriterResult(
            platform=wr.platform,
            username=wr.username,
            scripts=new_scripts,
            calendar=wr.calendar,
        ))

    return {
        "writer_results": new_writer_results,
        "current_step": "rewrite",
    }


def after_critic(state: PipelineState) -> str:
    """Route after critic: compile if approved or max rounds, rewrite otherwise."""
    if state.get("critic_approved", False):
        logger.info("Critic approved all scripts")
        return "compile"

    rounds = state.get("critic_rounds", 0)
    if rounds >= MAX_CRITIC_ROUNDS:
        logger.warning(
            "Max critic rounds (%d) reached, proceeding to compile",
            MAX_CRITIC_ROUNDS,
        )
        return "compile"

    logger.info("Critic rejected scripts, sending back for rewrite")
    return "rewrite"


def compile_node(state: PipelineState) -> dict:
    logger.info("Step 6/6: Compiling final document")
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
    workflow.add_node("critic", critic)
    workflow.add_node("rewrite", rewrite)
    workflow.add_node("compile", compile_node)

    workflow.set_entry_point("extract")

    workflow.add_edge("extract", "index")
    workflow.add_edge("index", "strategize")
    workflow.add_edge("strategize", "write")
    workflow.add_edge("write", "critic")

    # Critic decides: approved -> compile, rejected -> rewrite
    workflow.add_conditional_edges(
        "critic",
        after_critic,
        {"compile": "compile", "rewrite": "rewrite"},
    )

    # After rewrite, go back to critic for re-evaluation
    workflow.add_edge("rewrite", "critic")

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
