# service/chroma_search.py
from __future__ import annotations

from typing import List, Dict, Any, Optional
import logging
import os

log = logging.getLogger(__name__)

from app.services.chroma_client import get_chroma_client

FALLBACK_ON_EMPTY = os.getenv("CHROMA_SEARCH_FALLBACK_ON_EMPTY", "true").lower() in ("1","true","yes","on")
FORCE_TEXT_FALLBACK = os.getenv("CHROMA_SEARCH_FORCE_TEXT", "false").lower() in ("1","true","yes","on")

def _norm_cols(cols):
    if not cols:
        return []
    seen, out = set(), []
    for c in cols or []:
        if c is None:
            continue
        for p in str(c).split(","):
            p = p.strip()
            if p and p not in seen:
                seen.add(p); out.append(p)
    return out

def _load_embedding_client_or_none():
    try:
        return _load_embedding_client()
    except Exception as e:
        log.warning("chroma_search: EmbeddingClient unavailable; fallback to query_texts (%s)", e)
        return None
    
# ------------------------------
# 環境変数ゲート
# ------------------------------
def _is_enabled() -> bool:
    v = os.getenv("ALLOW_CHROMA_SEARCH", "true").strip().lower()
    return v in ("1", "true", "yes", "on")


# ------------------------------
# 内部ヘルパ（Embedding Client）
# ------------------------------
_EMBED_CLIENT: Optional[object] = None

def _load_embedding_client():
    """
    1) 既存の EmbeddingClient を複数候補から探して使う
    2) 見つからなければ OpenAI の簡易 Shim を使う（環境変数 OPENAI_API_KEY 必須）
    常に「自前でベクター化」して Chroma には query_embeddings を渡す。
    """
    global _EMBED_CLIENT
    if _EMBED_CLIENT is not None:
        return _EMBED_CLIENT

    candidates = [
        "app.services.embeddings",
        "app.services.embedding",
        "app.services.embedding_client",
        "app.services.openai_embeddings",
        "app.libs.embeddings",
        "app.core.embeddings",
    ]
    last_err: Exception | None = None

    # まずは既存の EmbeddingClient を探す
    for mod in candidates:
        try:
            m = __import__(mod, fromlist=["EmbeddingClient"])
            EmbeddingClient = getattr(m, "EmbeddingClient")
            _EMBED_CLIENT = EmbeddingClient()
            log.info("chroma_search: EmbeddingClient <- %s", mod)
            return _EMBED_CLIENT
        except Exception as e:
            last_err = e

    # ---- OpenAI Shim（settings に依存しない）----
    try:
        from openai import OpenAI  # type: ignore
        model = os.getenv("EMBED_MODEL", "text-embedding-3-small")
        client = OpenAI()  # OPENAI_API_KEY は env から自動取得

        class _OpenAIShim:
            def __init__(self, client, model):
                self._client = client
                self.model = model
            def embed_one(self, text: str):
                resp = self._client.embeddings.create(model=self.model, input=text)
                return list(resp.data[0].embedding)

        _EMBED_CLIENT = _OpenAIShim(client, model)
        log.warning(
            "chroma_search: using OpenAI shim EmbeddingClient (model=%s, key=%s)",
            model, "SET" if os.getenv("OPENAI_API_KEY") else "MISSING",
        )
        return _EMBED_CLIENT
    except Exception as e:
        last_err = e

    raise ModuleNotFoundError(
        "EmbeddingClient could not be imported. Tried: "
        + ", ".join(candidates)
        + (f". Last error: {last_err}" if last_err else "")
    )


# ------------------------------
# 内部ヘルパ（Collection）
# ------------------------------
def _get_collection(name: str):
    """
    クライアント側で埋め込みを作るため、Chroma 側の embedding_function は未設定。
    ただし距離空間は cosine に固定しておく。
    """
    client = get_chroma_client()
    return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})


def _norm_collections(cols: Optional[List[str]]) -> List[str]:
    if not cols:
        return []
    # 重複除去＋空文字除去
    seen, out = set(), []
    for c in cols:
        c = (c or "").strip()
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


# ------------------------------
# Public API
# ------------------------------
def search_collections(q: str, collections: List[str], n_results: int = 5) -> List[Dict[str, Any]]:
    cols = _norm_cols(collections)  # ← ここでCSV/重複/空を正規化

    emb = None if FORCE_TEXT_FALLBACK else _load_embedding_client_or_none()
    hits: List[Dict[str, Any]] = []

    for name in cols:
        col = _get_collection(name)
        res_hits = []
        used = None
        try:
            if emb is not None:
                q_vec = emb.embed_one(q)
                res = col.query(query_embeddings=[q_vec], n_results=n_results,
                                include=["documents","metadatas","distances"])
                ids   = (res.get("ids") or [[]])[0]
                dists = (res.get("distances") or [[]])[0]
                docs  = (res.get("documents") or [[]])[0]
                metas = (res.get("metadatas") or [[]])[0]
                for i in range(min(len(ids), len(dists))):
                    res_hits.append({
                        "doc_id": ids[i],
                        "collection": name,
                        "distance": float(dists[i]),
                        "document": docs[i] if i < len(docs) else None,
                        "metadata": metas[i] if i < len(metas) else {},
                    })
                used = "embeddings"
                if not res_hits and FALLBACK_ON_EMPTY:
                    raise RuntimeError("empty_hits_with_embeddings")
        except Exception as e:
            log.info("chroma_search: embeddings path failed on %s -> %s; falling back to query_texts", name, type(e).__name__)

        if used is None or not res_hits:
            # テキストフォールバック（Chromaサーバ側の埋め込み実装を利用）
            res = col.query(query_texts=[q], n_results=n_results,
                            include=["documents","metadatas","distances"])
            ids   = (res.get("ids") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            docs  = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            for i in range(min(len(ids), len(dists))):
                res_hits.append({
                    "doc_id": ids[i],
                    "collection": name,
                    "distance": float(dists[i]),
                    "document": docs[i] if i < len(docs) else None,
                    "metadata": metas[i] if i < len(metas) else {},
                })

        hits.extend(res_hits)

    hits.sort(key=lambda h: h["distance"])
    return hits
