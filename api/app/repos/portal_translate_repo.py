# portal_translate の読み書き用リポジトリ（Sessionベースに統一）
# - upsert_source(): (entity,natural_key,src_lang,tgt_lang) で source をUPSERT
#   * 既存かつ source_hash 同一 → 'skipped_no_change'
#   * 既存かつ source_hash 変更 → UPDATE + state='pending'
# - pick_pending(): 翻訳待ちを id ASC で取得
# - mark_translated()/mark_failed(): 状態遷移（RETURNING付き）
# - list_translated_for_pack(): フェーズGのパッケージ対象取得（state='translated'）
# - mark_ready_for_chroma(): 成功分だけ ready_for_chroma へ遷移

from __future__ import annotations
from typing import List, Dict, Any, Sequence, Literal, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

State = Literal["pending", "translated", "ready_for_chroma", "done", "failed"]

class PortalTranslateRepo:
    def __init__(self, session: Session):
        self.s = session

    # 020_portal_translate.sql に準拠：unique(entity,natural_key,src_lang,tgt_lang)
    def upsert_source(
        self,
        *,
        entity: str,
        natural_key: str,
        src_lang: str,
        tgt_lang: str,
        source_text: str,
        source_hash: str,
        mode: str = "upsert_if_changed",  # | 'skip_existing'
    ) -> str:
        """
        Returns: 'inserted' | 'updated' | 'skipped_no_change' | 'skipped_existing'
        """
        row = self.s.execute(
            text(
                """
                SELECT id, source_hash
                  FROM public.portal_translate
                 WHERE entity=:entity AND natural_key=:nk
                   AND src_lang=:sl AND tgt_lang=:tl
                """
            ),
            {"entity": entity, "nk": natural_key, "sl": src_lang, "tl": tgt_lang},
        ).mappings().first()

        if row is None:
            self.s.execute(
                text(
                    """
                    INSERT INTO public.portal_translate
                      (entity, natural_key, src_lang, tgt_lang, source_text, translated_text, source_hash, state, last_error)
                    VALUES
                      (:entity, :nk, :sl, :tl, :st, NULL, :sh, 'pending', NULL)
                    """
                ),
                {"entity": entity, "nk": natural_key, "sl": src_lang, "tl": tgt_lang, "st": source_text, "sh": source_hash},
            )
            return "inserted"

        if mode == "skip_existing":
            return "skipped_existing"

        if row["source_hash"] == source_hash:
            return "skipped_no_change"

        self.s.execute(
            text(
                """
                UPDATE public.portal_translate
                   SET source_text=:st,
                       source_hash=:sh,
                       translated_text=NULL,
                       state='pending',
                       last_error=NULL,
                       updated_at=now()
                 WHERE entity=:entity AND natural_key=:nk
                   AND src_lang=:sl AND tgt_lang=:tl
                """
            ),
            {"entity": entity, "nk": natural_key, "sl": src_lang, "tl": tgt_lang, "st": source_text, "sh": source_hash},
        )
        return "updated"

    def pick_pending(self, *, limit: int) -> List[dict]:
        rows = self.s.execute(
            text(
                """
                SELECT id, entity, natural_key, src_lang, tgt_lang, source_text, source_hash
                  FROM public.portal_translate
                 WHERE state='pending'
                 ORDER BY id ASC
                 LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
        return [dict(r) for r in rows]

    def mark_translated(self, id: int, translated_text: str) -> dict:
        row = self.s.execute(
            text(
                """
                UPDATE public.portal_translate
                   SET translated_text=:tt,
                       state='translated',
                       last_error=NULL,
                       updated_at=now()
                 WHERE id=:id
                RETURNING id, entity, natural_key, state
                """
            ),
            {"id": id, "tt": translated_text},
        ).mappings().one()
        return dict(row)

    def mark_failed(self, id: int, last_error: str) -> dict:
        row = self.s.execute(
            text(
                """
                UPDATE public.portal_translate
                   SET last_error=substring(:err from 1 for 500),
                       state='failed',
                       updated_at=now()
                 WHERE id=:id
                RETURNING id, entity, natural_key, state, last_error
                """
            ),
            {"id": id, "err": last_error},
        ).mappings().one()
        return dict(row)

    # === フェーズG で使用 ===
    def list_translated_for_pack(self, *, entities: Sequence[str], limit: int) -> List[dict]:
        rows = self.s.execute(
            text(
                """
                SELECT id, entity, natural_key, src_lang, tgt_lang, source_text, translated_text, model
                  FROM public.portal_translate
                 WHERE state = 'translated'
                   AND entity = ANY(:entities)
                 ORDER BY id ASC
                 LIMIT :limit
                """
            ),
            {"entities": list(entities), "limit": limit},
        ).mappings().all()
        return [dict(r) for r in rows]

    def mark_ready_for_chroma(self, *, natural_keys: Sequence[str]) -> int:
        if not natural_keys:
            return 0
        sql = text(
            """
            UPDATE public.portal_translate
            SET updated_at = now(), last_error = NULL
            WHERE natural_key = ANY(:nks)
            AND state = 'translated'
            """
        )
        res = self.s.execute(sql, {"nks": list(natural_keys)})
        return res.rowcount or 0