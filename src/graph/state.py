from typing import TypedDict

from src.models.content import ExtractionResult, IndexResult
from src.models.strategy import (
    CalendarConfig,
    CompilerResult,
    ContentCalendar,
    WriterResult,
)


class PipelineState(TypedDict, total=False):
    # User inputs
    url: str
    calendar_config: CalendarConfig | None
    template: str | None
    output_dir: str
    output_formats: list[str]
    # Intermediate state
    extraction: ExtractionResult | None
    index_result: IndexResult | None
    calendar: ContentCalendar | None
    writer_result: WriterResult | None
    compiler_result: CompilerResult | None
    # Control
    current_step: str
    error: str | None
