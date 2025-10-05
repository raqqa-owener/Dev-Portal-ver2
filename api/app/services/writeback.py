# Optional writeback
# api/app/services/writeback.py
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


# ---------------------------- helpers ----------------------------------------
def _is_blank(s: Optional[str]) -> bool:
    return s is None or str(s).strip() == ""


def _column_exists(sess: Session, schema: str, table: str, column: str) -> bool:
    sql = text(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = :schema
           AND table_name   = :table
           AND column_name  = :column
         LIMIT 1
        """
    )
    try:
        return bool(sess.execute(sql, {"schema": schema, "table": table, "column": column}).first())
    except Exception:
        return False


def _fetch_translation(
    sess: Session,
    *,
    natural_key: str,
    target_hint: Optional[str] = None,  # "ai_purpose" | "help" | "field_label"
) -> Optional[str]:
    """
    最も新しい翻訳済テキストを 1 件返す。
    - まず portal_translate.translated_text を探す（フェーズF以降の標準）
    - 無い場合のフォールバック:
        help/field_label -> translated_label
        ai_purpose       -> translated_purpose
    - state は translated / ready_for_chroma / done を許容
    """
    # 標準カラム（フェーズF以降）
    if _column_exists(sess, "public", "portal_translate", "translated_text"):
        sql = text(
            """
            SELECT translated_text
              FROM public.portal_translate
             WHERE natural_key = :nk
               AND translated_text IS NOT NULL
               AND state IN ('translated','ready_for_chroma','done')
             ORDER BY updated_at DESC
             LIMIT 1
            """
        )
        row = sess.execute(sql, {"nk": natural_key}).first()
        return row[0] if row else None

    # フォールバック（古い互換スキーマ）
    if target_hint == "ai_purpose":
        col = "translated_purpose"
    else:
        col = "translated_label"
    sql_fb = text(
        f"""
        SELECT {col}
          FROM public.portal_translate
         WHERE natural_key = :nk
           AND {col} IS NOT NULL
         ORDER BY updated_at DESC
         LIMIT 1
        """
    )
    row = sess.execute(sql_fb, {"nk": natural_key}).first()
    return row[0] if row else None


def _expand_fields(sess: Session, model: str, fields: Optional[Iterable[str]]) -> list[tuple[str, str]]:
    """
    対象 (model, field_name) の配列を返す。
    fields が空/None の場合は model 配下の全フィールド。
    """
    if fields:
        pairs = [(model, f) for f in fields]
        return pairs

    sql = text(
        """
        SELECT model, field_name
          FROM public.portal_fields
         WHERE model = :model
         ORDER BY field_name
        """
    )
    rows = sess.execute(sql, {"model": model}).all()
    return [(r[0], r[1]) for r in rows]


# ---------------------------- field writeback --------------------------------
def writeback_field_service(sess: Session, payload: dict) -> dict:
    """
    WritebackFieldRequest 相当の payload を受け取って処理。
    """
    model = (payload or {}).get("model")
    fields = (payload or {}).get("fields") or None
    mode = (payload or {}).get("mode") or "skip_if_exists"  # overwrite | skip_if_exists

    if not model or not isinstance(model, str):
        # フォーマット簡素化（Problem+JSON は上位に任せる設計のためここでは dict）
        return {"updated": {"field_label": 0}, "skipped": 0}

    targets = _expand_fields(sess, model, fields)
    updated_label = 0
    skipped = 0

    for m, field_name in targets:
        # 既存の en_US 値（skip_if_exists 判定用）
        cur_sql = text(
            """
            SELECT label_i18n->>'en_US'
              FROM public.portal_fields
             WHERE model=:model AND field_name=:field
             LIMIT 1
            """
        )
        cur_row = sess.execute(cur_sql, {"model": m, "field": field_name}).first()
        existing_en = cur_row[0] if cur_row else None

        if mode == "skip_if_exists" and not _is_blank(existing_en):
            skipped += 1
            continue

        nk = f"field::{m}::{field_name}"
        translated = _fetch_translation(sess, natural_key=nk, target_hint="field_label")
        if _is_blank(translated):
            skipped += 1
            continue

        # JSONB upsert（右側優先で上書き）
        upd_sql = text(
            """
            UPDATE public.portal_fields
               SET label_i18n = COALESCE(label_i18n, '{}'::jsonb) || jsonb_build_object('en_US', :en),
                   updated_at = now()
             WHERE model=:model AND field_name=:field
            """
        )
        sess.execute(upd_sql, {"en": str(translated), "model": m, "field": field_name})
        updated_label += 1

    # ここで commit は上位（リクエスト境界）に委譲される想定
    return {"updated": {"field_label": int(updated_label)}, "skipped": int(skipped)}


# ------------------------- view_common writeback ------------------------------
def writeback_view_common_service(sess: Session, payload: dict) -> dict:
    """
    WritebackViewCommonRequest 相当の payload を受け取って処理。
    """
    action_xmlids = (payload or {}).get("action_xmlids") or []
    req_targets = (payload or {}).get("targets") or ["ai_purpose", "help"]
    mode = (payload or {}).get("mode") or "skip_if_exists"  # overwrite | skip_if_exists

    if not action_xmlids:
        return {"updated": {"ai_purpose": 0, "help": 0}, "skipped": 0}

    do_ai = "ai_purpose" in req_targets
    do_help = "help" in req_targets

    updated_purpose = 0
    updated_help = 0
    skipped = 0

    for ax in action_xmlids:
        if do_ai:
            # 既存 en_US（skip 判定）
            cur_sql = text(
                """
                SELECT ai_purpose_i18n->>'en_US'
                  FROM public.portal_view_common
                 WHERE action_xmlid=:ax
                 LIMIT 1
                """
            )
            cur_row = sess.execute(cur_sql, {"ax": ax}).first()
            existing_en = cur_row[0] if cur_row else None

            if mode == "skip_if_exists" and not _is_blank(existing_en):
                skipped += 1
            else:
                nk = f"view_common::{ax}::ai_purpose"
                translated = _fetch_translation(sess, natural_key=nk, target_hint="ai_purpose")
                if _is_blank(translated):
                    skipped += 1
                else:
                    upd_sql = text(
                        """
                        UPDATE public.portal_view_common
                           SET ai_purpose_i18n = COALESCE(ai_purpose_i18n, '{}'::jsonb)
                                                || jsonb_build_object('en_US', :en),
                               updated_at = now()
                         WHERE action_xmlid=:ax
                        """
                    )
                    sess.execute(upd_sql, {"en": str(translated), "ax": ax})
                    updated_purpose += 1

        if do_help:
            # 既存 en（skip 判定）
            cur_sql = text(
                """
                SELECT help_en_text
                  FROM public.portal_view_common
                 WHERE action_xmlid=:ax
                 LIMIT 1
                """
            )
            cur_row = sess.execute(cur_sql, {"ax": ax}).first()
            existing_en = cur_row[0] if cur_row else None

            if mode == "skip_if_exists" and not _is_blank(existing_en):
                skipped += 1
            else:
                nk = f"view_common::{ax}::help"
                translated = _fetch_translation(sess, natural_key=nk, target_hint="help")
                if _is_blank(translated):
                    skipped += 1
                else:
                    upd_sql = text(
                        """
                        UPDATE public.portal_view_common
                           SET help_en_text = :en,
                               updated_at = now()
                         WHERE action_xmlid=:ax
                        """
                    )
                    sess.execute(upd_sql, {"en": str(translated), "ax": ax})
                    updated_help += 1

    return {
        "updated": {"ai_purpose": int(updated_purpose), "help": int(updated_help)},
        "skipped": int(skipped),
    }
