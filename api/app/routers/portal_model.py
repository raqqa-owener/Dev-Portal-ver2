# app/routers/portal_model.py
from __future__ import annotations
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Query, Path, Body, Response, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session



from app.db import get_session
from app.repos.portal_model_repo import PortalModelRepo
from ._helpers import to_problem
from app.schemas.imports import ImportModelRequest, ImportResult
from app.services.portal_import import PortalImportService  # ← 追加

router = APIRouter(prefix="/portal/model", tags=["Portal Model"])

# --- 追加: /import 用のPydanticモデル（ForwardRef回避のため先頭で定義） ----
class ImportModelsRequest(BaseModel):
    models: List[str] = Field(..., description="取り込み対象モデル（例: ['stock.picking']）")
    scaffold: bool = Field(True, description="IRが無い場合も最小構成を作成する")
    update_existing: bool = Field(False, description="既存 portal_model があっても label_i18n を IRに合わせて更新する")

class ImportModelsResult(BaseModel):
    requested: List[str] = Field(default_factory=list)
    found_models: int = 0
    upserted_models: int = 0
    upserted_fields: int = 0
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

# --- 追加: /import 用のPydanticモデル（ForwardRef回避のため先頭で定義） ----
class ImportModelsRequest(BaseModel):
    models: List[str] = Field(..., description="取り込み対象モデル（例: ['stock.picking']）")
    scaffold: bool = Field(True, description="IRが無い場合も最小構成を作成する")
    update_existing: bool = Field(False, description="既存 portal_model があっても label_i18n を IRに合わせて更新する")

class ImportModelsResult(BaseModel):
    requested: List[str] = Field(default_factory=list)
    found_models: int = 0
    upserted_models: int = 0
    upserted_fields: int = 0
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

# --- NEW: ir_model_src → portal_model 取込（modelのみ） ---
@router.post(
    "/import",
    summary="IRソースからPortalへモデルを取り込み（modelのみ）",
    response_model=ImportModelsResult,
)
def import_models(
    req: ImportModelsRequest = Body(...),
    sess: Session = Depends(get_session),
) -> ImportModelsResult:
    try:
        svc = PortalImportService(sess)
        # ← ここだけ変更：update_existing を渡す
        res = svc.import_models(models=req.models, scaffold=req.scaffold, update_existing=req.update_existing)

        created = int(res.get("created", 0))
        updated = int(res.get("updated", 0))
        skipped = int(res.get("skipped", 0))

        return ImportModelsResult(
            requested=list(req.models),
            found_models=created + updated,
            upserted_models=created + updated,
            upserted_fields=0,
            warnings=[f"skipped: {skipped}"] if skipped else [],
            errors=[],
        )
    except Exception as e:
        raise to_problem(e)