"""
Serviço de geração de embeddings local via sentence-transformers.
Modelo: BAAI/bge-m3 (1024 dims, multilingual, busca densa)
"""

import os
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_DIMENSION = 1024


class EmbeddingsService:
    """Serviço para gerar embeddings de texto localmente."""

    def __init__(self, model_name: str = None):
        self.model_name = model_name or os.getenv("EMBEDDINGS_MODEL", DEFAULT_MODEL)
        self.embedding_dimension = int(os.getenv("EMBEDDING_DIM_FALLBACK", str(DEFAULT_DIMENSION)))
        print(f"Carregando modelo de embeddings: {self.model_name}")
        self.model = SentenceTransformer(self.model_name)
        print(f"Modelo carregado. Dimensão: {self.model.get_sentence_embedding_dimension()}")

    def generate_embedding(self, text: str) -> np.ndarray:
        if not text or not text.strip():
            raise ValueError("Texto não pode ser vazio")
        embedding = self.model.encode(text.strip(), normalize_embeddings=True)
        return np.array(embedding, dtype=float)

    def generate_embeddings_batch(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.array([])
        cleaned = [t.strip() for t in texts if t and t.strip()]
        if not cleaned:
            return np.array([])
        embeddings = self.model.encode(cleaned, normalize_embeddings=True, show_progress_bar=False)
        return np.array(embeddings, dtype=float)

    def get_embedding_dimension(self) -> int:
        return self.model.get_sentence_embedding_dimension()
