# api/app/routers/writeback.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.writeback import writeback_field_service, writeback_view_common_service

# 既定: OpenAPI の Writeback タグ / パスに揃える
router = APIRouter(tags=["Writeback"], prefix="/writeback")


# ---- /writeback/field -------------------------------------------------------
@router.post(
    "/field",
    summary="label_i18n.en_US を portal_fields に書き戻し（既定: skip_if_exists）",
)
def writeback_field(payload: dict, sess: Session = Depends(get_session)):
    """
    Request 例（OpenAPI: WritebackFieldRequest）:
    {
      "model": "sale.order",
      "fields": ["partner_id", "note"],
      "mode": "skip_if_exists" | "overwrite"
    }

    Response 例（OpenAPI: WritebackResult）:
    {
      "updated": { "field_label": 3 },
      "skipped": 2
    }
    """
    result = writeback_field_service(sess, payload or {})
    return result


# ---- /writeback/view_common -------------------------------------------------
@router.post(
    "/view_common",
    summary="ai_purpose_i18n.en_US / help_en_text を portal_view_common に書き戻し（既定: skip_if_exists）",
)
def writeback_view_common(payload: dict, sess: Session = Depends(get_session)):
    """
    Request 例（OpenAPI: WritebackViewCommonRequest）:
    {
      "action_xmlids": ["sale.action_orders", "sale.action_quotations"],
      "targets": ["ai_purpose","help"],
      "mode": "skip_if_exists" | "overwrite"
    }

    Response 例（OpenAPI: WritebackResult）:
    {
      "updated": { "ai_purpose": 1, "help": 2 },
      "skipped": 3
    }
    """
    result = writeback_view_common_service(sess, payload or {})
    return result
