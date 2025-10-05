# app/services/portal_import.py
from __future__ import annotations
from sqlalchemy.dialects.postgresql import JSONB
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Sequence

from sqlalchemy import text, bindparam
from sqlalchemy.engine import Result
from sqlalchemy.orm import Session
from app.repos.portal_field_repo import PortalFieldRepo
from app.repos.portal_view_common_repo import PortalViewCommonRepo

log = logging.getLogger(__name__)

__all__ = [
    "PortalImportService",
    "import_models",          # legacy-compatible wrapper
    "import_fields",          # legacy-compatible stub (no-op)
    "import_view_common",     # legacy-compatible stub (no-op)
]

# 新規作成のクエリを事前に用意（label_i18n を JSONB としてバインド）
sql_ins = text("""
    INSERT INTO public.portal_model (model, model_table, label_i18n)
    VALUES (:model, :model_table, :label_i18n)
""").bindparams(bindparam("label_i18n", type_=JSONB))

# 上書き更新のクエリも同様に
sql_upd = text("""
    UPDATE public.portal_model
       SET model_table = :model_table,
           label_i18n = :label_i18n,
           updated_at = now()
     WHERE model = :model
""").bindparams(bindparam("label_i18n", type_=JSONB))

# -------------------------------
# ヘルパ：安全な i18n 正規化
# -------------------------------
def _normalize_label_i18n(value: Any, *, default_ja: str = "", prefer_key: str = "en_US") -> Dict[str, Any]:
    """
    ir_model_src.label_en_us 由来の値を JSONB 相当(dict) に正規化する。
    - dict の場合: そのまま返す
    - JSON 文字列の場合: 1〜2回まで json.loads を試し、dict なら採用
    - 素の文字列の場合: {"en_US": <value>, "ja_JP": ""} を生成
    - None/空の場合: {"ja_JP": default_ja, "en_US": ""}

    prefer_key は、素の文字列のときに入れる既定キー。
    """
    if value is None:
        return {"ja_JP": default_ja, "en_US": ""}

    if isinstance(value, dict):
        return value

    # 文字列: JSONの二重エンコードにも対応（最大2回）
    if isinstance(value, str):
        raw = value
        for _ in range(2):
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, str) and parsed != raw:
                raw = parsed
                continue
            break
        # JSONでなければ素文字列として扱う
        if prefer_key not in ("en_US", "ja_JP"):
            prefer_key = "en_US"
        base = {"en_US": "", "ja_JP": ""}
        base[prefer_key] = raw
        if prefer_key == "en_US" and not base["ja_JP"]:
            base["ja_JP"] = default_ja or ""
        return base

    # 想定外型
    return {"ja_JP": default_ja, "en_US": ""}


def _make_model_table(model: str) -> str:
    return (model or "").replace(".", "_")


# -------------------------------
# サービス本体
# -------------------------------
@dataclass
class ImportSummary:
    created: int = 0
    updated: int = 0          # 今回の要件では 0 のまま（既存は更新しない）
    skipped: int = 0
    errors: List[str] = None

    # 追加情報（ログ/デバッグ向け）
    skipped_existing: int = 0
    skipped_not_found: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "created": int(self.created),
            "updated": int(self.updated),
            "skipped": int(self.skipped),
            "errors": list(self.errors or []),
            "skipped_existing": int(self.skipped_existing),
            "skipped_not_found": int(self.skipped_not_found),
        }


