import logging

from qdrant_client import QdrantClient, models

from config import EMBEDDING_DIMENSIONS, QDRANT_API_KEY, QDRANT_URL

logger = logging.getLogger(__name__)

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        if not QDRANT_URL:
            raise ValueError("QDRANT_URL is not set. Add it to your .env file.")
        _client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
    return _client


def ensure_collection(collection_name: str, vector_size: int = EMBEDDING_DIMENSIONS) -> None:
    client = get_client()

    collections = [c.name for c in client.get_collections().collections]
    if collection_name in collections:
        logger.info("Collection '%s' already exists", collection_name)
        return

    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=vector_size,
            distance=models.Distance.COSINE,
        ),
    )
    logger.info("Created collection '%s'", collection_name)


def upsert_chunks(
    collection_name: str,
    chunks: list[dict],
    embeddings: list[list[float]],
) -> None:
    client = get_client()

    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        points.append(models.PointStruct(
            id=i,
            vector=embedding,
            payload=chunk,
        ))

    batch_size = 100
    for start in range(0, len(points), batch_size):
        batch = points[start : start + batch_size]
        client.upsert(collection_name=collection_name, points=batch)

    logger.info("Upserted %d chunks into '%s'", len(points), collection_name)


def ensure_viral_frameworks_collection() -> None:
    ensure_collection("viral_frameworks")
    client = get_client()
    for field in ("metadata.objetivo", "metadata.plataforma", "metadata.tono_predominante"):
        client.create_payload_index(
            collection_name="viral_frameworks",
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    logger.info("Payload indexes ensured on viral_frameworks collection")


def upsert_viral_framework(framework: dict, embedding: list[float], point_id: str) -> None:
    client = get_client()
    point = models.PointStruct(id=point_id, vector=embedding, payload=framework)
    client.upsert(collection_name="viral_frameworks", points=[point])
    logger.info("Upserted viral framework '%s'", point_id)


def search_viral_frameworks(
    query_embedding: list[float],
    objetivo: str,
    plataforma: str,
    tono: str | None = None,
    limit: int = 2,
) -> list[dict]:
    """Query viral_frameworks filtered by objetivo + plataforma (+ optional tono).
    Falls back to objetivo+plataforma only if the tone filter returns no results.
    Returns [] gracefully if the collection doesn't exist yet.
    """
    client = get_client()

    base_conditions = [
        models.FieldCondition(key="metadata.objetivo", match=models.MatchValue(value=objetivo)),
        models.FieldCondition(key="metadata.plataforma", match=models.MatchValue(value=plataforma)),
    ]

    def _run(conditions: list) -> list[dict]:
        results = client.query_points(
            collection_name="viral_frameworks",
            query=query_embedding,
            query_filter=models.Filter(must=conditions),
            limit=limit,
        )
        return [{"score": p.score, **p.payload} for p in results.points]

    try:
        if tono:
            results = _run(base_conditions + [
                models.FieldCondition(
                    key="metadata.tono_predominante",
                    match=models.MatchValue(value=tono),
                )
            ])
            if results:
                return results
        return _run(base_conditions)
    except Exception as exc:
        logger.warning("viral_frameworks search failed (%s), skipping", exc)
        return []


def search(
    collection_name: str,
    query_embedding: list[float],
    limit: int = 10,
) -> list[dict]:
    client = get_client()

    results = client.query_points(
        collection_name=collection_name,
        query=query_embedding,
        limit=limit,
    )

    return [
        {"score": point.score, **point.payload}
        for point in results.points
    ]
