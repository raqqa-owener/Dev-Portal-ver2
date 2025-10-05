from __future__ import annotations
from typing import Optional, Dict, Any

from fastapi import APIRouter, Query, Path, Body, status, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.portal_view_set_primary import SetPrimaryRequest
from app.repos.portal_view_repo import PortalViewRepo
from ._helpers import to_problem

router = APIRouter(prefix="/portal/view", tags=["Portal View"])

# 一覧（DB）
@router.get("", summary="一覧")
def list_views(
    common_id: Optional[int] = Query(None, ge=1),
    view_type: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    limit: int = Query(50, ge=1),
    cursor: Optional[str] = Query(None),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalViewRepo(sess)
        eq: Dict[str, Any] = {}
        if common_id is not None: eq["common_id"] = common_id
        if view_type:             eq["view_type"] = view_type
        if model:                 eq["model"] = model
        items, next_cursor = repo.list_keyset(limit=limit, cursor=cursor, eq_filters=eq or None)
        return {"items": items, "next_cursor": next_cursor}
    except Exception as e:
        raise to_problem(e)

# 作成（DB）
@router.post("", summary="作成", status_code=status.HTTP_201_CREATED)
def create_view(
    payload: Dict[str, Any] = Body(...),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalViewRepo(sess)
        return repo.create(payload)
    except Exception as e:
        raise to_problem(e)

# 取得（DB）
@router.get("/{id}", summary="取得")
def get_view(
    id: int = Path(..., ge=1),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalViewRepo(sess)
        return repo.get(id)
    except Exception as e:
        raise to_problem(e)

# 更新（DB）
@router.patch("/{id}", summary="更新（部分）")
def update_view(
    id: int = Path(..., ge=1),
    payload: Dict[str, Any] = Body(...),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalViewRepo(sess)
        return repo.update_by_id(id, payload)
    except Exception as e:
        raise to_problem(e)

# 主ビュー設定（実装済み API を DB 経由で）
@router.post("/set_primary", status_code=status.HTTP_204_NO_CONTENT, summary="主ビューを設定（common_id 内で単一化）")
def set_primary(req: SetPrimaryRequest, sess: Session = Depends(get_session)):
    try:
        repo = PortalViewRepo(sess)
        if req.view_id is not None:
            repo.set_primary_by_view_id(view_id=req.view_id)
            return
        row = repo.get_by_common_and_type(common_id=req.common_id, view_type=req.view_type)  # type: ignore[arg-type]
        repo.set_primary_by_view_id(view_id=row["id"])
        return
    except Exception as e:
        raise to_problem(e)

# 別名（必要なら本実装に差し替え）
@router.post("/bootstrap_from_common", summary="view_common から骨組み生成（別名エンドポイント）")
def bootstrap_from_common(payload: Dict[str, Any] = Body(...)):
    return {"created": 0, "skipped": 0}
