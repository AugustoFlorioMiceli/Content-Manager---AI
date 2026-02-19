import logging
from datetime import datetime

import yt_dlp

logger = logging.getLogger(__name__)


def get_channel_videos(channel_url: str, limit: int) -> list[dict]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": limit,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    if not info:
        return []

    entries = info.get("entries", [])
    if not entries:
        return []

    videos = []
    for entry in entries[:limit]:
        if entry is None:
            continue
        videos.append({
            "id": entry.get("id"),
            "title": entry.get("title"),
            "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}",
        })

    return videos


def get_video_metadata(video_url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["es", "en"],
        "subtitlesformat": "json3",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)

    if not info:
        return {}

    transcript = _extract_transcript(info)

    upload_date = info.get("upload_date", "")
    published_at = None
    if upload_date:
        try:
            published_at = datetime.strptime(upload_date, "%Y%m%d")
        except ValueError:
            pass

    return {
        "title": info.get("title", ""),
        "description": info.get("description", ""),
        "transcript": transcript,
        "url": info.get("webpage_url", video_url),
        "views": info.get("view_count"),
        "likes": info.get("like_count"),
        "comments": info.get("comment_count"),
        "duration": info.get("duration"),
        "published_at": published_at,
        "channel": info.get("channel", ""),
        "channel_id": info.get("channel_id", ""),
    }


def _extract_transcript(info: dict) -> str | None:
    subtitles = info.get("subtitles", {})
    automatic_captions = info.get("automatic_captions", {})

    for lang in ["es", "en"]:
        for source in [subtitles, automatic_captions]:
            tracks = source.get(lang, [])
            for track in tracks:
                if track.get("ext") == "json3":
                    return _download_subtitle_text(track["url"])

    for source in [subtitles, automatic_captions]:
        if source:
            first_lang = next(iter(source))
            tracks = source[first_lang]
            for track in tracks:
                if track.get("ext") == "json3":
                    return _download_subtitle_text(track["url"])

    return None


def _download_subtitle_text(subtitle_url: str) -> str | None:
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(subtitle_url) as response:
            data = json.loads(response.read().decode())

        segments = []
        for event in data.get("events", []):
            segs = event.get("segs", [])
            text = "".join(seg.get("utf8", "") for seg in segs).strip()
            if text and text != "\n":
                segments.append(text)

        return " ".join(segments) if segments else None
    except Exception:
        logger.warning("Failed to download subtitle from %s", subtitle_url)
        return None
