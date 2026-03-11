from typing import TypedDict

from models.content import ExtractionResult, IndexResult
from models.strategy import (
    CalendarConfig,
    CompilerResult,
    ContentCalendar,
    WriterResult,
)


class PipelineState(TypedDict, total=False):
    # User inputs
    input_mode: str  # "own_account" | "niche_description"
    urls: list[str]
    niche_description: str | None
    brand_name: str | None
    platforms: list[str]
    calendar_config: CalendarConfig | None
    template: str | None
    output_dir: str
    output_formats: list[str]
    # Intermediate state
    extraction: ExtractionResult | None
    index_result: IndexResult | None
    calendars: list[ContentCalendar]
    writer_results: list[WriterResult]
    compiler_results: list[CompilerResult]
    # Critic
    critic_approved: bool
    critic_feedback: dict
    critic_rounds: int
    # Control
    current_step: str
    error: str | None
