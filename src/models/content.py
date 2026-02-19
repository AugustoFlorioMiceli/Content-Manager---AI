from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _RevalidatingModel(BaseModel):
    """Base model that accepts instances reconstructed by serializers."""
    model_config = ConfigDict(revalidate_instances="always")


class ContentItem(_RevalidatingModel):
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


class ExtractionResult(_RevalidatingModel):
    source_url: str
    platform: str
    username: str
    items: list[ContentItem]
    extracted_at: datetime


class IndexResult(_RevalidatingModel):
    collection_name: str
    chunks_indexed: int
    platform: str
    username: str
