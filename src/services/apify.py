import logging
from datetime import datetime, timezone

from apify_client import ApifyClient

from config import APIFY_API_TOKEN

logger = logging.getLogger(__name__)

INSTAGRAM_ACTOR = "apify/instagram-post-scraper"
TIKTOK_ACTOR = "clockworks/tiktok-scraper"


def _get_client() -> ApifyClient:
    if not APIFY_API_TOKEN:
        raise ValueError("APIFY_API_TOKEN is not set. Add it to your .env file.")
    return ApifyClient(APIFY_API_TOKEN)


def scrape_instagram(username: str, limit: int) -> list[dict]:
    client = _get_client()

    run_input = {
        "username": [username],
        "resultsLimit": limit,
    }

    logger.info("Running Instagram scraper for @%s (limit=%d)", username, limit)
    run = client.actor(INSTAGRAM_ACTOR).call(run_input=run_input)

    items = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        published_at = None
        if item.get("timestamp"):
            try:
                published_at = datetime.fromisoformat(item["timestamp"])
            except (ValueError, TypeError):
                pass

        post_type = item.get("type", "image")
        if post_type == "Sidecar":
            post_type = "carousel"
        elif post_type == "Video":
            post_type = "reel"
        else:
            post_type = "image"

        items.append({
            "description": item.get("caption", ""),
            "url": item.get("url", ""),
            "views": item.get("videoPlayCount"),
            "likes": item.get("likesCount"),
            "comments": item.get("commentsCount"),
            "hashtags": item.get("hashtags", []),
            "published_at": published_at,
            "content_type": post_type,
        })

    return items


def scrape_tiktok(username: str, limit: int) -> list[dict]:
    client = _get_client()

    run_input = {
        "profiles": [username],
        "resultsPerPage": limit,
        "excludePinnedPosts": False,
        "shouldDownloadCovers": False,
    }

    logger.info("Running TikTok scraper for @%s (limit=%d)", username, limit)
    run = client.actor(TIKTOK_ACTOR).call(run_input=run_input)

    items = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        published_at = None
        create_time = item.get("createTime")
        if create_time:
            try:
                published_at = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass

        hashtags = []
        for tag in item.get("hashtags", []):
            if isinstance(tag, dict):
                hashtags.append(tag.get("name", ""))
            else:
                hashtags.append(str(tag))

        items.append({
            "description": item.get("text", "") or item.get("description", ""),
            "url": item.get("webVideoUrl", ""),
            "views": item.get("playCount"),
            "likes": item.get("diggCount"),
            "comments": item.get("commentCount"),
            "shares": item.get("shareCount"),
            "hashtags": [h for h in hashtags if h],
            "published_at": published_at,
            "content_type": "video",
            "duration": item.get("videoMeta", {}).get("duration"),
        })

    return items
