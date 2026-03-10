#!/usr/bin/env python3
"""
Reindexação completa do Qdrant a partir dos textos armazenados no PostgreSQL.

Execução dentro do container fastapi:
    docker exec rag-fastapi python reindex.py
"""

import os
import sys
import time
import httpx
import numpy as np

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "raguser")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "ragpass")
POSTGRES_DB = os.getenv("POSTGRES_DB", "ragdb")

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "documents")

EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "BAAI/bge-m3")
BATCH_SIZE = int(os.getenv("REINDEX_BATCH_SIZE", "16"))

QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"


def get_pg_connection():
    import psycopg2
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        user=POSTGRES_USER, password=POSTGRES_PASSWORD, dbname=POSTGRES_DB,
    )


def load_all_chunks(conn):
    cur = conn.cursor()
    cur.execute("SELECT id, filename, content FROM documents ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    print(f"[PG] {len(rows)} chunks encontrados")
    return rows


def load_model():
    print(f"[Embeddings] Carregando '{EMBEDDINGS_MODEL}'...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDINGS_MODEL)
    dim = model.get_sentence_embedding_dimension()
    print(f"[Embeddings] Dim: {dim}")
    return model, dim


def ensure_collection(client: httpx.Client, dim: int):
    resp = client.get(f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}")
    if resp.status_code == 200:
        existing_dim = (
            resp.json().get("result", {})
            .get("config", {}).get("params", {})
            .get("vectors", {}).get("size")
        )
        if existing_dim == dim:
            print(f"[Qdrant] Collection OK (dim={dim})")
            return
        print(f"[Qdrant] Dim errada ({existing_dim} vs {dim}). Deletando...")
        client.delete(f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}").raise_for_status()

    print(f"[Qdrant] Criando collection dim={dim}...")
    client.put(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}",
        json={"vectors": {"size": dim, "distance": "Cosine"}},
    ).raise_for_status()
    print("[Qdrant] Collection criada.")


def upsert_batch(client: httpx.Client, points: list):
    client.put(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points",
        json={"points": points},
        timeout=60,
    ).raise_for_status()


def reindex(chunks, model, client: httpx.Client):
    total = len(chunks)
    ok = 0
    errors = 0
    start_all = time.time()
    print(f"\n[Reindex] {total} chunks em batches de {BATCH_SIZE}...")

    for batch_start in range(0, total, BATCH_SIZE):
        batch = chunks[batch_start: batch_start + BATCH_SIZE]
        ids = [r[0] for r in batch]
        filenames = [r[1] for r in batch]
        texts = [r[2] or "" for r in batch]

        valid_mask = [bool(t.strip()) for t in texts]
        valid_texts = [t for t, v in zip(texts, valid_mask) if v]

        if not valid_texts:
            errors += len(batch)
            continue

        t0 = time.time()
        try:
            embs = model.encode(valid_texts, normalize_embeddings=True, show_progress_bar=False)
            embs = np.array(embs, dtype=float)
        except Exception as exc:
            print(f"  [batch {batch_start}] ERRO embedding: {exc}")
            errors += len(batch)
            continue

        norms = np.linalg.norm(embs, axis=1)
        if int(np.sum(norms == 0)) > 0:
            print(f"  [batch {batch_start}] AVISO: vetores zero — pulando")
            errors += len(batch)
            continue

        points = []
        valid_idx = 0
        for i, (doc_id, fn, txt) in enumerate(zip(ids, filenames, texts)):
            if not valid_mask[i]:
                continue
            points.append({
                "id": doc_id,
                "vector": embs[valid_idx].tolist(),
                "payload": {"document_id": doc_id, "filename": fn, "chunk_index": i},
            })
            valid_idx += 1

        try:
            upsert_batch(client, points)
        except Exception as exc:
            print(f"  [batch {batch_start}] ERRO upsert: {exc}")
            errors += len(batch)
            continue

        ok += len(points)
        pct = (batch_start + len(batch)) / total * 100
        print(f"  [{pct:5.1f}%] chunks {batch_start}–{batch_start + len(batch) - 1} ({len(points)} pts) — {time.time()-t0:.1f}s")

    print(f"\n[Reindex] Concluído em {time.time()-start_all:.0f}s")
    print(f"  ✓ Reindexados: {ok}/{total}")
    if errors:
        print(f"  ✗ Erros:       {errors}/{total}")
    return ok, errors


def main():
    print("=" * 60)
    print("  Reindexação: PostgreSQL → BGE-M3 → Qdrant")
    print("=" * 60)

    try:
        conn = get_pg_connection()
    except Exception as exc:
        print(f"[ERRO] PostgreSQL: {exc}")
        sys.exit(1)

    chunks = load_all_chunks(conn)
    conn.close()

    if not chunks:
        print("[AVISO] Sem documentos. Abortando.")
        sys.exit(0)

    model, dim = load_model()

    with httpx.Client(timeout=30) as client:
        ensure_collection(client, dim)
        ok, errors = reindex(chunks, model, client)

    if ok == 0:
        print("\n[ERRO] Nenhum chunk reindexado.")
        sys.exit(1)

    print("\n✅ Reindexação concluída! Teste uma pergunta no chat.")


if __name__ == "__main__":
    main()
