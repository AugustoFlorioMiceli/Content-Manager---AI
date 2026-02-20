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
    url: str
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
    # Control
    current_step: str
    error: str | None
