# app/repos/pg_helpers.py
from typing import Any, Mapping, Sequence, Dict, Iterable, Optional, Tuple
from sqlalchemy import Table, Column, cast, bindparam, func
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert, JSONB
from sqlalchemy.sql import ColumnElement

# --- 1. 単体 UPSERT ---
def upsert_one(
    session: Session,
    *,
    table: Table,
    values: Mapping[str, Any],
    conflict_cols: Sequence[str],
    update_assignments: Optional[Mapping[ColumnElement, Any]] = None,
    returning: Optional[Sequence[Column]] = None,
):
    ins = pg_insert(table).values(**values)
    if update_assignments is None:
        # ★ 修正: ins.excluded.c[...] は NG。getattr(ins.excluded, colname) を使う
        update_assignments = {
            c: getattr(ins.excluded, c.name)
            for c in table.columns
            if c.name not in conflict_cols and c.name != "id"
        }
    stmt = ins.on_conflict_do_update(
        index_elements=[getattr(table.c, c) for c in conflict_cols],
        set_=update_assignments,
    )
    if returning:
        stmt = stmt.returning(*returning)
        return session.execute(stmt).mappings().one()
    return session.execute(stmt)

# --- 2. バルク UPSERT ---
def upsert_many(
    session: Session,
    *,
    table: Table,
    rows: Sequence[Mapping[str, Any]],
    conflict_cols: Sequence[str],
    update_columns: Optional[Sequence[str]] = None,
    returning_cols: Optional[Sequence[Column]] = None,
):
    if not rows:
        return []
    ins = pg_insert(table).values(rows)
    if update_columns is None:
        # ★ 念のためこちらも同じく getattr を使用
        set_map = {
            c: getattr(ins.excluded, c.name)
            for c in table.columns
            if c.name not in conflict_cols and c.name != "id"
        }
    else:
        set_map = {
            getattr(table.c, c): getattr(ins.excluded, c)
            for c in update_columns
        }
    stmt = ins.on_conflict_do_update(
        index_elements=[getattr(table.c, c) for c in conflict_cols],
        set_=set_map,
    )
    if returning_cols:
        stmt = stmt.returning(*returning_cols)
        return session.execute(stmt).mappings().all()
    session.execute(stmt)
    return []

# （以下 jsonb_merge_expr / build_update_assignments はそのまま）
def build_update_assignments(
    table: Table,
    values: Mapping[str, Any],
    *,
    jsonb_cols: Iterable[str] = (),
) -> Tuple[Dict[ColumnElement, Any], Dict[str, Any]]:
    set_map: Dict[ColumnElement, Any] = {}
    params: Dict[str, Any] = {}

    jsonb_cols_set = set(jsonb_cols or [])
    for k, v in values.items():
        try:
            col = table.c[k]  # ★ getattr ではなく添字
        except Exception:
            continue

        if k in jsonb_cols_set and isinstance(v, dict):
            param_name = f"{k}_patch"
            set_map[col] = jsonb_merge_expr(col, param_name)
            params[param_name] = v
        elif v is not None:
            set_map[col] = v
        # None は無視
    return set_map, params