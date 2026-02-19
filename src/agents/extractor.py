import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from config import DEFAULT_EXTRACTION_LIMIT
from models.content import ContentItem, ExtractionResult
from services.apify import scrape_instagram, scrape_tiktok
from services.youtube import get_channel_videos, get_video_metadata

logger = logging.getLogger(__name__)


def detect_platform(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    if any(domain in hostname for domain in ["youtube.com", "youtu.be"]):
        return "youtube"
    if "instagram.com" in hostname:
        return "instagram"
    if "tiktok.com" in hostname:
        return "tiktok"

    raise ValueError(f"Unsupported platform for URL: {url}")


def extract_username(url: str, platform: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if platform == "youtube":
        match = re.match(r"@?([\w.-]+)", path.split("/")[-1] if "/" in path else path)
        return match.group(0) if match else path

    if platform in ("instagram", "tiktok"):
        parts = path.split("/")
        username = parts[0] if parts else path
        return username.lstrip("@")

    return path


def _normalize_youtube_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if "youtu.be" in (parsed.hostname or ""):
        return url

    if path.startswith("@") or path.startswith("c/") or path.startswith("channel/"):
        if not path.endswith("/videos"):
            return f"{parsed.scheme}://{parsed.hostname}/{path}/videos"

    return url


def run_extractor(url: str, limit: int = DEFAULT_EXTRACTION_LIMIT) -> ExtractionResult:
    platform = detect_platform(url)
    username = extract_username(url, platform)

    logger.info("Extracting %s content for @%s (limit=%d)", platform, username, limit)

    if platform == "youtube":
        items = _extract_youtube(url, limit)
    elif platform == "instagram":
        items = _extract_instagram(username, limit)
    elif platform == "tiktok":
        items = _extract_tiktok(username, limit)
    else:
        raise ValueError(f"Unsupported platform: {platform}")

    return ExtractionResult(
        source_url=url,
        platform=platform,
        username=username,
        items=items,
        extracted_at=datetime.now(timezone.utc),
    )


def _extract_youtube(url: str, limit: int) -> list[ContentItem]:
    normalized_url = _normalize_youtube_url(url)
    video_list = get_channel_videos(normalized_url, limit)

    items = []
    for video in video_list:
        video_url = video.get("url", "")
        if not video_url:
            continue

        try:
            metadata = get_video_metadata(video_url)
        except Exception:
            logger.warning("Failed to get metadata for %s", video_url)
            continue

        published_at = metadata.get("published_at") or datetime.now(timezone.utc)

        items.append(ContentItem(
            platform="youtube",
            title=metadata.get("title", video.get("title", "")),
            description=metadata.get("description", ""),
            transcript=metadata.get("transcript"),
            url=metadata.get("url", video_url),
            views=metadata.get("views"),
            likes=metadata.get("likes"),
            comments=metadata.get("comments"),
            duration=metadata.get("duration"),
            published_at=published_at,
            content_type="video",
        ))

    return items


def _extract_instagram(username: str, limit: int) -> list[ContentItem]:
    raw_items = scrape_instagram(username, limit)

    items = []
    for raw in raw_items:
        published_at = raw.get("published_at") or datetime.now(timezone.utc)

        items.append(ContentItem(
            platform="instagram",
            description=raw.get("description", ""),
            url=raw.get("url", ""),
            views=raw.get("views"),
            likes=raw.get("likes"),
            comments=raw.get("comments"),
            hashtags=raw.get("hashtags", []),
            published_at=published_at,
            content_type=raw.get("content_type", "image"),
        ))

    return items


def _extract_tiktok(username: str, limit: int) -> list[ContentItem]:
    raw_items = scrape_tiktok(username, limit)

    items = []
    for raw in raw_items:
        published_at = raw.get("published_at") or datetime.now(timezone.utc)

        items.append(ContentItem(
            platform="tiktok",
            description=raw.get("description", ""),
            url=raw.get("url", ""),
            views=raw.get("views"),
            likes=raw.get("likes"),
            comments=raw.get("comments"),
            shares=raw.get("shares"),
            hashtags=raw.get("hashtags", []),
            published_at=published_at,
            content_type="video",
            duration=raw.get("duration"),
        ))

    return items
