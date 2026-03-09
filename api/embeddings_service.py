"""
Serviço de geração de embeddings via Google Gemini Embeddings API.
"""

import os
from typing import List

import numpy as np
from google import genai

DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_DIMENSION = 768


class EmbeddingsService:
    """Serviço para gerar embeddings de texto."""

    def __init__(self, model_name: str = None):
        self.model_name = model_name or os.getenv("EMBEDDINGS_MODEL", DEFAULT_MODEL)
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
        self.embedding_dimension = int(os.getenv("EMBEDDING_DIM_FALLBACK", str(DEFAULT_DIMENSION)))
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY não configurada")
        self.client = genai.Client(api_key=self.api_key)

    def _normalize(self, vector: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vector)
        if norm == 0:
            return vector
        return vector / norm

    def _embed_inputs(self, inputs: List[str]) -> np.ndarray:
        response = self.client.models.embed_content(
            model=self.model_name,
            contents=inputs,
            config={"output_dimensionality": self.embedding_dimension},
        )
        raw_embeddings = getattr(response, "embeddings", None)
        if not raw_embeddings and isinstance(response, dict):
            raw_embeddings = response.get("embeddings")
        if not raw_embeddings:
            raise ValueError("Resposta inválida da API de embeddings")

        vectors_data = []
        for item in raw_embeddings:
            values = getattr(item, "values", None)
            if values is None and isinstance(item, dict):
                values = item.get("values")
            if not values:
                continue
            vectors_data.append(values)
        if not vectors_data:
            raise ValueError("Resposta inválida da API de embeddings")

        vectors = np.array(vectors_data, dtype=float)
        if vectors.ndim == 1:
            vectors = np.expand_dims(vectors, axis=0)
        normalized = np.array([self._normalize(v) for v in vectors])
        return normalized

    def generate_embedding(self, text: str) -> np.ndarray:
        if not text or not text.strip():
            raise ValueError("Texto não pode ser vazio")
        vectors = self._embed_inputs([f"query: {text.strip()}"])
        return vectors[0]

    def generate_embeddings_batch(self, texts: list) -> np.ndarray:
        if not texts:
            return np.array([])
        prefixed = [f"passage: {t.strip()}" for t in texts if t and t.strip()]
        if not prefixed:
            return np.array([])
        return self._embed_inputs(prefixed)

    def get_embedding_dimension(self) -> int:
        return self.embedding_dimension

