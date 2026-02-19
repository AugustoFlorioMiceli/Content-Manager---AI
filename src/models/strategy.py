from datetime import date

from pydantic import BaseModel, Field


class CalendarConfig(BaseModel):
    posts_per_week: int = 3
    period_weeks: int = 4
    start_date: date = Field(default_factory=date.today)

    @property
    def total_posts(self) -> int:
        return self.posts_per_week * self.period_weeks


class ContentBrief(BaseModel):
    day: int
    date: date
    pillar: str
    topic: str
    angle: str
    hook: str
    objective: str
    content_type: str
    reference_data: list[str] = []


class ContentCalendar(BaseModel):
    platform: str
    username: str
    config: CalendarConfig
    briefs: list[ContentBrief]
    strategy_summary: str
    pillar_distribution: dict[str, int]


class ScriptSection(BaseModel):
    title: str
    content: str
    notes: str = ""


class Script(BaseModel):
    brief: ContentBrief
    hook: str
    sections: list[ScriptSection]
    cta: str
    retention_tips: list[str] = []
    strategic_justification: str = ""


class WriterResult(BaseModel):
    platform: str
    username: str
    scripts: list[Script]
    calendar: ContentCalendar


class CompilerResult(BaseModel):
    markdown_path: str | None = None
    pdf_path: str | None = None
    platform: str
    username: str
    total_scripts: int
