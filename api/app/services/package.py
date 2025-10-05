# api/app/services/package.py
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.utils.text_hash import sha256_text

# ロガー
logger = logging.getLogger(__name__)

# Eフェーズの正規化ユーティリティを再利用（存在しない環境でもフォールバック）
try:
    from app.utils.html_strip import html_to_text as _html_to_text
except Exception:  # pragma: no cover
    try:
        from app.utils.html_strip import strip_html as _html_to_text
    except Exception:  # さらに無ければ超簡易版
        def _html_to_text(s: str) -> str:
            import re
            return re.sub(r"<[^>]+>", " ", s or "")

try:
    from app.utils.normalization import normalize_whitespace as _norm_ws
except Exception:
    def _norm_ws(s: str) -> str:
        return " ".join((s or "").split())

try:
    from app.utils.normalization import normalize_newlines as _norm_nl
except Exception:
    def _norm_nl(s: str, max_consecutive: int = 2) -> str:
        import re
        s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
        s = re.sub(r"\n{3,}", "\n" * max_consecutive, s)
        return s.strip()

from app.repos.portal_translate_repo import PortalTranslateRepo
from app.repos.portal_field_repo import PortalFieldRepo
from app.repos.portal_view_common_repo import PortalViewCommonRepo
from app.repos.portal_chroma_doc_repo import PortalChromaDocRepo
from app.services.package_templates import (
    render_field_doc,
    render_view_common_doc,
)

ALLOWED_ENTITIES = ("field", "view_common")
ALLOWED_VC_TARGETS = {"ai_purpose", "help"}


