# api/app/routers/chroma_docs.py
from __future__ import annotations
from typing import Optional, Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.chroma_package import ChromaDocsList
#from app.repos.portal_chroma_doc_repo import PortalChromaDocRepo
try:
    from app.repos.portal_chroma_doc_repo import PortalChromaDocRepo
except ImportError:
    # 旧名しか無い環境向け
    from app.repos.portal_chroma_doc_repo import PortalChromaDocRepository as PortalChromaDocRepo

# 旧: from app.repos.portal_chroma_doc_repo import PortalChromaDocRepo
try:
    from app.repos.portal_chroma_doc_repo import PortalChromaDocRepo
except ImportError:
    # 片方しか無い環境向けのフォールバック
    from app.repos.portal_chroma_doc_repo import PortalChromaDocRepository as PortalChromaDocRepo


router = APIRouter()

@router.get("/docs", response_model=ChromaDocsList, tags=["Package"], summary="portal_chroma_doc の一覧")
def list_chroma_docs(
    status: Optional[Literal["queued", "upserted", "failed"]] = Query(default=None),
    entity: Optional[Literal["field", "view_common"]] = Query(default=None),
    model: Optional[str] = None,
    collection: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
):
    try:
        cur_id = int(cursor) if cursor else None
    except Exception:
        cur_id = None

    repo = PortalChromaDocRepo(session)
    items, next_cursor = repo.list_keyset(
        status=status,
        entity=entity,
        model=model,
        collection=collection,
        limit=limit,
        cursor=cur_id,
    )
    return {"items": items, "next_cursor": (str(next_cursor) if next_cursor else None)}
