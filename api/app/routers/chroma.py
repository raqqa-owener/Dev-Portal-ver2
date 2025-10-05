# app/routers/chroma.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.schemas.chroma_upsert import ChromaUpsertRequest, ChromaUpsertResult

# 可能なら既存の Problem+JSON 変換ヘルパを使用（無ければ素の HTTPException にフォールバック）
try:
    from ._helpers import problem_response  # type: ignore
except Exception:  # pragma: no cover
    problem_response = None  # type: ignore

log = logging.getLogger(__name__)

# /chroma 配下でまとめる
router = APIRouter(prefix="/chroma", tags=["Chroma"])


# =========================
# Upsert
# =========================
@router.post(
    "/upsert",
    response_model=ChromaUpsertResult,
    summary="portal_chroma_doc.state=queued を Chroma に upsert（H-slim）",
    include_in_schema=True,
)
def chroma_upsert(req: ChromaUpsertRequest) -> ChromaUpsertResult:
    """
    入力検証 → サービス呼び出し → 結果返却。
    例外は routers/_helpers.py の Problem 変換に委譲（未提供環境では 5xx を返す）。
    """
    if not getattr(settings, "ALLOW_CHROMA_UPSERT", True):
        raise HTTPException(status_code=403, detail="Chroma upsert is disabled in this environment")

    try:
        # 遅延 import（モジュール import 失敗でルーターごと消えるのを防ぐ）
        from app.services.chroma_upsert import run_chroma_upsert  # type: ignore

        result = run_chroma_upsert(
            collections=req.collections,
            limit=req.limit,
            dry_run=req.dry_run,
        )
        return ChromaUpsertResult(**result)
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        log.exception("chroma_upsert failed: %s", e)
        if problem_response:
            return problem_response(e)  # type: ignore[return-value]
        raise HTTPException(status_code=503, detail=f"chroma_upsert failed: {e}")


# =========================
# Query（既存：SQL フォールバック内蔵）
# =========================
class ChromaQueryRequest(BaseModel):
    q: str = Field(..., description="検索クエリ文字列")
    collections: Optional[List[str]] = Field(None, description="検索対象コレクション")
    limit: int = Field(5, ge=1, le=100, description="返却件数")


class ChromaQueryHit(BaseModel):
    doc_id: str
    collection: str
    distance: float
    document: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChromaQueryResponse(BaseModel):
    hits: List[ChromaQueryHit]


@router.post(
    "/query",
    response_model=ChromaQueryResponse,
    include_in_schema=True,
)
def chroma_query(body: ChromaQueryRequest):
    """
    ベクター検索（Chroma → SQL フォールバック）。距離の小さい順に上位を返します。
    """
    try:
        from app.services.chroma_query import run_chroma_query  # 遅延 import
        return run_chroma_query(q=body.q, collections=body.collections, limit=body.limit)
    except Exception as e:  # pragma: no cover
        log.exception("chroma_query failed: %s", e)
        if problem_response:
            return problem_response(e)  # type: ignore[return-value]
        raise HTTPException(status_code=503, detail=f"chroma_query failed: {e}")


# =========================
# Search（距離を Chroma 側で算出して返すシンプル版）
# =========================

# Swagger に distance を出すためのスキーマ
class ChromaSearchHit(BaseModel):
    doc_id: str
    collection: str
    distance: float
    document: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChromaSearchResponse(BaseModel):
    hits: List[ChromaSearchHit] = Field(default_factory=list)


def _norm_collections(cols: Optional[List[str]]) -> List[str]:
    """
    collections を正規化：
      - None/空は [] に
      - "a,b" の1要素形式/複数要素をともに許可
      - 重複排除・空白除去
    """
    if not cols:
        return []
    seen: set[str] = set()
    out: List[str] = []
    for c in cols:
        if c is None:
            continue
        for p in str(c).split(","):
            p = p.strip()
            if not p or p in seen:
                continue
            seen.add(p)
            out.append(p)
    return out


@router.get(
    "/search",
    response_model=ChromaSearchResponse,
    summary="Chroma 検索（distance 付き）",
    include_in_schema=True,
)
def chroma_search(
    q: str = Query(..., description="検索クエリ（日本語OK）"),
    collections: List[str] = Query(
        default=["portal_field_ja_v2", "portal_view_common_ja_v2"],
        description="検索対象コレクション（Swaggerでは Add item で複数追加。'a,b' 形式も可）",
    ),
    n: int = Query(5, ge=1, le=50, description="返却件数"),
) -> ChromaSearchResponse:
    # Feature gate（未定義なら許可）
    if not getattr(settings, "ALLOW_CHROMA_SEARCH", True):
        raise HTTPException(status_code=403, detail="Chroma search is disabled in this environment")

    try:
        from app.services.chroma_search import search_collections  # 遅延 import

        cols = _norm_collections(collections)
        hits = search_collections(q, cols, n_results=n)
        # search_collections は dict のリストを返す想定
        return ChromaSearchResponse(hits=[ChromaSearchHit(**h) for h in hits])
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        log.exception("chroma_search failed: %s", e)
        if problem_response:
            return problem_response(e)  # type: ignore[return-value]
        raise HTTPException(status_code=503, detail=f"chroma_search failed: {e}")
