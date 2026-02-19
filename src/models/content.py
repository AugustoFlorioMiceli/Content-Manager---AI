from datetime import datetime

from pydantic import BaseModel


class ContentItem(BaseModel):
    platform: str
    title: str | None = None
    description: str
    transcript: str | None = None
    url: str
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    hashtags: list[str] = []
    published_at: datetime
    content_type: str
    duration: int | None = None


class ExtractionResult(BaseModel):
    source_url: str
    platform: str
    username: str
    items: list[ContentItem]
    extracted_at: datetime


class IndexResult(BaseModel):
    collection_name: str
    chunks_indexed: int
    platform: str
    username: str
