# api/app/services/chroma_query.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging

from .chroma_client import get_chroma_client, ensure_collection

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 5


def _flatten_results(res: Dict[str, Any], coll_name: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for i, doc_id in enumerate(ids):
        out.append(
            {
                "doc_id": doc_id,
                "collection": coll_name,
                "distance": float(dists[i]) if i < len(dists) else 0.0,
                "document": docs[i] if i < len(docs) else None,
                "metadata": metas[i] if i < len(metas) else {},
            }
        )
    return out


def _try_query_collection(collection, q: str, n: int) -> List[Dict[str, Any]]:
    include = ["ids", "documents", "metadatas", "distances"]
    # 1) query_texts
    try:
        res = collection.query(query_texts=[q], n_results=n, include=include)
        return _flatten_results(res, getattr(collection, "name", ""))
    except Exception as e1:
        log.info("[chroma-query] query_texts failed on %s: %s", getattr(collection, "name", "?"), e1)
    # 2) query_embeddings（オプション）
    try:
        from .chroma_client import embed_texts  # optional
        emb = embed_texts([q])
        res = collection.query(query_embeddings=emb, n_results=n, include=include)
        return _flatten_results(res, getattr(collection, "name", ""))
    except Exception as e2:
        log.info("[chroma-query] query_embeddings failed on %s: %s", getattr(collection, "name", "?"), e2)
        return []


def run_chroma_query(*, q: str, collections: Optional[List[str]], limit: int) -> Dict[str, Any]:
    """
    ベクター検索（Chroma）と SQL フォールバックを統合して上位 N を返す。
    """
    client = get_chroma_client()
    coll_names = collections or ["portal_field_ja", "portal_view_common_ja"]
    limit = max(1, min(int(limit or DEFAULT_LIMIT), 100))

    # --- Chroma 検索 ---
    vector_hits: List[Dict[str, Any]] = []
    for name in coll_names:
        try:
            coll = ensure_collection(client, name)
        except Exception as ex:
            log.info("[chroma-query] ensure_collection(%s) failed: %s", name, ex)
            continue
        vector_hits.extend(_try_query_collection(coll, q, limit))

    # --- SQL フォールバック（常に実行して統合） ---
    sql_hits: List[Dict[str, Any]] = []
    try:
        from ..db import session_scope
        from ..repos.portal_chroma_doc_repo import PortalChromaDocRepo
        with session_scope() as s:
            repo = PortalChromaDocRepo(s)
            rows = repo.search_upserted_text(q=q, collections=coll_names, limit=limit)
            for r in rows:
                doc_id = (getattr(r, "doc_id", None) or getattr(r, "natural_key", None) or f"row:{r.id}")
                sql_hits.append(
                    {
                        "doc_id": doc_id,
                        "collection": r.collection,
                        "distance": 0.0,  # フォールバックは距離なし
                        "document": r.doc_text,
                        "metadata": r.metadata or {},
                    }
                )
    except Exception as ex:
        log.exception("[chroma-query] SQL fallback failed: %s", ex)

    # --- 統合（doc_id, collection のペアで重複排除） ---
    merged: List[Dict[str, Any]] = []
    seen = set()
    for h in (vector_hits + sql_hits):
        key = (h.get("doc_id"), h.get("collection"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(h)

    # cosine 距離想定で昇順（SQLヒットは 0.0 として先頭に来やすい）
    merged.sort(key=lambda h: h.get("distance", 1e9))
    return {"hits": merged[:limit]}
