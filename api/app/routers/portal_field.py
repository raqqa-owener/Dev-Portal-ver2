from __future__ import annotations
from typing import Optional, Dict, Any

from fastapi import APIRouter, Query, Path, Body, Response, status, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.imports import ImportFieldRequest, ImportResult
from app.schemas.extract_field import ExtractFieldRequest
from app.schemas.common import ExtractResult
from app.services.portal_import import PortalImportService
from app.services.extract import extract_field as run_extract_field
from app.repos.portal_field_repo import PortalFieldRepo
from ._helpers import to_problem
import logging

router = APIRouter(prefix="/portal/field", tags=["Portal Field", "Extract"])
logger = logging.getLogger(__name__)


# 一覧（DB）
@router.get("", summary="フィールド一覧")
def list_fields(
    model: Optional[str] = Query(None),
    field_name: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    limit: int = Query(50, ge=1),
    cursor: Optional[str] = Query(None),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalFieldRepo(sess)
        eq: Dict[str, Any] = {}
        if model:      eq["model"] = model
        if field_name: eq["field_name"] = field_name
        if origin:     eq["origin"] = origin
        items, next_cursor = repo.list_keyset(limit=limit, cursor=cursor, eq_filters=eq or None)
        return {"items": items, "next_cursor": next_cursor}
    except Exception as e:
        raise to_problem(e)

# 作成（DB）
@router.post("", summary="フィールド作成", status_code=status.HTTP_201_CREATED)
def create_field(
    payload: Dict[str, Any] = Body(...),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalFieldRepo(sess)
        return repo.create(payload)
    except Exception as e:
        raise to_problem(e)

# 単一取得（DB）
@router.get("/{id}", summary="フィールド取得")
def get_field(
    id: int = Path(..., ge=1),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalFieldRepo(sess)
        return repo.get(id)
    except Exception as e:
        raise to_problem(e)

# 更新（DB）
@router.patch("/{id}", summary="フィールド更新")
def update_field(
    id: int = Path(..., ge=1),
    payload: Dict[str, Any] = Body(...),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalFieldRepo(sess)
        return repo.update_by_id(id, payload)
    except Exception as e:
        raise to_problem(e)

# 削除（DB）
@router.delete("/{id}", summary="フィールド削除", status_code=status.HTTP_204_NO_CONTENT)
def delete_field(
    id: int = Path(..., ge=1),
    sess: Session = Depends(get_session),
):
    try:
        repo = PortalFieldRepo(sess)
        repo.delete_by_id(id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        raise to_problem(e)

# 取込（実装）
@router.post("/import", response_model=ImportResult, summary="ir_field_src から選択取込")
def import_field(req: ImportFieldRequest = Body(...), sess: Session = Depends(get_session)):
    try:
        svc = PortalImportService(sess)
        res = svc.import_fields(model=req.model, fields=req.fields)
        # 既存のレスポンス設計に合わせ、3キーだけ返す（errors を落としたくなければそのまま res を返してOK）
        return ImportResult(**{
            "created": res.get("created", 0),
            "updated": res.get("updated", 0),
            "skipped": res.get("skipped", 0),
            "errors": res.get("errors", []),
        })
    except Exception as e:
        raise to_problem(e)

# Extract（実装）
@router.post("/extract", response_model=ExtractResult, summary="指定フィールドを translate にキュー投入")
def post_portal_field_extract(payload: ExtractFieldRequest, session: Session = Depends(get_session)):
    return run_extract_field(payload, session)
