import logging
import re

from src.config import CHUNK_SIZE
from src.models.content import ContentItem, ExtractionResult, IndexResult
from src.services.embeddings import generate_embeddings
from src.services.qdrant import ensure_collection, upsert_chunks

logger = logging.getLogger(__name__)


def _make_collection_name(platform: str, username: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", username)
    return f"{platform}_{clean}"


def _split_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def _item_metadata(item: ContentItem) -> dict:
    return {
        "platform": item.platform,
        "url": item.url,
        "published_at": item.published_at.isoformat(),
        "views": item.views,
        "likes": item.likes,
        "comments": item.comments,
        "content_type": item.content_type,
    }


def chunk_content(item: ContentItem) -> list[dict]:
    chunks = []
    metadata = _item_metadata(item)

    if item.platform == "youtube":
        # Chunk 1: title + description
        header = ""
        if item.title:
            header += item.title + "\n"
        if item.description:
            header += item.description
        if header.strip():
            chunks.append({"text": header.strip(), **metadata, "chunk_type": "metadata"})

        # Chunk 2+: transcript split into chunks
        if item.transcript:
            for part in _split_text(item.transcript):
                chunks.append({"text": part, **metadata, "chunk_type": "transcript"})
    else:
        # IG/TikTok: each post is a single chunk
        text = item.description
        if item.hashtags:
            text += "\n" + " ".join(f"#{h}" for h in item.hashtags)
        if text.strip():
            chunks.append({"text": text.strip(), **metadata, "chunk_type": "post"})

    return chunks


def run_indexer(extraction: ExtractionResult) -> IndexResult:
    collection_name = _make_collection_name(extraction.platform, extraction.username)

    logger.info(
        "Indexing %d items for @%s into collection '%s'",
        len(extraction.items),
        extraction.username,
        collection_name,
    )

    # Generate all chunks
    all_chunks = []
    for item in extraction.items:
        all_chunks.extend(chunk_content(item))

    if not all_chunks:
        logger.warning("No chunks generated for @%s", extraction.username)
        return IndexResult(
            collection_name=collection_name,
            chunks_indexed=0,
            platform=extraction.platform,
            username=extraction.username,
        )

    # Generate embeddings
    texts = [chunk["text"] for chunk in all_chunks]
    logger.info("Generating embeddings for %d chunks", len(texts))
    embeddings = generate_embeddings(texts)

    # Store in Qdrant
    ensure_collection(collection_name)
    upsert_chunks(collection_name, all_chunks, embeddings)

    return IndexResult(
        collection_name=collection_name,
        chunks_indexed=len(all_chunks),
        platform=extraction.platform,
        username=extraction.username,
    )