class PortalImportService:
    """
    - 既存の portal_model に同名 model がある場合は「取り込まない（skip）」に統一。
    - ir_model_src.label_en_us を portal_model.label_i18n(JSONB) にミラー可能。
      （mirror_label_from_ir=True, label_source='label_en_us'）
    """

    def __init__(self, sess: Session):
        self.sess = sess

    # ---- モデル取込（今回の主対象） ---------------------------------------
    def import_models(
        self,
        models: Optional[List[str]] = None,
        scaffold: bool = True,
        *,
        mirror_label_from_ir: bool = False,
        label_source: str = "label_en_us",
        convert_to_jsonb: bool = True,   # 互換シグネチャ維持（今回の仕様では既存スキップのため更新に使わない）
    ) -> Dict[str, Any]:
        """
        IRソース（public.ir_model_src）→ portal_model
        - 既存に同名の model がある場合は更新せず skip（要件）
        - mirror_label_from_ir=True なら、ir_model_src.label_en_us を label_i18n(JSONB) として保存
        - IRに無くても scaffold=True なら最小行を作成

        Returns: {"created": x, "updated": 0, "skipped": y, "errors": [...], "skipped_existing": a, "skipped_not_found": b}
        """
        summary = ImportSummary(errors=[])

        req_models = [m.strip() for m in (models or []) if isinstance(m, str) and m.strip()]
        if not req_models:
            # 空なら何もしない
            return summary.to_dict()

        # 1) 既存 portal_model を先に取得（lower(model) 比較）
        placeholders = ",".join(f":pm{i}" for i in range(len(req_models)))
        params = {f"pm{i}": req_models[i].lower() for i in range(len(req_models))}
        existing_q = text(f"""
            SELECT model
              FROM public.portal_model
             WHERE lower(model) IN ({placeholders})
        """)
        existing_rows: Result = self.sess.execute(existing_q, params)
        existing_models = {str(r[0]).lower() for r in existing_rows}

        # 2) IR から対象を取得
        ir_map: Dict[str, Tuple[str, Optional[Any]]] = {}  # lower(model) -> (model_table, label_src)
        ir_params = params.copy()
        ir_q = text(f"""
            SELECT model, model_table, {label_source} AS label_src
              FROM public.ir_model_src
             WHERE lower(model) IN ({placeholders})
        """)
        try:
            ir_rows: Result = self.sess.execute(ir_q, ir_params)
            for model, model_table, label_src in ir_rows:
                ir_map[str(model).lower()] = (model_table, label_src)
        except Exception as e:
            # IRテーブルが無い/列が無い等でも全体は継続（scaffold の可能性）
            log.warning("import_models: failed to read ir_model_src (%s): %s", label_source, e)

        # 3) ループして insert or skip
        for m in req_models:
            key = m.lower()
            if key in existing_models:
                summary.skipped += 1
                summary.skipped_existing += 1
                log.info("import_models: skip existing portal_model.model=%s", m)
                continue

            # IRにある？
            if key in ir_map:
                model_table, label_src = ir_map[key]
                label_i18n = (
                    _normalize_label_i18n(label_src, default_ja=m, prefer_key="en_US")
                    if mirror_label_from_ir
                    else {"ja_JP": m, "en_US": ""}
                )
                payload = {
                    "model": m,
                    "model_table": model_table or _make_model_table(m),
                    "label_i18n": label_i18n,
                }
                try:
                    self._create_portal_model(payload)
                    summary.created += 1
                except Exception as e:
                    msg = f"create failed for model={m}: {e}"
                    log.warning(msg)
                    summary.errors.append(msg)
                continue

            # IRに無い → scaffold の判定
            if scaffold:
                payload = {
                    "model": m,
                    "model_table": _make_model_table(m),
                    "label_i18n": {"ja_JP": m, "en_US": ""},
                }
                try:
                    self._create_portal_model(payload)
                    summary.created += 1
                except Exception as e:
                    msg = f"scaffold failed for model={m}: {e}"
                    log.warning(msg)
                    summary.errors.append(msg)
            else:
                summary.skipped += 1
                summary.skipped_not_found += 1
                log.info("import_models: skip not found in IR (model=%s, scaffold=False)", m)

        return summary.to_dict()

    # ---- フィールド取込（IR→portal_fields） -------------------------------
    def import_fields(self, *, model: str, fields: Optional[list[str]] = None) -> Dict[str, Any]:
        """
        IRソース（public.ir_field_src）→ portal_fields へ取り込み（UPSERT）
        - model は技術名（例: 'stock.picking'）
        - fields 指定があれば交差集合で絞り込み
        """
        if not model or not isinstance(model, str):
            return {"created": 0, "updated": 0, "skipped": 0, "errors": ["model is required"]}

        model = model.strip()
        model_table = model.replace(".", "_").lower()
        fields_l = [f.strip().lower() for f in (fields or []) if f and isinstance(f, str)]

        # 動的に WHERE を構築（空配列時に IN () を生成しない）
        base_sql = """
            SELECT
                :model AS model,
                model_table,
                field_name,
                ttype,
                label_ja_jp,
                label_en_us,
                notes,
                'ir'::text AS origin
            FROM public.ir_field_src
            WHERE lower(model_table) = :model_table
        """
        if fields_l:
            base_sql += "  AND lower(field_name) IN :fields\n"
            q = text(base_sql).bindparams(bindparam("fields", expanding=True))
            params = {"model": model, "model_table": model_table, "fields": fields_l}
        else:
            q = text(base_sql)
            params = {"model": model, "model_table": model_table}

        rows = list(self.sess.execute(q, params).mappings())

        from app.repos.portal_field_repo import PortalFieldRepo
        repo = PortalFieldRepo(self.sess)
        res = repo.bulk_upsert_from_ir(model=model, ir_rows=rows, only_fields=fields_l or None)

        # Router は created/updated/skipped を使う
        return {
            "created": res.get("inserted", 0),
            "updated": res.get("updated", 0),
            "skipped": res.get("skipped", 0),
            "errors": [],
        }


    def import_view_common(self, *args, **kwargs) -> Dict[str, Any]:
        """
        既存互換のためのプレースホルダ。
        既存の実装が別ルートで動いている環境を壊さないよう、0件のサマリを返す。
        """
        log.info("PortalImportService.import_view_common called (no-op placeholder).")
        return {"created": 0, "updated": 0, "skipped": 0, "errors": []}

    # ---- 内部：INSERT 専用（既存は更新しない） ----------------------------
    def _create_portal_model(self, payload: Dict[str, Any]) -> None:
        """
        既存の portal_model 行が無い前提で INSERT。
        BaseCoreRepo に寄せず SQL で最小実装（未知カラムを入れない）。
        """
        q = text("""
            INSERT INTO public.portal_model (model, model_table, label_i18n)
            VALUES (:model, :model_table, CAST(:label_i18n AS jsonb))
        """)
        # label_i18n は dict → JSON 文字列化
        params = {
            "model": payload["model"],
            "model_table": payload["model_table"],
            "label_i18n": json.dumps(payload.get("label_i18n") or {}),
        }
        self.sess.execute(q, params)
        # commit はリクエスト境界（get_session）で行われる前提

    def _parse_label_i18n(self, raw):
        # raw: None | str(JSON) | dict(JSON)
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        s = str(raw).strip()
        if not s:
            return {}
        # JSON文字列なら読む。失敗したら英語キーにそのまま入れるか最小構成へ。
        try:
            val = json.loads(s)
            # もし "en_US": "Transfer" のようなプリミティブだけなら dict に包む（保険）
            if isinstance(val, str):
                return {"en_US": val}
            if isinstance(val, dict):
                return val
            return {}
        except Exception:
            # ただの文字列だった場合のフォールバック
            return {"en_US": s}

    def import_models(self, *, models: list[str], scaffold: bool = True, update_existing: bool = False) -> dict:
        if not models:
            return {"created": 0, "updated": 0, "skipped": 0}

        m_lower = [m.lower() for m in models]

        # 1) IRから model, model_table, label_en_us を収集
        sql = text("""
            SELECT model, model_table, label_en_us
              FROM public.ir_model_src
             WHERE lower(model) IN :models
        """).bindparams(bindparam("models", expanding=True))
        rows = list(self.sess.execute(sql, {"models": m_lower}).mappings())

        ir_map = {}
        for r in rows:
            model = r["model"]
            label_i18n = self._parse_label_i18n(r.get("label_en_us"))
            ir_map[model] = {
                "model": model,
                "model_table": r.get("model_table") or model.replace(".", "_"),
                "label_i18n": label_i18n,
            }

        created = updated = skipped = 0

        for model in models:
            target = ir_map.get(model)
            if not target:
                if scaffold:
                    target = {
                        "model": model,
                        "model_table": model.replace(".", "_"),
                        "label_i18n": {"ja_JP": model},  # 最小スキャフォールド
                    }
                else:
                    skipped += 1
                    continue

            # 既存チェック
            exist = self.sess.execute(
                text("SELECT id, label_i18n FROM public.portal_model WHERE model=:m"),
                {"m": model},
            ).first()

            if exist:
                if not update_existing:
                    skipped += 1
                    continue
                self.sess.execute(sql_upd, target) 
                updated += 1
                # 上書き更新（label_i18n も含めて upsert）
                # self.sess.execute(
                #     text("""
                #         UPDATE public.portal_model
                #            SET model_table = :model_table,
                #                label_i18n = :label_i18n::jsonb,
                #                updated_at = now()
                #          WHERE model = :model
                #     """),
                #     target,
                # )
                # updated += 1
            else:
                # 新規作成
                self.sess.execute(sql_ins, target)
                created += 1

        # トランザクション反映（呼び元のリクエスト境界で commit/rollback 方針でもOK）
        self.sess.commit()

        return {"created": created, "updated": updated, "skipped": skipped}
    
    #Service に「portal_field_src → portal_view_common」の実装を追加
    def import_view_common_from_field_src(self, *, model: str, fields: Optional[list[str]] = None) -> Dict[str, Any]:
        """
        portal_field_src をソースに、指定 model の display_fields を構成して
        portal_view_common を 1 件 UPSERT する。
        - fields が与えられればその交差（lower 比較）
        - action_xmlid は model ベースの合成（衝突しないよう命名）
        """
        if not model or not isinstance(model, str):
            return {"created": 0, "updated": 0, "skipped": 0, "errors": ["model is required"]}

        model = model.strip()
        model_lower = model.lower()
        model_table = model.replace(".", "_").lower()
        fields_l = [f.strip().lower() for f in (fields or []) if f and isinstance(f, str)]

        # --- portal_field_src から field_name を取得（model または model_table のどちらかに対応）
        rows = []
        # 1) model 列での取得を試行
        try:
            base_sql = """
                SELECT field_name
                  FROM public.portal_field_src
                 WHERE lower(model) = :m
            """
            if fields_l:
                base_sql += "   AND lower(field_name) IN :fields\n"
                q = text(base_sql).bindparams(bindparam("fields", expanding=True))
                rows = list(self.sess.execute(q, {"m": model_lower, "fields": fields_l}).mappings())
            else:
                q = text(base_sql)
                rows = list(self.sess.execute(q, {"m": model_lower}).mappings())
        except Exception:
            rows = []

        # 2) 取れなければ model_table 列での取得を試行
        if not rows:
            base_sql = """
                SELECT field_name
                  FROM public.portal_field_src
                 WHERE lower(model_table) = :mt
            """
            if fields_l:
                base_sql += "   AND lower(field_name) IN :fields\n"
                q = text(base_sql).bindparams(bindparam("fields", expanding=True))
                rows = list(self.sess.execute(q, {"mt": model_table, "fields": fields_l}).mappings())
            else:
                q = text(base_sql)
                rows = list(self.sess.execute(q, {"mt": model_table}).mappings())

        display_fields = [r["field_name"] for r in rows]
        # 空でも「スキャフォールド」する（後で UI から編集できる前提）
        # 必要なら空時 skipped 扱いにしても良い

        # --- action_xmlid を model ベースで合成（重複しない命名規則）
        action_xmlid = f"portal_view_common:{model_lower}"

        # 既存有無チェック
        exists = bool(
            self.sess.execute(
                text("SELECT 1 FROM public.portal_view_common WHERE action_xmlid = :axid"),
                {"axid": action_xmlid},
            ).scalar()
        )

        # UPSERT 実行
        repo = PortalViewCommonRepo(self.sess)
        payload = {
            "action_xmlid": action_xmlid,
            "action_name": model,          # 運用や UI でわかりやすいように
            "model": model,                # repo 側で model_tech へマップ
            "model_table": model_table,
            "display_fields": display_fields,  # JSONB（配列）として保存
            # 必要に応じて初期値を置く:
            # "view_types": ["list", "form"],
            # "primary_view_type": "list",
        }
        repo.upsert(payload)

        return {
            "created": 0 if exists else 1,
            "updated": 1 if exists else 0,
            "skipped": 0,
            "errors": [],
        }


