# api/app/routers/translate.py
from typing import Optional
from fastapi import APIRouter, Query, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.translate_run import TranslateRunRequest, TranslateRunResult
from app.services.translate import run_translate as run_translate_service

router = APIRouter(prefix="/translate", tags=["Translate"])

@router.get("", summary="translate 行の一覧")
def list_translate(
    status: Optional[str] = Query(None),
    entity: Optional[str] = Query(None),
    limit: int = Query(50, ge=1),
    cursor: Optional[str] = Query(None),
):
    # TODO: 実装（今はモック）
    return {
        "items": [],
        "next_cursor": None,
    }

@router.post("/run", response_model=TranslateRunResult, summary="pending を翻訳して translated に")
def post_translate_run(payload: TranslateRunRequest, session: Session = Depends(get_session)):
    """pending → translated。limit / entities / languages は payload 指定を尊重。"""
    return run_translate_service(payload, session)
