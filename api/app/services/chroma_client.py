# api/app/services/chroma_client.py
from __future__ import annotations
import os
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "true")

from typing import Any, Callable, Dict, Iterable, List, Tuple
import logging
import time
from urllib.parse import urlparse

import chromadb
from functools import lru_cache
import os as u
from chromadb.config import Settings

from ..config import settings

log = logging.getLogger(__name__)

# =========================================================
# Globals (lazy init)
# =========================================================
_client: chromadb.HttpClient | None = None
_embedder_fn: Callable[[List[str]], List[List[float]]] | None = None  # pure function
_embedding_function_obj: Any | None = None  # Chroma embedding_function-compatible (__call__(texts)->embs)


# =========================================================
# Public: Chroma client
# =========================================================

def _parse_chroma_url() -> tuple[str, int]:
    raw = os.getenv("CHROMA_URL") or "http://chroma:8000"
    u = urlparse(raw)
    host = u.hostname or "chroma"
    port = u.port or (443 if (u.scheme or "http") == "https" else 8000)
    return host, int(port)

def get_chroma_client() -> chromadb.HttpClient:
    global _client
    if _client is not None:
        return _client

    host, port = _parse_chroma_url()

    headers = {}
    token = os.getenv("CHROMA_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Settings は渡さない（0.4.24 で余計な項目を入れると ValidationError）
    _client = chromadb.HttpClient(host=host, port=port, headers=headers)
    return _client

def get_collection(name: str):
    # 存在しなければ作る（検索前の 500 回避）
    client = get_chroma_client()
    return client.get_or_create_collection(name=name)
# =========================================================
# Embedding backends
#   - provider=openai: OpenAI Embeddings API
#   - provider=sbert : sentence-transformers (all-MiniLM-L6-v2 等)
#   - provider=local : 0 ベクトル（開発用）
# =========================================================
def _ensure_embedder():
    """
    _embedder_fn:  List[str] -> List[List[float]]
    _embedding_function_obj: Chroma の embedding_function として渡せる __call__ を持つオブジェクト
    """
    global _embedder_fn, _embedding_function_obj
    if _embedder_fn is not None and _embedding_function_obj is not None:
        return

    provider = (settings.EMBED_PROVIDER or "openai").lower()
    model = (settings.EMBED_MODEL or "").strip()
    dim = int(settings.EMBED_DIMENSIONS or 1536)

    if provider == "sbert":
        # sentence-transformers ベース
        try:
            from chromadb.utils import embedding_functions
        except Exception as e:  # pragma: no cover
            raise RuntimeError("sentence-transformers is not installed (provider=sbert)") from e

        if not model:
            model = "all-MiniLM-L6-v2"

        sbert_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model)

        def _fn(texts: List[str]) -> List[List[float]]:
            embs = sbert_ef(texts)
            if embs and len(embs[0]) != dim:
                log.warning("embedding dimension mismatch: expected=%s actual=%s", dim, len(embs[0]))
            return embs

        class _EFWrapper:
            def __call__(self, texts: List[str]) -> List[List[float]]:
                return _fn(texts)

        _embedder_fn = _fn
        _embedding_function_obj = _EFWrapper()
        log.info("Embedding provider=sbert model=%s", model)

    elif provider == "openai":
        # OpenAI Embeddings API（openai>=1.0）
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("openai>=1.0 is not installed (provider=openai)") from e

        _openai_client = OpenAI()

        if not model:
            # 互換の出力次元に合わせる（既定は text-embedding-3-small 1536 次元を想定）
            model = "text-embedding-3-small"

        def _fn(texts: List[str]) -> List[List[float]]:
            if not texts:
                return []
            resp = _openai_client.embeddings.create(model=model, input=texts)
            embs = [d.embedding for d in resp.data]
            if embs and len(embs[0]) != dim:
                log.warning(
                    "embedding dimension mismatch: expected=%s actual=%s (provider=openai model=%s)",
                    dim, len(embs[0]), model,
                )
            return embs

        class _EFWrapper:
            def __call__(self, texts: List[str]) -> List[List[float]]:
                return _fn(texts)

        _embedder_fn = _fn
        _embedding_function_obj = _EFWrapper()
        log.info("Embedding provider=openai model=%s", model)

    elif provider == "local":
        # 開発用ダミー（距離検索は意味を持たない）
        def _fn(texts: List[str]) -> List[List[float]]:
            return [[0.0] * dim for _ in texts]

        class _EFWrapper:
            def __call__(self, texts: List[str]) -> List[List[float]]:
                return _fn(texts)

        _embedder_fn = _fn
        _embedding_function_obj = _EFWrapper()
        log.info("Embedding provider=local dim=%d", dim)

    else:
        raise ValueError(f"unsupported EMBED_PROVIDER: {provider}")


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    サービス層で直接呼べる埋め込み関数（query_embeddings / upsert 両対応）
    """
    _ensure_embedder()
    return _embedder_fn(texts)  # type: ignore[operator]


# =========================================================
# Collections
# =========================================================
def ensure_collection(client, name: str):
    """
    get -> (失敗) create -> (既存なら) get の二重トライで idempotent に取得。
    取得後はローカルの embedding_function をアタッチ（サーバ状態は変更しない）。
    """
    _ensure_embedder()

    meta = {
        "embedding_model": settings.EMBED_MODEL,
        "embedding_provider": settings.EMBED_PROVIDER,
        "embedding_dimensions": str(settings.EMBED_DIMENSIONS),
    }

    # 1) まず素の get（embedding_function は後でローカル付与）
    try:
        client.get_or_create_collection(
    name=name,
    metadata={"hnsw:space": "cosine"}  # "l2" でもOK。ただし“score”解釈が変わる
)
    except Exception:
        # 2) create を試す
        try:
            coll = client.create_collection(name=name, metadata=meta)
        except Exception as e:
            msg = str(e)
            # {"error":"UniqueConstraintError('... already exists')"} などを吸収
            if "already exists" in msg.lower() or "uniqueconstrainterror" in msg.lower():
                coll = client.get_collection(name=name)  # 3) 再 get
            else:
                raise

    # ローカルに embedding_function を付ける（query_texts 用）
    try:
        coll._embedding_function = _embedding_function_obj  # type: ignore[attr-defined]
    except Exception:
        # 念のためのフォールバック（失敗しても upsert は embeddings 明示指定で動く）
        try:
            coll = client.get_collection(name=name, embedding_function=_embedding_function_obj)
        except Exception:
            pass

    return coll

# 互換（古いコードから呼ばれる可能性）
def get_collection(client, name: str):
    return ensure_collection(client, name)


# =========================================================
# Upsert helper (batch)
# =========================================================
def embed_and_upsert(
    collection,
    items: Iterable[Tuple[str, str, Dict]],  # [(id, text, metadata)]
    *,
    batch_size: int,
    timeout_s: int = 10,
    dry_run: bool = False,
) -> Tuple[int, int, List[Dict[str, str]]]:
    """
    items をバッチで埋め込み → collection.upsert。
    失敗はまとめて1回だけリトライ。errors は [{doc_id, reason}]。
    """
    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict] = []
    for i, t, m in items:
        ids.append(i)
        docs.append(t or "")
        metas.append(m or {})

    if not ids:
        return 0, 0, []

    if dry_run:
        return len(ids), 0, []

    upserted = 0
    failed = 0
    errors: List[Dict[str, str]] = []

    deadline = time.time() + max(1, int(timeout_s))

    for start in range(0, len(ids), max(1, int(batch_size))):
        if time.time() > deadline:
            # タイムアウト：残りは失敗扱い
            rem = len(ids) - start
            failed += rem
            reason = "upsert timeout"
            for i in ids[start:]:
                errors.append({"doc_id": i, "reason": reason})
            break

        i_batch = ids[start : start + batch_size]
        d_batch = docs[start : start + batch_size]
        m_batch = metas[start : start + batch_size]

        def _try_once():
            embs = embed_texts(d_batch)
            collection.upsert(ids=i_batch, embeddings=embs, documents=d_batch, metadatas=m_batch)

        try:
            _try_once()
            upserted += len(i_batch)
        except Exception as e1:
            log.warning("upsert batch failed, retrying once: %s", e1)
            time.sleep(0.5)
            try:
                _try_once()
                upserted += len(i_batch)
            except Exception as e2:
                failed += len(i_batch)
                reason = str(e2)
                for _id in i_batch:
                    errors.append({"doc_id": _id, "reason": reason})

    return upserted, failed, errors

@lru_cache(maxsize=1)
def get_collection(name: str):
    """
    /chroma/search が動的 import で呼び出すフック。
    検索時は勝手に作らず、存在前提で取得だけにする（名前誤りを早く検知するため）。
    """
    client = get_chroma_client()
    return client.get_collection(name)