# -------------------------------
# レガシー互換：関数形式の薄いラッパ
# -------------------------------
# def import_models(
#     sess: Session,
#     models: Optional[List[str]] = None,
#     scaffold: bool = True,
#     **kwargs,
# ) -> Dict[str, Any]:
#     """
#     互換用：
#     from app.services.portal_import import import_models
#     の呼び出しを維持するための関数ラッパ。
#     """
#     svc = PortalImportService(sess)
#     return svc.import_models(models=models, scaffold=scaffold, **kwargs)


# def import_fields(sess: Session, *args, **kwargs) -> Dict[str, Any]:
#     svc = PortalImportService(sess)
#     return svc.import_fields(*args, **kwargs)


# def import_view_common(sess: Session, *args, **kwargs) -> Dict[str, Any]:
#     svc = PortalImportService(sess)
#     return svc.import_view_common(*args, **kwargs)

    def import_view_common_by_action_xmlids(self, action_xmlids: Sequence[str]) -> dict:
        if not action_xmlids:
            return {"created": 0, "updated": 0, "skipped": 0}

        xmlids = [x.strip() for x in action_xmlids if x and str(x).strip()]
        if not xmlids:
            return {"created": 0, "updated": 0, "skipped": 0}

        # まとめて IR を取得（IR に存在しない列は参照しない）
        rows = self.sess.execute(
            text("""
                SELECT
                    action_xmlid, action_id, action_name,
                    model_label, model_tech, model_table,
                    view_types, primary_view_type,
                    help_i18n_html, help_ja_html, help_ja_text,
                    help_en_html, help_en_text,
                    view_mode, context, domain
                FROM public.ir_view_src
                WHERE action_xmlid IN :ids
            """).bindparams(bindparam("ids", expanding=True)),
            {"ids": xmlids},
        ).mappings().all()

        if not rows:
            return {"created": 0, "updated": 0, "skipped": len(xmlids)}

        repo = PortalViewCommonRepo(self.sess)

        # 既存行を一括で把握
        existed_set = set(
            self.sess.execute(
                text("SELECT action_xmlid FROM public.portal_view_common WHERE action_xmlid IN :ids")
                .bindparams(bindparam("ids", expanding=True)),
                {"ids": [r["action_xmlid"] for r in rows]},
            ).scalars().all()
        )

        created = 0
        updated = 0
        seen = set()

        for r in rows:
            axid = r["action_xmlid"]
            seen.add(axid)
            repo.upsert_from_ir(dict(r))
            if axid in existed_set:
                updated += 1
            else:
                created += 1

        skipped = len([x for x in xmlids if x not in seen])
        self.sess.commit()
        return {"created": created, "updated": updated, "skipped": skipped}