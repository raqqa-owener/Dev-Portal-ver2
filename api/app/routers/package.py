# app/routers/package.py
from __future__ import annotations
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import session_scope
from app.services.package import PackService

router = APIRouter(tags=["Chroma"])

class ChromaPackageReq(BaseModel):
    entities: List[str] = Field(default_factory=lambda: ["view_common"])
    lang: str = "ja"
    collections: Dict[str, str] = Field(default_factory=lambda: {"view_common": "portal_view_common_ja"})
    limit: int = Field(1000, ge=1, le=5000)
    dry_run: bool = False  # NOTE: 現実装では無視（常に実行）

@router.post("/package", summary="Translate済みを portal_chroma_doc に詰める（state=queued）")
def post_chroma_package(req: ChromaPackageReq):
    try:
        with session_scope() as s:
            svc = PackService(s)
            result = svc.pack(
                entities=req.entities,
                lang=req.lang,
                collections=req.collections,
                limit=req.limit,
            )
            return result
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"package failed: {e}")
