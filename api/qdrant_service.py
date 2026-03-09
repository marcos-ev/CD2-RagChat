"""
Serviço de integração com Qdrant (REST API).
"""

import os
from typing import Any, Dict, List

import httpx


class QdrantService:
    def __init__(self):
        self.host = os.getenv("QDRANT_HOST", "qdrant")
        self.port = int(os.getenv("QDRANT_PORT", "6333"))
        self.collection = os.getenv("QDRANT_COLLECTION", "documents")
        self.dimension = int(os.getenv("EMBEDDING_DIM_FALLBACK", "768"))
        self.url = f"http://{self.host}:{self.port}"
        self.timeout = float(os.getenv("QDRANT_TIMEOUT_SECONDS", "30"))
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def ensure_collection(self) -> None:
        resp = await self._client.get(f"{self.url}/collections/{self.collection}")
        if resp.status_code == 200:
            return
        payload = {
            "vectors": {
                "size": self.dimension,
                "distance": "Cosine",
            }
        }
        create = await self._client.put(f"{self.url}/collections/{self.collection}", json=payload)
        create.raise_for_status()

    async def upsert_points(self, points: List[Dict[str, Any]]) -> None:
        if not points:
            return
        payload = {"points": points}
        resp = await self._client.put(
            f"{self.url}/collections/{self.collection}/points",
            json=payload,
        )
        resp.raise_for_status()

    async def search(self, query_vector: List[float], limit: int = 5, score_threshold: float = 0.0) -> List[Dict[str, Any]]:
        payload = {
            "vector": query_vector,
            "limit": limit,
            "with_payload": True,
            "score_threshold": score_threshold,
        }
        resp = await self._client.post(
            f"{self.url}/collections/{self.collection}/points/search",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", [])

    async def delete_points(self, point_ids: List[int]) -> None:
        if not point_ids:
            return
        payload = {"points": point_ids}
        resp = await self._client.post(
            f"{self.url}/collections/{self.collection}/points/delete",
            json=payload,
        )
        resp.raise_for_status()

