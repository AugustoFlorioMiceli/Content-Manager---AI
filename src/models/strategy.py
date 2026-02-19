from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class _RevalidatingModel(BaseModel):
    """Base model that accepts instances reconstructed by serializers."""
    model_config = ConfigDict(revalidate_instances="always")


class CalendarConfig(_RevalidatingModel):
    posts_per_week: int = 3
    period_weeks: int = 4
    start_date: date = Field(default_factory=date.today)

    @property
    def total_posts(self) -> int:
        return self.posts_per_week * self.period_weeks


class ContentBrief(_RevalidatingModel):
    day: int
    date: date
    pillar: str
    topic: str
    angle: str
    hook: str
    objective: str
    content_type: str
    reference_data: list[str] = []


class ContentCalendar(_RevalidatingModel):
    platform: str
    username: str
    config: CalendarConfig
    briefs: list[ContentBrief]
    strategy_summary: str
    pillar_distribution: dict[str, int]


class ScriptSection(_RevalidatingModel):
    title: str
    content: str
    notes: str = ""


class Script(_RevalidatingModel):
    brief: ContentBrief
    hook: str
    sections: list[ScriptSection]
    cta: str
    retention_tips: list[str] = []
    strategic_justification: str = ""


class WriterResult(_RevalidatingModel):
    platform: str
    username: str
    scripts: list[Script]
    calendar: ContentCalendar


class CompilerResult(_RevalidatingModel):
    markdown_path: str | None = None
    pdf_path: str | None = None
    platform: str
    username: str
    total_scripts: int
