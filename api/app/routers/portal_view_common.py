from __future__ import annotations
from typing import Optional, Dict, Any

from fastapi import APIRouter, Query, Path, Body, status, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.repos.portal_view_common_repo import PortalViewCommonRepo
from app.schemas.imports import ImportViewCommonRequest, ImportResult
from app.schemas.bootstrap_view import BootstrapViewRequest, BootstrapResult
from app.schemas.extract_view_common import ExtractViewCommonRequest
from app.schemas.common import ExtractResult
from app.services.portal_import import PortalImportService
from app.services.bootstrap_view import BootstrapViewService
from app.services.extract import extract_view_common as run_extract_view_common
from ._helpers import to_problem

router = APIRouter(prefix="/portal/view_common", tags=["Portal View Common", "Extract"])

# 一覧（DB）
@router.get("", summary="一覧")
def list_view_common(
    action_xmlid: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    limit: int = Query(50, ge=1),
    cursor: Optional[str] = Query(None),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalViewCommonRepo(sess)
        eq: Dict[str, Any] = {}
        if action_xmlid: eq["action_xmlid"] = action_xmlid
        if model:        eq["model_tech"]  = model  # ← ここを修正
        items, next_cursor = repo.list_keyset(limit=limit, cursor=cursor, eq_filters=eq or None)
        return {"items": items, "next_cursor": next_cursor}
    except Exception as e:
        raise to_problem(e)

# 作成（DB）: model → model_tech 変換を repo に任せる
@router.post("", summary="作成", status_code=status.HTTP_201_CREATED)
def create_view_common(
    payload: Dict[str, Any] = Body(...),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalViewCommonRepo(sess)
        return repo.create_common(payload)
    except Exception as e:
        raise to_problem(e)

# 詳細（DB）
@router.get("/{id}", summary="詳細")
def get_view_common(
    id: int = Path(..., ge=1),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalViewCommonRepo(sess)
        return repo.get_detail(id)
    except Exception as e:
        raise to_problem(e)

# 更新（DB）
@router.patch("/{id}", summary="更新（部分）")
def update_view_common(
    id: int = Path(..., ge=1),
    payload: Dict[str, Any] = Body(...),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalViewCommonRepo(sess)
        return repo.patch_common(id, payload)
    except Exception as e:
        raise to_problem(e)

# 取込：portal_field_src をソースに、model/fields 指定で portal_view_common を UPSERT
@router.post("/import", response_model=ImportResult, summary="ir_view_src（action-centric）から取込（UPSERT）")
def import_view_common(req: ImportViewCommonRequest = Body(...), sess: Session = Depends(get_session)):
    try:
        svc = PortalImportService(sess)
        # こちらのメソッド名に統一（実装済み）
        res = svc.import_view_common_by_action_xmlids(action_xmlids=req.action_xmlids)
        return ImportResult(**svc.import_view_common_by_action_xmlids(req.action_xmlids))
    except Exception as e:
        raise to_problem(e)

@router.post("/bootstrap_view", response_model=BootstrapResult, summary="view_types[] を展開し portal_view の骨組みを作成")
def bootstrap_view(req: BootstrapViewRequest, sess: Session = Depends(get_session)):
    try:
        svc = BootstrapViewService(sess)
        res = svc.bootstrap_by_action_xmlids(
            action_xmlids=req.action_xmlids,
            set_primary_from_common=req.set_primary_from_common,
        )
        return BootstrapResult(**res)
    except Exception as e:
        raise to_problem(e)

@router.post("/extract", response_model=ExtractResult, summary="ai_purpose / help を translate にキュー投入")
def post_portal_view_common_extract(payload: ExtractViewCommonRequest, session: Session = Depends(get_session)):
    return run_extract_view_common(payload, session)