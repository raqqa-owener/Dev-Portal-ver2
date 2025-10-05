# app/repos/portal_chroma_doc_repo.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
import json

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.sql import text as SQL

# 型エイリアス
ChromaDocRow = Dict[str, Any]


@dataclass
class QueuedDoc:
    id: int
    doc_id: str
    entity: str
    natural_key: str
    lang: str
    collection: str
    model: Optional[str]
    doc_text: str
    metadata: Dict[str, Any]


class PortalChromaDocRepo:
    def __init__(self, session: Session):
        self.s: Session = session

    # ---------- 内部SQL（doc_id を一切含めない） ----------
    _SQL_SELECT_ONE = SQL(
        """
        SELECT id, source_hash, doc_id
          FROM public.portal_chroma_doc
         WHERE entity=:entity AND natural_key=:nk AND lang=:lang
        """
    )

    _SQL_UPDATE = SQL(
        """
        UPDATE public.portal_chroma_doc
           SET doc_text    = :doc_text,
               meta        = :meta,
               source_hash = :source_hash,
               collection  = :collection,
               model       = :model,
               status      = :status,
               payload     = :payload,
               state       = 'queued',
               last_error  = NULL,
               updated_at  = NOW()
         WHERE entity=:entity AND natural_key=:nk AND lang=:lang
        """
    ).bindparams(
        sa.bindparam("meta", type_=sa.JSON),
        sa.bindparam("payload", type_=sa.JSON),
    )

    _SQL_INSERT = SQL(
        """
        INSERT INTO public.portal_chroma_doc
          (entity, natural_key, lang,
           doc_text, meta, source_hash, collection,
           model, status, payload, state)
        VALUES
          (:entity, :natural_key, :lang,
           :doc_text, :meta, :source_hash, :collection,
           :model, :status, :payload, 'queued')
        """
    ).bindparams(
        sa.bindparam("meta", type_=sa.JSON),
        sa.bindparam("payload", type_=sa.JSON),
    )

    # ---------- Helpers ----------
    @staticmethod
    def _parse_meta(meta_val: Any) -> Dict[str, Any]:
        """meta が文字列なら JSON として解釈。失敗時は {}。"""
        if meta_val is None:
            return {}
        if isinstance(meta_val, dict):
            return meta_val
        if isinstance(meta_val, str):
            try:
                v = json.loads(meta_val)
                return v if isinstance(v, dict) else {}
            except Exception:
                return {}
        return {}

    # ---------- 単件 UPSERT ----------
    def upsert_one(self, r: ChromaDocRow) -> Tuple[bool, Dict[str, Any] | None]:
        for k in ("entity", "natural_key", "lang"):
            if not r.get(k):
                return False, {"reason": f"missing required: {k}"}

        r = dict(r)
        r.pop("doc_id", None)

        r.setdefault("doc_text", "")
        r.setdefault("meta", {})
        r.setdefault("source_hash", None)
        r.setdefault("collection", None)
        r.setdefault("model", None)
        r.setdefault("status", None)
        r.setdefault("payload", {})

        row = (
            self.s.execute(
                self._SQL_SELECT_ONE,
                {"entity": r["entity"], "nk": r["natural_key"], "lang": r["lang"]},
            )
            .mappings()
            .first()
        )

        if row:
            try:
                self.s.execute(
                    self._SQL_UPDATE,
                    {
                        "doc_text": r["doc_text"],
                        "meta": r["meta"],
                        "source_hash": r["source_hash"],
                        "collection": r["collection"],
                        "model": r["model"],
                        "status": r["status"],
                        "payload": r["payload"],
                        "entity": r["entity"],
                        "nk": r["natural_key"],
                        "lang": r["lang"],
                    },
                )
                return True, None
            except Exception as e:
                return False, {"reason": str(e)}

        try:
            self.s.execute(self._SQL_INSERT, r)
            return True, None
        except Exception as e:
            return False, {"reason": str(e)}

    # ---------- 複数 UPSERT ----------
    def bulk_upsert(self, rows: Iterable[ChromaDocRow]) -> Tuple[int, int, List[Dict[str, Any]]]:
        ok = 0
        fails: List[Dict[str, Any]] = []
        for r in rows:
            success, err = self.upsert_one(r)
            if success:
                ok += 1
            else:
                fails.append(
                    {
                        "doc_id": r.get("natural_key"),
                        "collection": r.get("collection"),
                        "model": r.get("model"),
                        "status": "failed",
                        **(err or {}),
                    }
                )
        return ok, len(fails), fails

    # ---------- 一覧（キーセットページング / SQLAlchemy 2.x safe）----------
    def list_keyset(
        self,
        *,
        status: Optional[str] = None,  # 呼び出し互換のため維持（state の意味）
        entity: Optional[str] = None,
        model: Optional[str] = None,
        collection: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[int] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        # テーブル定義（Core）
        t = sa.table(
            "portal_chroma_doc",
            sa.column("id"),
            sa.column("doc_id"),
            sa.column("entity"),
            sa.column("natural_key"),
            sa.column("lang"),
            sa.column("collection"),
            sa.column("doc_text"),
            sa.column("meta"),
            sa.column("state"),
            sa.column("model"),
            sa.column("status"),
            sa.column("payload"),
            sa.column("updated_at"),
        )

        conds = [sa.true()]
        if status:
            conds.append(t.c.state == status)
        if entity:
            conds.append(t.c.entity == entity)
        if model:
            conds.append(t.c.model == model)
        if collection:
            conds.append(t.c.collection == collection)
        if cursor:
            conds.append(t.c.id > cursor)

        stmt = (
            sa.select(
                t.c.id,
                t.c.doc_id,
                t.c.entity,
                t.c.natural_key,
                t.c.lang,
                t.c.collection,
                t.c.doc_text,
                t.c.meta.label("meta"),
                t.c.state,
                t.c.model,
                t.c.status,
                t.c.payload,
                sa.func.to_char(t.c.updated_at, 'YYYY-MM-DD"T"HH24:MI:SSOF').label("updated_at"),
            )
            .where(sa.and_(*conds))
            .order_by(t.c.id.asc())
            .limit(limit)
        )

        rows = self.s.execute(stmt).mappings().all()

        items: List[dict] = []
        last_id: Optional[int] = None
        for r in rows:
            last_id = r["id"]
            meta_val = self._parse_meta(r.get("meta"))
            items.append(
                {
                    "doc_id": r["doc_id"],
                    "entity": r["entity"],
                    "natural_key": r["natural_key"],
                    "lang": r["lang"],
                    "collection": r["collection"],
                    "doc_text": r["doc_text"],
                    "metadata": meta_val,
                    "status": r["state"],
                    "updated_at": r["updated_at"],
                    "model": r["model"],
                    "doc_status": r["status"],
                    "payload": r["payload"] or {},
                }
            )
        next_cursor = last_id if rows and len(rows) == limit else None
        return items, next_cursor

    # ---------- キュー取得（Chroma upsert 用）----------
    def list_queued(self, *, collections: Optional[List[str]] = None, limit: int = 1000) -> List[QueuedDoc]:
        """
        queued を取得。collections が指定されたら IN (...) で絞り込み。
        SQLAlchemy 2.x では ANY(:arr) + ARRAY bind より expanding=True を使う方が安定。
        """
        base = """
            SELECT id, doc_id, entity, natural_key, lang, collection,
                   model, doc_text, meta AS metadata
              FROM public.portal_chroma_doc
             WHERE state='queued' {flt}
             ORDER BY id ASC
             LIMIT :limit
        """
        params: Dict[str, Any] = {"limit": int(limit)}
        if collections:
            sql = sa.text(base.format(flt="AND collection IN :colls")).bindparams(
                sa.bindparam("colls", expanding=True)
            )
            params["colls"] = list(collections)
        else:
            sql = sa.text(base.format(flt=""))

        rows = self.s.execute(sql, params).mappings().all()

        out: List[QueuedDoc] = []
        for r in rows:
            md = r.get("metadata") or {}
            if isinstance(md, str):
                try:
                    md = json.loads(md)
                except Exception:
                    md = {}
            out.append(
                QueuedDoc(
                    id=r["id"],
                    doc_id=r["doc_id"],
                    entity=r["entity"],
                    natural_key=r["natural_key"],
                    lang=r["lang"],
                    collection=r["collection"],
                    model=r.get("model"),
                    doc_text=r.get("doc_text") or "",
                    metadata=md,
                )
            )
        return out

    # 互換エイリアス（/chroma/upsert が fetch_queued を呼ぶケースに対応）
    fetch_queued = list_queued

    # ---------- 状態更新 ----------
    def mark_upserted(self, *, id_: int) -> None:
        self.s.execute(
            SQL(
                """
                UPDATE public.portal_chroma_doc
                   SET state='upserted', last_error=NULL, updated_at=NOW()
                 WHERE id=:id
                """
            ),
            {"id": id_},
        )

    def mark_failed(self, *, id_: int, error: str) -> None:
        self.s.execute(
            SQL(
                """
                UPDATE public.portal_chroma_doc
                   SET state='failed', last_error=:err, updated_at=NOW()
                 WHERE id=:id
                """
            ),
            {"id": id_, "err": error[:2000]},
        )
