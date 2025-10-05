# app/routers/smart_button.py
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Query, Path, Body, status
from pydantic import BaseModel, Field

router = APIRouter(tags=["Portal Smart Button"])

# ---- API↔DB マッピングメモ ----------------------------------------
# API: label_i18n            -> DB: label_i18n (jsonb)
# API: target_model          -> DB: target_model
# API: view_url              -> DB: dest_view_url
# API: origin                -> DB: origin
# API: module                -> DB: module
# API: show_badge            -> DB: show_count
# API: badge_count_expr      -> DB: badge_count_expr
# API: is_codegen_target     -> DB: is_codegen_target
# API: notes                 -> DB: notes
# API: groups (list[str])    -> DB: groups (jsonb)
# API: domain (object)       -> DB: domain (jsonb)
# API: context (object)      -> DB: context (jsonb)
# API: sequence              -> DB: sequence
# API: model                 -> DB: model（便宜上：所有モデルを表示）
# API: button_key + view_id  -> DB: UNIQUE(view_id, button_key)
# ------------------------------------------------------------------

class CursorList(BaseModel):
    items: List[Dict[str, Any]]
    next_cursor: Optional[str] = None

class SmartButtonBase(BaseModel):
    # 主要キー（POSTで必須化）
    view_id: Optional[int] = Field(None, ge=1, description="親ビューID")
    button_key: Optional[str] = Field(None, description="業務キー（view内ユニーク）")

    # 表示名（多言語）
    label_i18n: Optional[Dict[str, str]] = Field(
        default=None,
        description='{"ja_JP":"...", "en_US":"..."} を推奨。片言語入力でも可'
    )

    # 遷移先など
    target_model: Optional[str] = Field(None, description="例: stock.picking")
    view_url: Optional[str] = Field(None, description="例: /web#action=...&model=...")

    # メタ
    origin: Optional[str] = Field(None, description="standard/module/studio/portal/unknown")
    module: Optional[str] = None
    is_codegen_target: Optional[bool] = False
    notes: Optional[str] = None

    # バッジ表示
    show_badge: Optional[bool] = Field(None, description="件数表示の有無（DB: show_count）")
    badge_count_expr: Optional[str] = Field(None, description="件数計算式や簡易ドメインの文字列")

    # 権限・条件
    groups: Optional[List[str]] = Field(
        default=None,
        description="アクセス許可のxml_id配列を推奨（DBはjsonbで保持）"
    )
    domain: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None

    # 並び・所有モデルなど
    sequence: Optional[int] = Field(None, ge=0)
    model: Optional[str] = Field(None, description="所有モデルの表示用（任意）")

class SmartButtonCreate(SmartButtonBase):
    view_id: int = Field(..., ge=1)
    button_key: str = Field(..., min_length=1)

class SmartButtonUpdate(SmartButtonBase):
    # PATCH なので全項目任意
    pass

class SmartButton(SmartButtonBase):
    id: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class SmartButtonList(BaseModel):
    items: List[SmartButton]
    next_cursor: Optional[str] = None


@router.get("/portal/smart_button", summary="スマートボタン一覧", response_model=SmartButtonList)
def list_smart_buttons(
    view_id: Optional[int] = Query(None, ge=1),
    button_key: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    cursor: Optional[str] = Query(None),
):
    """
    Keysetページング想定（cursor=Base64({"last_id":<int>})）。
    いまはモックとして空返却。Repo接続時に置換。
    """
    return {"items": [], "next_cursor": None}


@router.post(
    "/portal/smart_button",
    summary="作成",
    status_code=status.HTTP_201_CREATED,
    response_model=SmartButton,
)
def create_smart_button(payload: SmartButtonCreate = Body(...)):
    """
    モック実装：受け取った値をそのまま返す。
    後で Repo に差し替え（INSERT ... RETURNING）。
    """
    return {
        "id": 1,
        **payload.model_dump(exclude_unset=True),
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }


@router.patch(
    "/portal/smart_button/{id}",
    summary="更新",
    response_model=SmartButton,
)
def update_smart_button(
    id: int = Path(..., ge=1),
    payload: SmartButtonUpdate = Body(...),
):
    """
    モック実装：部分更新の体裁のみ（PATCH＝シャローマージ前提）。
    Repo接続時：jsonbは DB 側でマージ（groups/domain/context は jsonb）。
    """
    base = {
        "id": id,
        "view_id": 1,
        "button_key": "pickings",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    return {**base, **payload.model_dump(exclude_unset=True)}


@router.post(
    "/portal/smart_button/bulk_upsert",
    summary="複数ボタンの一括UPSERT",
    response_model=Dict[str, Any],
)
def bulk_upsert_smart_buttons(payload: List[SmartButtonCreate] = Body(...)):
    """
    モック実装：件数のみ返却。
    Repo接続時：(view_id, button_key) を衝突キーに ON CONFLICT DO UPDATE。
    """
    return {"updated": {"portal_smart_button": len(payload)}, "skipped": 0}
