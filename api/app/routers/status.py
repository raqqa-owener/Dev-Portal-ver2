# api/app/routers/status.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.repos.portal_chroma_doc_repo import PortalChromaDocRepo

router = APIRouter(tags=["Status"], prefix="/status")

_TRANSLATE_STATUSES = ["pending", "translated", "ready_for_chroma", "done", "failed"]
_CHROMA_DOC_STATUSES = ["queued", "upserted", "failed"]


# ===== Repo(DBAPI直)ヘルパ =====
def _column_exists_repo(repo: PortalChromaDocRepo, *, schema: str, table: str, column: str) -> bool:
    try:
        rows, _ = repo._select(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema = %s
               AND table_name   = %s
               AND column_name  = %s
             LIMIT 1
            """,
            (schema, table, column),
        )
        return bool(rows)
    except Exception:
        return False


def _count_by_col_repo(repo: PortalChromaDocRepo, table_fq: str, col: str, keys: list[str]) -> dict[str, int]:
    """
    DBAPI直で SELECT col, COUNT(*)。失敗時は 0 埋め。
    table_fq は "public.portal_chroma_doc" のような固定文字列を渡すこと。
    """
    try:
        rows, cols = repo._select(f"SELECT {col} AS k, COUNT(*) AS c FROM {table_fq} GROUP BY {col}")
        # cols = ["k","c"] を想定
        idx = {name: i for i, name in enumerate(cols)}
        m = {}
        for r in rows:
            k = r[idx.get("k", 0)]
            c = r[idx.get("c", 1)]
            if k is not None:
                m[str(k)] = int(c)
        return {k: int(m.get(k, 0)) for k in keys}
    except Exception:
        return {k: 0 for k in keys}


@router.get("/summary", summary="ステージ別件数サマリ")
def status_summary(sess: Session = Depends(get_session)):
    """
    translate（status）と chroma_doc（state or status）の件数サマリを返す。
    * translate: status 固定
    * chroma_doc: state 優先、無い場合は status を state 名にエイリアス
    失敗時は各カテゴリ 0 で返す（リトライ/キャッシュなし）。
    """
    repo = PortalChromaDocRepo(sess)

    # translate（status 固定）
    try:
        rows, _ = repo._select("SELECT status, COUNT(*) FROM public.portal_translate GROUP BY status")
        translate = {k: 0 for k in _TRANSLATE_STATUSES}
        for status, c in rows:
            if status in translate:
                translate[status] = int(c)
    except Exception:
        translate = {k: 0 for k in _TRANSLATE_STATUSES}

    # chroma_doc（state 優先 → status フォールバック）
    chroma_doc = {k: 0 for k in _CHROMA_DOC_STATUSES}
    for sql in (
        "SELECT state,  COUNT(*) FROM public.portal_chroma_doc GROUP BY state",
        "SELECT status, COUNT(*) FROM public.portal_chroma_doc GROUP BY status",
    ):
        try:
            rows, _ = repo._select(sql)
            d = {k: 0 for k in _CHROMA_DOC_STATUSES}
            for key, c in rows:
                if key in d:
                    d[key] = int(c)
            chroma_doc = d
            break
        except Exception:
            continue

    return {"translate": translate, "chroma_doc": chroma_doc}


@router.get("/trace", summary="natural_key 単位の通し状況", name="samples/trace")
def trace(
    natural_key: str = Query(..., description="例: field::sale.order::partner_id"),
    sess: Session = Depends(get_session),
):
    """
    natural_key を基点に translate の最新行と chroma_doc の履歴（最大50件）を返す。
    chroma_doc の state カラムが無ければ status を state 名にエイリアス。
    失敗時は該当セクションを None / [] として返す。
    """
    repo = PortalChromaDocRepo(sess)

    # translate（最新1件）
    try:
        rows, cols = repo._select(
            """
            SELECT natural_key, entity, model, label, purpose,
                   translated_label, translated_purpose,
                   status, updated_at
              FROM public.portal_translate
             WHERE natural_key = %s
             ORDER BY updated_at DESC
             LIMIT 1
            """,
            (natural_key,),
        )
        if rows:
            idx = {name: i for i, name in enumerate(cols)}
            r = rows[0]
            translate = {k: r[i] for k, i in idx.items()}
        else:
            translate = None
    except Exception:
        translate = None

    # chroma_docs（state 優先、無ければ status→state）
    has_state = _column_exists_repo(repo, schema="public", table="portal_chroma_doc", column="state")
    if has_state:
        sql = """
            SELECT doc_id, natural_key, lang, collection, doc_text,
                   entity, model, model_table, field_name, action_xmlid, target,
                   meta AS metadata,
                   state AS state,
                   updated_at
              FROM public.portal_chroma_doc
             WHERE natural_key = %s
             ORDER BY updated_at DESC
             LIMIT 50
        """
    else:
        sql = """
            SELECT doc_id, natural_key, lang, collection, doc_text,
                   entity, model, model_table, field_name, action_xmlid, target,
                   meta AS metadata,
                   status AS state,
                   updated_at
              FROM public.portal_chroma_doc
             WHERE natural_key = %s
             ORDER BY updated_at DESC
             LIMIT 50
        """

    chroma_docs = []
    try:
        rows, cols = repo._select(sql, (natural_key,))
        idx = {name: i for i, name in enumerate(cols)}
        for r in rows:
            chroma_docs.append({k: r[i] for k, i in idx.items()})
    except Exception:
        chroma_docs = []

    return {"natural_key": natural_key, "translate": translate, "chroma_docs": chroma_docs}

#元ファイル
# # app/routers/status.py
# from __future__ import annotations

# from fastapi import APIRouter, Depends, Query
# from sqlalchemy.orm import Session

# from app.db import get_session
# from app.repos.portal_chroma_doc_repo import PortalChromaDocRepo

# router = APIRouter(tags=["Status"], prefix="/status")

# _TRANSLATE_STATUSES = ["pending", "translated", "ready_for_chroma", "done", "failed"]
# _CHROMA_DOC_STATUSES = ["queued", "upserted", "failed"]


# # ===== Repo(DBAPI直)ヘルパ =====
# def _column_exists_repo(repo: PortalChromaDocRepo, *, schema: str, table: str, column: str) -> bool:
#     try:
#         rows, _ = repo._select(
#             """
#             SELECT 1
#               FROM information_schema.columns
#              WHERE table_schema = %s
#                AND table_name   = %s
#                AND column_name  = %s
#              LIMIT 1
#             """,
#             (schema, table, column),
#         )
#         return bool(rows)
#     except Exception:
#         return False


# def _count_by_col_repo(repo: PortalChromaDocRepo, table_fq: str, col: str, keys: list[str]) -> dict[str, int]:
#     """
#     DBAPI直で SELECT col, COUNT(*)。失敗時は 0 埋め。
#     table_fq は "public.portal_chroma_doc" のような固定文字列を渡すこと。
#     """
#     try:
#         rows, cols = repo._select(f"SELECT {col} AS k, COUNT(*) AS c FROM {table_fq} GROUP BY {col}")
#         # cols = ["k","c"] を想定
#         idx = {name: i for i, name in enumerate(cols)}
#         m = {}
#         for r in rows:
#             k = r[idx.get("k", 0)]
#             c = r[idx.get("c", 1)]
#             if k is not None:
#                 m[str(k)] = int(c)
#         return {k: int(m.get(k, 0)) for k in keys}
#     except Exception:
#         return {k: 0 for k in keys}


# # app/routers/status.py の /summary をこれに置換

# @router.get("/summary", summary="ステージ別件数サマリ")
# def status_summary(sess: Session = Depends(get_session)):
#     from app.repos.portal_chroma_doc_repo import PortalChromaDocRepo
#     repo = PortalChromaDocRepo(sess)

#     # translate（status 固定）
#     try:
#         rows, _ = repo._select("SELECT status, COUNT(*) FROM public.portal_translate GROUP BY status")
#         translate = {k: 0 for k in _TRANSLATE_STATUSES}
#         for status, c in rows:
#             if status in translate:
#                 translate[status] = int(c)
#     except Exception:
#         translate = {k: 0 for k in _TRANSLATE_STATUSES}

#     # chroma_doc（state 優先 → status フォールバック）
#     chroma_doc = {k: 0 for k in _CHROMA_DOC_STATUSES}
#     for sql in (
#         "SELECT state,  COUNT(*) FROM public.portal_chroma_doc GROUP BY state",
#         "SELECT status, COUNT(*) FROM public.portal_chroma_doc GROUP BY status",
#     ):
#         try:
#             rows, _ = repo._select(sql)
#             d = {k: 0 for k in _CHROMA_DOC_STATUSES}
#             for key, c in rows:
#                 if key in d:
#                     d[key] = int(c)
#             chroma_doc = d
#             break
#         except Exception:
#             continue

#     return {"translate": translate, "chroma_doc": chroma_doc}




# @router.get("/trace", summary="natural_key 単位の通し状況", name="samples/trace")
# def trace(
#     natural_key: str = Query(..., description="例: field::sale.order::partner_id"),
#     sess: Session = Depends(get_session),
# ):
#     """
#     DBAPI直で取得。chroma_doc は meta を metadata 名で返し、
#     state カラムが無ければ status を state 名にエイリアス。
#     """
#     repo = PortalChromaDocRepo(sess)

#     # translate（最新1件）
#     try:
#         rows, cols = repo._select(
#             """
#             SELECT natural_key, entity, model, label, purpose,
#                    translated_label, translated_purpose,
#                    status, updated_at
#               FROM public.portal_translate
#              WHERE natural_key = %s
#              ORDER BY updated_at DESC
#              LIMIT 1
#             """,
#             (natural_key,),
#         )
#         if rows:
#             idx = {name: i for i, name in enumerate(cols)}
#             r = rows[0]
#             translate = {k: r[i] for k, i in idx.items()}
#         else:
#             translate = None
#     except Exception:
#         translate = None

#     # chroma_docs（state 優先、無ければ status→state）
#     has_state = _column_exists_repo(repo, schema="public", table="portal_chroma_doc", column="state")
#     if has_state:
#         sql = """
#             SELECT doc_id, natural_key, lang, collection, doc_text,
#                    entity, model, model_table, field_name, action_xmlid, target,
#                    meta AS metadata,
#                    state AS state,
#                    updated_at
#               FROM public.portal_chroma_doc
#              WHERE natural_key = %s
#              ORDER BY updated_at DESC
#              LIMIT 50
#         """
#     else:
#         sql = """
#             SELECT doc_id, natural_key, lang, collection, doc_text,
#                    entity, model, model_table, field_name, action_xmlid, target,
#                    meta AS metadata,
#                    status AS state,
#                    updated_at
#               FROM public.portal_chroma_doc
#              WHERE natural_key = %s
#              ORDER BY updated_at DESC
#              LIMIT 50
#         """

#     chroma_docs = []
#     try:
#         rows, cols = repo._select(sql, (natural_key,))
#         idx = {name: i for i, name in enumerate(cols)}
#         for r in rows:
#             chroma_docs.append({k: r[i] for k, i in idx.items()})
#     except Exception:
#         chroma_docs = []

#     return {"natural_key": natural_key, "translate": translate, "chroma_docs": chroma_docs}
