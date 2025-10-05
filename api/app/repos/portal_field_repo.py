# portal_fields リポジトリ（Unified：Session/Connection両対応）
# - Session 経路：CRUD/UPSERT/IR取り込みなどフル機能（BaseCoreRepoの機能を利用）
# - Connection 経路：軽量な参照APIのみ（list_by_* / batch_lookup / pick_jp_datatype）
# - 追加点：batch_lookup(), pick_jp_datatype() を統合
from __future__ import annotations
from typing import Optional, Tuple, List, Dict, Any, Iterable
import json
import sqlalchemy as sa
from sqlalchemy import Table, MetaData, select, func, bindparam
from sqlalchemy.orm import Session
from sqlalchemy.engine import Connection   # ★ これを追加
from sqlalchemy.sql.elements import ClauseElement

from app.repos.base_core import BaseCoreRepo
from app.repos.pg_helpers import upsert_one, build_update_assignments
from app.repos.errors import NotFound
from app.utils.normalization import normalize_model_name, merge_label_i18n
from app.utils.audit import log_ttype_change


class PortalFieldRepo(BaseCoreRepo):
    TABLE = "portal_fields"   # ← 実テーブル名（複数形）に統一
    SCHEMA = "public"

    def __init__(self, session_or_conn: Session | Connection):
        if isinstance(session_or_conn, Session):
            super().__init__(session_or_conn)
            self.conn = session_or_conn.connection()
        else:
            tmp_sess = Session(bind=session_or_conn)
            super().__init__(tmp_sess)
            self.conn = session_or_conn

    # ---------- BaseCoreRepo 経路（Session 必須）のAPI ----------
    def list(
        self,
        *,
        model: Optional[str],
        field_name: Optional[str],
        origin: Optional[str],
        limit: int,
        cursor: Optional[str],
    ) -> Tuple[List[dict], Optional[str]]:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("... requires Session-backed construction")
        eq = {}
        if model:
            eq["model"] = normalize_model_name(model)
        if field_name:
            eq["field_name"] = field_name
        if origin:
            eq["origin"] = origin
        return self.list_keyset(limit=limit, cursor=cursor, eq_filters=eq)

    def create_field(self, values: Dict[str, Any]) -> dict:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("... requires Session-backed construction")

        vals = dict(values)
        if "model" in vals:
            vals["model"] = normalize_model_name(vals["model"])
        return self.create(vals)

    def patch_field(self, id: int, values: Dict[str, Any]) -> dict:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("... requires Session-backed construction")

        if "model" in values:
            values = dict(values)
            values["model"] = normalize_model_name(values["model"])
        set_map, params = build_update_assignments(self.t, values, jsonb_cols=["label_i18n"])  # type: ignore[arg-type]
        return self.update_by_id(id, set_map, params)

    def get_by_model_and_field(self, *, model: str, field_name: str) -> dict:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("... requires Session-backed construction")

        model_n = normalize_model_name(model)
        row = (
            self.sess.execute(
                select(self.t).where((self.t.c.model == model_n) & (self.t.c.field_name == field_name))  # type: ignore[attr-defined]
            )
            .mappings()
            .first()
        )
        if not row:
            raise NotFound(f"portal_fields model={model_n} field={field_name} not found")
        return dict(row)

    def upsert(self, values: Dict[str, Any]) -> dict:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("... requires Session-backed construction")

        vals = dict(values)
        if "model" in vals:
            vals["model"] = normalize_model_name(vals["model"])

        # 日本語派生列の同期（UI/運用向けの補助列）
        if "model" in vals:
            vals["モデル技術名"] = vals["model"]
        if "model_table" in vals:
            vals["モデル物理名"] = vals["model_table"]
        if "field_name" in vals:
            vals["フィールド技術名"] = vals["field_name"]
        if "ttype" in vals and vals["ttype"] is not None:
    # ClauseElement が入らないよう **必ず** 文字列に正規化
            try:
                jp = self.pick_jp_datatype(str(vals["ttype"]))
                if jp:
                    vals["データ型"] = jp
            except Exception:
                # フォールバック：テーブル default に任せる（キーごと削除）
                vals.pop("データ型", None)

        # 念のため、外部から渡された値に ClauseElement が紛れていれば除去
        for k, v in list(vals.items()):
            if isinstance(v, ClauseElement):
                # ここで bool(v) されると例外になるため、使わない or 文字列化
                if k == "データ型" and "ttype" in vals:
                    # 上の pick_jp_datatype で置換済が基本。保険で外す。
                    vals.pop(k, None)
                else:
                    # 安全側に倒して JSON 化できる文字列へ
                    vals[k] = str(v)


        row = upsert_one(
            self.sess,
            table=self.t,  # type: ignore[arg-type]
            values=vals,
            conflict_cols=["model", "field_name"],
            returning=[
                self.t.c.id,  # type: ignore[attr-defined]
                self.t.c.model,
                self.t.c.model_table,
                self.t.c.field_name,
                self.t.c.ttype,
                self.t.c.label_i18n,
                self.t.c.notes,
                self.t.c.origin,
                self.t.c.created_at,
                self.t.c.updated_at,
            ],
        )
        return dict(row)

    def bulk_upsert_from_ir(
        self,
        *,
        model: str,
        ir_rows: List[Dict[str, Any]],
        only_fields: Optional[List[str]] = None,
        actor: Optional[str] = None,
    ) -> Dict[str, int]:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("... requires Session-backed construction")


        model_n = normalize_model_name(model)
        picked = inserted = updated = ttype_changed = skipped = 0

        fields_set = set(only_fields or [])
        for r in ir_rows:
            if r.get("model") and normalize_model_name(r.get("model")) != model_n:
                continue
            if fields_set and r.get("field_name") not in fields_set:
                continue
            picked += 1

            # 既存の ttype を確認
            existing = self.sess.execute(
                select(self.t.c.id, self.t.c.ttype).where(
                    (self.t.c.model == model_n) & (self.t.c.field_name == r["field_name"])
                )
            ).first()

            label_i18n = merge_label_i18n(r.get("label_i18n"), r.get("label_ja_jp"), r.get("label_en_us"))
            vals = {
                "model": model_n,
                "model_table": r.get("model_table"),
                "field_name": r.get("field_name"),
                "ttype": r.get("ttype"),
                "label_i18n": label_i18n,
                "notes": r.get("notes"),
                "origin": r.get("origin") or "ir",
            }
            # null は無視（None は既存値保持）
            vals = {k: v for k, v in vals.items() if v is not None}
            for k, v in list(vals.items()):
                if isinstance(v, ClauseElement):
                    vals[k] = str(v)

            if existing:
                if vals.get("ttype") and existing.ttype and existing.ttype != vals["ttype"]:
                    log_ttype_change(
                        model=model_n,
                        field_name=r["field_name"],
                        old_ttype=str(existing.ttype),
                        new_ttype=str(vals["ttype"]),
                        actor=actor,
                    )
                    ttype_changed += 1
                self.upsert(vals)
                updated += 1
            else:
                self.upsert(vals)
                inserted += 1

        return {
            "picked": picked,
            "inserted": inserted,
            "updated": updated,
            "ttype_changed": ttype_changed,
            "skipped": skipped,
        }

    # ---------- 軽量クエリ（Connection 経路でも使用可） ----------
    def list_by_models(self, models: Iterable[str]) -> List[Dict[str, Any]]:
        models = [m.strip().lower() for m in models]
        if not models:
            return []
        sql = sa.text(
            """
            SELECT id, model, model_table, field_name, ttype, label_i18n, notes
              FROM public.portal_fields
             WHERE lower(model) IN :models
             ORDER BY model, field_name
            """
        ).bindparams(bindparam("models", expanding=True))
        return list(self.conn.execute(sql, {"models": models}).mappings())

    def list_by_field_names(self, field_names: Iterable[str]) -> List[Dict[str, Any]]:
        fns = [f.strip().lower() for f in field_names]
        if not fns:
            return []
        sql = sa.text(
            """
            SELECT id, model, model_table, field_name, ttype, label_i18n, notes
              FROM public.portal_fields
             WHERE lower(field_name) IN :fns
             ORDER BY model, field_name
            """
        ).bindparams(bindparam("fns", expanding=True))
        return list(self.conn.execute(sql, {"fns": fns}).mappings())

    def list_by_models_and_field_names(self, models: Iterable[str], field_names: Iterable[str]) -> List[Dict[str, Any]]:
        models = [m.strip().lower() for m in models]
        fns = [f.strip().lower() for f in field_names]
        if not models or not fns:
            return []
        sql = sa.text(
            """
            SELECT id, model, model_table, field_name, ttype, label_i18n, notes
              FROM public.portal_fields
             WHERE lower(model) IN :models
               AND lower(field_name) IN :fns
             ORDER BY model, field_name
            """
        ).bindparams(
            bindparam("models", expanding=True),
            bindparam("fns", expanding=True),
        )
        return list(self.conn.execute(sql, {"models": models, "fns": fns}).mappings())

    # ---------- 追加：パッケージ生成などで使う補助関数 ----------
    def batch_lookup(self, pairs: Iterable[tuple[str, str]]) -> Dict[tuple[str, str], dict]:
        """
        (model, field_name) をキーに portal_fields の必要メタをまとめて取得。
        - lower 比較で大小文字ゆれを吸収
        - 戻り値は {(model, field_name): row_dict}
        """
        pairs = list(pairs)
        if not pairs:
            return {}
        models = [m for m, _ in pairs]
        fields = [f for _, f in pairs]
        sql = sa.text(
            """
            SELECT model, model_table, field_name, ttype, label_i18n, notes,
                   "データ型" AS jp_datatype,
                   to_char(updated_at, 'YYYY-MM-DD"T"HH24:MI:SSOF') AS updated_at
              FROM public.portal_fields
             WHERE lower(model) IN :models
               AND lower(field_name) IN :fields
            """
        ).bindparams(
            bindparam("models", expanding=True),
            bindparam("fields", expanding=True),
        )
        rows = self.conn.execute(
            sql, {"models": [m.lower() for m in models], "fields": [f.lower() for f in fields]}
        ).mappings().all()
        out: Dict[tuple[str, str], dict] = {}
        for r in rows:
            rec = dict(r)
            li = rec.get("label_i18n")
            if isinstance(li, str):
                try:
                    rec["label_i18n"] = json.loads(li)
                except Exception:
                    rec["label_i18n"] = {}
            # ★ キーを小文字・trimで正規化して格納
            k_model = (rec["model"] or "").strip().lower()
            k_field = (rec["field_name"] or "").strip().lower()
            out[(k_model, k_field)] = rec
        return out           

    def pick_jp_datatype(self, ttype: str) -> str:
        """
        ttype から日本語表示名を返す（DB関数 public._pick_jp_datatype_label を利用）。
        関数が未定義でも '文字列' にフォールバック。
        """
        try:
            return (
                self.conn.execute(
                    sa.text("SELECT public._pick_jp_datatype_label(:t)"),
                    {"t": ttype},
                ).scalar()
                or "文字列"
            )
        except Exception:
            return "文字列"
