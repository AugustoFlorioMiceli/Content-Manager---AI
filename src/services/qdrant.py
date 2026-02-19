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
