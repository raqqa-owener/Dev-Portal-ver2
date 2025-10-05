# api/app/services/chroma_upsert.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import json
import logging

from sqlalchemy.orm import Session

from ..config import settings
from ..db import session_scope

# Repo / Row 型の互換
try:
    from ..repos.portal_chroma_doc_repo import PortalChromaDocRepo, QueuedDoc  # type: ignore
except Exception:
    from ..repos.portal_chroma_doc_repo import PortalChromaDocRepo, ChromaDocRow as QueuedDoc  # type: ignore

from .chroma_client import get_chroma_client, ensure_collection, embed_and_upsert

log = logging.getLogger(__name__)

# 16 KiB safety limit for Chroma documents (UTF-8 safe truncation)
MAX_DOC_BYTES = 16 * 1024


def _safe_truncate_utf8(text: str, max_bytes: int = MAX_DOC_BYTES) -> str:
    """UTF-8 セーフにバイト長で丸める。"""
    if not text:
        return ""
    b = text.encode("utf-8", errors="ignore")
    if len(b) <= max_bytes:
        return text
    b = b[:max_bytes]
    return b.decode("utf-8", errors="ignore")


def _sanitize_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chroma が受け付けるメタデータは {str: (str|int|float|bool)} のみ。
    list/tuple/dict/その他は安全に文字列化する。
    - list/tuple が全スカラならカンマ連結、それ以外は JSON 文字列化
    - dict は JSON 文字列化
    - 文字列は最大 8KB までに丸める（UTF-8 セーフ）
    """
    out: Dict[str, Any] = {}
    for k, v in (meta or {}).items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            val = v
        elif isinstance(v, (list, tuple)):
            if all((x is None) or isinstance(x, (str, int, float, bool)) for x in v):
                val = ",".join(str(x) for x in v if x is not None)
            else:
                val = json.dumps(v, ensure_ascii=False)
        elif isinstance(v, dict):
            val = json.dumps(v, ensure_ascii=False)
        else:
            val = str(v)

        if isinstance(val, str):
            b = val.encode("utf-8", errors="ignore")
            if len(b) > 8192:
                val = b[:8192].decode("utf-8", errors="ignore")

        out[str(k)] = val
    return out


def _choose_document_id(doc_id: Optional[str], natural_key: Optional[str], lang: str) -> str:
    """
    Chroma の document.id 決定規則（idempotent）:
      - 基本は doc_id 優先、なければ natural_key を使う
      - '::' を含む ID（entity::key 形式）は言語でユニーク化するため '::<lang>' を付与
    """
    base = (doc_id or "").strip() or (natural_key or "").strip()
    if not base:
        return ""
    return f"{base}::{lang}" if "::" in base else base


def _group_by_collection(rows: List[QueuedDoc]) -> Dict[str, List[QueuedDoc]]:
    buckets: Dict[str, List[QueuedDoc]] = {}
    for r in rows:
        buckets.setdefault(r.collection, []).append(r)
    return buckets


class ChromaUpsertService:
    """
    portal_chroma_doc.state='queued' を対象に、埋め込み→Chroma upsert→状態遷移。
    - dry_run: 変更なし
    - 実行: 成功は upserted、失敗は failed + error
    - レスポンスは Pydantic モデル（errors[*] は {doc_id, reason} のみ）に準拠
    - 状態更新は 1件ずつ行い、例外時は rollback→継続、commit は都度実行
    """

    def __init__(self, session: Session):
        self.s = session
        self.repo = PortalChromaDocRepo(session)
        self.client = get_chroma_client()

    # ---- 低リスクの commit/rollback ----
    def _commit_quiet(self) -> None:
        try:
            self.s.commit()
        except Exception:
            log.exception("[chroma-upsert] commit failed")

    def _rollback_quiet(self) -> None:
        try:
            self.s.rollback()
        except Exception:
            # ここで失敗しても続行する
            pass

    def run(
        self,
        *,
        collections: Optional[List[str]] = None,
        limit: int = 1000,
        dry_run: bool = False,
    ) -> Dict:
        # 1) 対象取得（queued のみ、id ASC）
        rows = self.repo.list_queued(collections=collections, limit=limit)
        processed = len(rows)
        if processed == 0:
            return {"processed": 0, "upserted": 0, "skipped": 0, "failed": 0, "errors": []}

        if dry_run:
            log.info("[chroma-upsert] dry_run only: processed=%d", processed)
            # dry_run は件数だけ返す（skipped に積む）
            return {"processed": processed, "upserted": 0, "skipped": processed, "failed": 0, "errors": []}

        upserted = 0
        failed = 0
        skipped = 0
        # Pydantic に合わせ、errors[*] は {doc_id, reason} のみ許可
        errors: List[Dict[str, str]] = []

        # 2) コレクション単位で upsert
        by_col = _group_by_collection(rows)
        batch_size = int(settings.EMBED_BATCH_SIZE or 64)
        timeout_s = int(settings.CHROMA_TIMEOUT_S or 10)

        for coll_name, docs in by_col.items():
            log.info("[chroma-upsert] collection=%s, queued=%d", coll_name, len(docs))
            collection = ensure_collection(self.client, coll_name)

            # Chroma upsert 用バッチ
            items: List[Tuple[str, str, Dict]] = []
            id_to_rowid: Dict[str, int] = {}

            for d in docs:
                cid = _choose_document_id(getattr(d, "doc_id", None), getattr(d, "natural_key", None), d.lang)
                if not cid:
                    skipped += 1
                    continue
                txt = _safe_truncate_utf8(getattr(d, "doc_text", None) or "", MAX_DOC_BYTES)
                raw_meta = getattr(d, "metadata", None) or {}
                meta = _sanitize_metadata(raw_meta)
                items.append((cid, txt, meta))
                id_to_rowid[cid] = d.id

            if not items:
                continue

            # 3) 埋め込み＋upsert（失敗時はコレクション全体を failed として扱う）
            errs_from_batch: List[Dict[str, str]] = []
            try:
                ucount, fcount, errs = embed_and_upsert(
                    collection,
                    items,
                    batch_size=batch_size,
                    timeout_s=timeout_s,
                    dry_run=False,
                )
                upserted += int(ucount or 0)
                failed += int(fcount or 0)
                # 正規化（{doc_id, reason} のみ）
                for e in errs or []:
                    doc_id = (e.get("doc_id") if isinstance(e, dict) else None) or ""
                    reason = ""
                    if isinstance(e, dict):
                        reason = e.get("reason") or e.get("error") or "upsert failed"
                    else:
                        reason = str(e)
                    errs_from_batch.append({"doc_id": doc_id, "reason": reason[:400]})
            except Exception as ex:
                msg = f"embed_and_upsert failed: {str(ex)}"
                log.exception("[chroma-upsert] %s", msg)
                for (cid, _txt, _meta) in items:
                    errs_from_batch.append({"doc_id": cid, "reason": msg[:400]})
                failed += len(items)

            # 4) 状態遷移（1件ずつ、例外時は rollback のうえ継続）
            failed_ids = {e["doc_id"] for e in errs_from_batch if e.get("doc_id")}
            reason_by_id = {e["doc_id"]: e["reason"] for e in errs_from_batch if e.get("doc_id")}

            for (cid, _txt, _meta) in items:
                rid = id_to_rowid.get(cid)
                if rid is None:
                    continue

                if cid in failed_ids:
                    # 失敗状態へ
                    try:
                        self.repo.mark_failed(id_=rid, error=reason_by_id.get(cid, "upsert failed"))
                        self._commit_quiet()
                    except Exception as ex2:
                        self._rollback_quiet()
                        log.exception("[chroma-upsert] mark_failed error id=%s: %s", rid, ex2)
                        # ここでさらに errors を積む（doc_id, reason のみ）
                        errors.append({"doc_id": cid, "reason": f"mark_failed exception: {str(ex2)[:300]}"})
                else:
                    # 成功状態へ
                    try:
                        self.repo.mark_upserted(id_=rid)
                        self._commit_quiet()
                    except Exception as ex2:
                        # 状態更新に失敗した場合は failed に倒し、カウンタも補正
                        self._rollback_quiet()
                        try:
                            self.repo.mark_failed(id_=rid, error=f"post-upsert state update failed: {ex2}")
                            self._commit_quiet()
                        except Exception:
                            self._rollback_quiet()
                            log.exception("[chroma-upsert] mark_failed fallback error id=%s", rid)
                        failed += 1
                        # エラー配列へ（doc_id, reason のみ）
                        errors.append(
                            {"doc_id": cid, "reason": f"post-upsert state update failed: {str(ex2)[:300]}"}
                        )

            # バッチ単位のエラーを最後にまとめて追加
            errors.extend(errs_from_batch)

        # 集計整合（下限ゼロ保証）
        upserted = max(0, int(upserted))
        failed = max(0, int(failed))
        skipped = max(0, int(skipped))

        return {
            "processed": processed,
            "upserted": upserted,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,  # ← {doc_id, reason} のみ
        }


def run_chroma_upsert(*, collections: Optional[List[str]], limit: int, dry_run: bool) -> Dict:
    with session_scope() as s:
        svc = ChromaUpsertService(s)
        return svc.run(collections=collections, limit=limit, dry_run=dry_run)
