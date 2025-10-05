# app/routers/portal_model_import.py
from __future__ import annotations
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, Body, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.portal_import import PortalImportService
from ._helpers import to_problem

router = APIRouter(prefix="/portal/model", tags=["Portal Model Import"])

class ImportModelsRequest(BaseModel):
    models: List[str] = Field(..., description="取り込み対象モデル（例: ['stock.picking']）")
    scaffold: bool = Field(True, description="Trueでフィールドも同時に取り込み")

class ImportModelsResult(BaseModel):
    requested: List[str]
    found_models: int
    upserted_models: int
    upserted_fields: int
    warnings: List[str] = []
    errors: List[str] = []

@router.post(
    "/import",
    summary="IRソースからPortalへモデル/フィールドを取り込み",
    status_code=status.HTTP_200_OK,
    response_model=ImportModelsResult,
)
def import_models(
    req: ImportModelsRequest = Body(...),
    sess: Session = Depends(get_session),
) -> Any:
    """
    例:
    POST /portal/model/import
    {
      "models": ["stock.picking"],
      "scaffold": true
    }
    """
    try:
        svc = PortalImportService(sess)
        result = svc.import_models(models=req.models, scaffold=req.scaffold)
        return ImportModelsResult(**result)
    except Exception as e:
        raise to_problem(e)
