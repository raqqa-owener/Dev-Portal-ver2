# app/routers/chroma_docs.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text as SQL

from app.db import get_session

router = APIRouter(tags=["Chroma"])

def _to_int_or_none(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return None

@router.get("/chroma/docs", summary="portal_chroma_doc の一覧（キーセット）")
def list_docs(
    *,
    status: Optional[str] = Query(None, description="state 列（queued / upserted / failed）"),
    entity: Optional[str] = Query(None, description="entity 列（例: field / view_common）"),
    model: Optional[str] = Query(None, description="top-level model 列"),
    collection: Optional[str] = Query(None, description="collection 列"),
    limit: int = Query(50, ge=1, le=500),
    cursor: Optional[str] = Query(None, description="次ページ用。前回レスポンスの last id を文字列で渡す簡易版"),
    s: Session = Depends(get_session),
):
    """
    注意点:
    - SQLAlchemy の句（ClauseElement）を真偽値判定にかけない。
    - execute() の第2引数は常に dict（パラメータ）を渡す。
    """
    last_id = _to_int_or_none(cursor) or 0

    # WHERE 句は文字列連結で組み立て（ClauseElement を boolean にしない）
    clauses: List[str] = ["id > :last_id"]
    params: Dict[str, Any] = {"last_id": last_id, "limit": limit}

    if status is not None and status != "":
        clauses.append("state = :state")
        params["state"] = status
    if entity is not None and entity != "":
        clauses.append("entity = :entity")
        params["entity"] = entity
    if model is not None and model != "":
        clauses.append("model = :model")
        params["model"] = model
    if collection is not None and collection != "":
        clauses.append("collection = :collection")
        params["collection"] = collection

    sql = SQL(f"""
        SELECT
            id, doc_id, entity, natural_key, lang, collection,
            doc_text, meta, state, model, status, payload,
            to_char(updated_at, 'YYYY-MM-DD"T"HH24:MI:SSOF') AS updated_at
        FROM public.portal_chroma_doc
        WHERE {' AND '.join(clauses)}
        ORDER BY id ASC
        LIMIT :limit
    """)

    rows = s.execute(sql, params).mappings().all()

    # meta が text 型で来た場合の保険
    out: List[Dict[str, Any]] = []
    for r in rows:
        meta_val = r.get("meta")
        if isinstance(meta_val, str):
            try:
                import json
                meta_val = json.loads(meta_val)
            except Exception:
                meta_val = {}
        out.append({
            "id": r["id"],
            "doc_id": r.get("doc_id"),
            "entity": r.get("entity"),
            "natural_key": r.get("natural_key"),
            "lang": r.get("lang"),
            "collection": r.get("collection"),
            "doc_text": r.get("doc_text"),
            "meta": meta_val,
            "state": r.get("state"),
            "model": r.get("model"),
            "status": r.get("status"),
            "payload": r.get("payload") or {},
            "updated_at": r.get("updated_at"),
        })

    next_cursor = str(out[-1]["id"]) if out else None
    return {"items": out, "next_cursor": next_cursor}