class PackService:
    """
    フェーズG: translated → portal_chroma_doc（queued）へのパッケージング。
    - view_common の NK は必ず 'view_common::<action_xmlid>::<target>' で再構成して保存
    - repo.upsert() に doc_id / 未知カラム（model/status/payload）は渡さない
    - meta は dict のまま（JSONB バインド）
    """

    def __init__(self, session: Session):
        self.s = session
        self.cfg = get_settings()
        self.trans_repo = PortalTranslateRepo(session)
        self.field_repo = PortalFieldRepo(session)
        self.vc_repo = PortalViewCommonRepo(session)
        self.doc_repo = PortalChromaDocRepo(session)

    # ===== 内部ユーティリティ =====

    def _text_limit(self) -> int:
        return int(self.cfg.PACK_TEXT_LIMIT)

    def _truncate(self, s: str) -> str:
        data = (s or "").encode("utf-8")
        if len(data) <= self._text_limit():
            return s or ""
        clipped = data[: self._text_limit() - 3]
        # マルチバイト途中切りを回避
        while clipped and (clipped[-1] & 0xC0) == 0x80:
            clipped = clipped[:-1]
        return clipped.decode("utf-8", errors="ignore") + "…"

    def _norm_label(self, s: Optional[str]) -> str:
        return _norm_ws(_norm_nl(s or "", 2))

    def _norm_help(self, s: Optional[str]) -> str:
        return _norm_nl(_norm_ws(_html_to_text(s or "")), 2)

    # ===== メイン処理 =====

    def pack(
        self,
        *,
        entities: Sequence[str],
        lang: str,
        collections: Dict[str, str],
        limit: int,
    ) -> Dict[str, Any]:
        ents = [e for e in entities if e in ALLOWED_ENTITIES] or list(ALLOWED_ENTITIES)
        rows = self.trans_repo.list_translated_for_pack(entities=ents, limit=limit)

        queued = 0
        skipped_no_change = 0
        failed = 0
        samples: List[Dict[str, Any]] = []
        ready_nks: List[str] = []

        # ===== 1) 参照キー収集 =====
        field_pairs: List[Tuple[str, str]] = []
        vc_keys: List[str] = []

        for r in rows:
            if r["entity"] == "field":
                try:
                    _, model, field_name = r["natural_key"].split("::", 2)
                    field_pairs.append((model, field_name))
                except Exception:
                    logger.warning("package skip(field): reason=invalid_natural_key nk=%s", r.get("natural_key"))
            elif r["entity"] == "view_common":
                try:
                    _, action_xmlid, target = r["natural_key"].split("::", 2)
                    if target not in ALLOWED_VC_TARGETS:
                        logger.warning("package skip(view_common): reason=invalid_target nk=%s target=%s", r.get("natural_key"), target)
                        continue
                    vc_keys.append(action_xmlid)
                except Exception:
                    logger.warning("package skip(view_common): reason=invalid_natural_key nk=%s", r.get("natural_key"))

        # ===== 2) メタ取得 + 正規化インデックス化 =====
        #   - field: (model, field_name) → メタ
        #   - view_common: action_xmlid → メタ
        field_map_raw = self.field_repo.batch_lookup_by_model_and_fields(field_pairs)
        field_map = {((k[0] or "").strip().lower(), (k[1] or "").strip().lower()): v for k, v in field_map_raw.items()}

        vc_map_raw = self.vc_repo.batch_lookup_by_action_xmlids(vc_keys)
        vc_map = {(k or "").strip().lower(): v for k, v in vc_map_raw.items()}

        # 既定コレクション
        default_field_coll = collections.get("field", self.cfg.DEFAULT_COLLECTION_FIELD)
        default_vc_coll = collections.get("view_common", self.cfg.DEFAULT_COLLECTION_VIEW_COMMON)

        # ===== 3) 本体ループ =====
        for r in rows:
            entity = r["entity"]
            src_nk = r["natural_key"]

            try:
                if entity == "field":
                    # ---- field ----
                    try:
                        _, model, field_name = src_nk.split("::", 2)
                    except Exception:
                        failed += 1
                        logger.warning("package failed(field): reason=invalid_natural_key nk=%s", src_nk)
                        if len(samples) < self.cfg.PACK_SAMPLES_MAX:
                            samples.append({"doc_id": "", "collection": default_field_coll, "model": None, "status": "failed"})
                        continue

                    k_model = (model or "").strip().lower()
                    k_field = (field_name or "").strip().lower()
                    meta_src = field_map.get((k_model, k_field))
                    if not meta_src:
                        failed += 1
                        logger.warning(
                            "package failed(field): reason=field_meta_not_found nk=%s model=%s field=%s",
                            src_nk, model, field_name
                        )
                        if len(samples) < self.cfg.PACK_SAMPLES_MAX:
                            samples.append({"doc_id": "", "collection": default_field_coll, "model": model, "status": "failed"})
                        continue

                    label_ja = (meta_src.get("label_i18n") or {}).get("ja") or ""
                    notes_ja = meta_src.get("notes") or ""
                    ttype = meta_src.get("ttype") or "char"
                    jp_dt = meta_src.get("jp_datatype") or "" or self.field_repo.pick_jp_datatype(ttype)

                    label_ja_n = self._norm_label(label_ja)
                    notes_ja_n = self._norm_help(notes_ja)
                    src_hash = sha256_text(f"{label_ja_n}\n\n{notes_ja_n}")

                    doc_text = render_field_doc(
                        label_ja=label_ja_n,
                        model=model,
                        field_name=field_name,
                        model_table=meta_src.get("model_table") or "",
                        ttype=ttype,
                        jp_datatype=jp_dt,
                        notes_ja=notes_ja_n,
                    )
                    doc_text = self._truncate(doc_text)

                    meta: Dict[str, Any] = {
                        "entity": "field",
                        "natural_key": src_nk,
                        "lang": lang,
                        "model": model,
                        "model_table": meta_src.get("model_table"),
                        "field_name": field_name,
                        "ttype": ttype,
                        "collection": default_field_coll,
                        "label_ja": label_ja_n,
                        "notes_ja": notes_ja_n,
                        "source_row_updated_at": meta_src.get("updated_at"),
                    }

                    result, doc_id = self.doc_repo.upsert(
                        entity="field",
                        natural_key=src_nk,
                        lang=lang,
                        doc_text=doc_text,
                        meta=meta,
                        source_hash=src_hash,
                        collection=default_field_coll,
                    )

                    if result == "skipped_no_change":
                        skipped_no_change += 1
                    else:
                        queued += 1
                        ready_nks.append(src_nk)
                        if len(samples) < self.cfg.PACK_SAMPLES_MAX:
                            samples.append({"doc_id": doc_id, "collection": default_field_coll, "model": model, "status": "queued"})

                elif entity == "view_common":
                    # ---- view_common ----
                    try:
                        _, action_xmlid, target = src_nk.split("::", 2)
                    except Exception:
                        failed += 1
                        logger.warning("package failed(view_common): reason=invalid_natural_key nk=%s", src_nk)
                        if len(samples) < self.cfg.PACK_SAMPLES_MAX:
                            samples.append({"doc_id": "", "collection": default_vc_coll, "model": None, "status": "failed"})
                        continue

                    if target not in ALLOWED_VC_TARGETS:
                        failed += 1
                        logger.warning("package failed(view_common): reason=invalid_target nk=%s target=%s", src_nk, target)
                        if len(samples) < self.cfg.PACK_SAMPLES_MAX:
                            samples.append({"doc_id": "", "collection": default_vc_coll, "model": None, "status": "failed"})
                        continue

                    # ※ NK を必ず再構成（NULL/空を防ぐ）
                    nk_view = f"view_common::{action_xmlid}::{target}"

                    k_action = (action_xmlid or "").strip().lower()
                    vc = vc_map.get(k_action)
                    if not vc:
                        failed += 1
                        logger.warning("package failed(view_common): reason=view_common_not_found nk=%s action_xmlid=%s", nk_view, action_xmlid)
                        if len(samples) < self.cfg.PACK_SAMPLES_MAX:
                            samples.append({"doc_id": "", "collection": default_vc_coll, "model": None, "status": "failed"})
                        continue

                    ai_purpose_ja_n = self._norm_label(vc.get("ai_purpose") or "")
                    help_ja_text_n = self._norm_help(vc.get("help_ja_text") or "")
                    src_hash = sha256_text(f"{ai_purpose_ja_n}\n\n{help_ja_text_n}")

                    action_display = vc.get("action_name") or action_xmlid
                    doc_text = render_view_common_doc(
                        action_display=action_display,
                        ai_purpose_ja=ai_purpose_ja_n,
                        help_ja_text=help_ja_text_n,
                        model_tech=vc.get("model_tech") or "",
                        model_table=vc.get("model_table") or "",
                        primary_view_type=vc.get("primary_view_type"),
                    )
                    doc_text = self._truncate(doc_text)

                    meta = {
                        "entity": "view_common",
                        "natural_key": nk_view,
                        "lang": lang,
                        "action_xmlid": action_xmlid,
                        "model_tech": vc.get("model_tech"),
                        "model_table": vc.get("model_table"),
                        "primary_view_type": vc.get("primary_view_type"),
                        "collection": default_vc_coll,
                        "ai_purpose_ja": ai_purpose_ja_n,
                        "help_ja_text": help_ja_text_n,
                        "view_types": vc.get("view_types"),
                        "common_id": vc.get("common_id"),
                        "source_row_updated_at": vc.get("updated_at"),
                        "target": target,
                    }

                    result, doc_id = self.doc_repo.upsert(
                        entity="view_common",
                        natural_key=nk_view,          # ★ 再構成した NK を保存
                        lang=lang,
                        doc_text=doc_text,
                        meta=meta,
                        source_hash=src_hash,
                        collection=default_vc_coll,
                    )

                    if result == "skipped_no_change":
                        skipped_no_change += 1
                    else:
                        queued += 1
                        ready_nks.append(nk_view)
                        if len(samples) < self.cfg.PACK_SAMPLES_MAX:
                            samples.append({"doc_id": doc_id, "collection": default_vc_coll, "model": vc.get("model_tech"), "status": "queued"})

                else:
                    # 想定外 entity はスキップ
                    logger.warning("package skip: reason=unsupported_entity entity=%s nk=%s", entity, src_nk)
                    continue

            except Exception as ex:
                # 1件失敗しても全体は続行（部分成功許容）
                failed += 1
                logger.exception("package failed: nk=%s entity=%s err=%s", src_nk, entity, ex)
                try:
                    self.s.rollback()
                except Exception:
                    pass
                # サンプルは entity に応じたコレクションの既定値にする
                coll_for_sample = default_field_coll if entity == "field" else default_vc_coll
                if len(samples) < self.cfg.PACK_SAMPLES_MAX:
                    samples.append({"doc_id": "", "collection": coll_for_sample, "model": None, "status": "failed"})

        # ここまで成功分のみ ready_for_chroma へ
        try:
            if ready_nks:
                self.trans_repo.mark_ready_for_chroma(natural_keys=ready_nks)
        except Exception as e:
            logger.warning("mark_ready_for_chroma skipped: %s", e)

        return {
            "queued": queued,
            "skipped_no_change": skipped_no_change,
            "failed": failed,
            "samples": samples,
        }
