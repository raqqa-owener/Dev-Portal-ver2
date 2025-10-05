# app/repos/base_core.py
import logging
from typing import Any, Mapping, Optional, Tuple, List, Dict, Union, Iterable

from sqlalchemy import (
    MetaData,
    Table,
    select,
    update as sa_update,
    delete as sa_delete,
    insert as sa_insert,
    text,
)
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, DataError

from app.db import engine
from app.repos.errors import NotFound, Conflict, Validation, Transient
from app.utils.cursor import decode_last_id_cursor, encode_last_id_cursor

logger = logging.getLogger(__name__)

try:
    from pydantic import BaseModel as _PydanticBaseModel  # type: ignore
    _HAS_PYDANTIC = True
except Exception:  # pragma: no cover
    _HAS_PYDANTIC = False
    class _PydanticBaseModel:  # type: ignore
        pass


class BaseCoreRepo:
    TABLE: Optional[str] = None
    SCHEMA: Optional[str] = "public"

    def __init__(self, db: Session, *, table: Optional[Union[str, Table]] = None):
        self.db: Session = db
        self.sess: Session = db
        self._table_input = table
        self.t: Optional[Table] = None
        self._table_name_cache: Optional[str] = None
        self._init_table_if_possible()

    # -------------------- table init / helpers --------------------

    def _init_table_if_possible(self) -> None:
        """
        - Table オブジェクトが与えられていればそれを採用
        - 文字列 or クラス属性 TABLE があればリフレクト
        """
        # ★ 防御: サブクラスが super().__init__ を呼ばなくても落ちないように
        if not hasattr(self, "_table_input"):
            self._table_input = None
        if not hasattr(self, "t"):
            self.t = None
        if not hasattr(self, "_table_name_cache"):
            self._table_name_cache = None

        table_input = self._table_input
        if isinstance(table_input, Table):
            self.t = table_input
            self._table_name_cache = table_input.name
            return

        name = (
            table_input if isinstance(table_input, str)
            else getattr(self, "TABLE", None)
        )
        self._table_name_cache = name

        if not name:
            logger.debug("BaseCoreRepo: TABLE name not provided; will fallback to information_schema")
            return

        try:
            md = MetaData()
            bind = getattr(self.db, "bind", None) or engine
            self.t = Table(
                name, md,
                schema=getattr(self, "SCHEMA", None),
                autoload_with=bind,
            )
            logger.debug("BaseCoreRepo: reflected table %s (schema=%s)", name, self.SCHEMA)
        except Exception as e:
            logger.warning("BaseCoreRepo: table reflect failed for %s: %s", name, e)
            self.t = None

    def _ensure_table(self) -> Table:
        if self.t is None:
            self._init_table_if_possible()
        if self.t is None:
            raise Transient(f"Table metadata not available (TABLE={self._table_name_cache!r}, SCHEMA={self.SCHEMA!r})")
        return self.t

    def _columns_via_information_schema(self) -> Optional[Iterable[str]]:
        if not self._table_name_cache:
            return None
        schema = self.SCHEMA or "public"
        sql = """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            ORDER BY ordinal_position
        """
        rows = self.sess.execute(text(sql), {"schema": schema, "table": self._table_name_cache}).scalars().all()
        return rows or None

    # -------------------- utils --------------------

    def _coerce_to_dict(self, obj: Optional[Union[Mapping[str, Any], "_PydanticBaseModel"]], kwargs: Dict[str, Any]) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if obj is not None:
            if _HAS_PYDANTIC and isinstance(obj, _PydanticBaseModel):  # type: ignore[arg-type]
                data.update(obj.model_dump(exclude_unset=True, exclude_none=True))  # type: ignore[attr-defined]
            elif isinstance(obj, Mapping):
                data.update(dict(obj))
            else:
                raise Validation(f"Unsupported payload type: {type(obj)!r}")
        if kwargs:
            data.update(kwargs)
        return data

    def _sanitize_columns(self, data: Mapping[str, Any]) -> Dict[str, Any]:
        cols: Optional[Iterable[str]] = None
        if self.t is None:
            self._init_table_if_possible()
        if self.t is not None:
            cols = self.t.c.keys()
        else:
            cols = self._columns_via_information_schema()

        if not cols:
            raise Transient(f"Could not resolve columns for TABLE={self._table_name_cache!r} (schema={self.SCHEMA!r})")

        colset = set(cols)
        unknown = [k for k in data.keys() if k not in colset]
        if unknown:
            raise Validation(f"Unknown fields for table '{self._table_name_cache or (self.t and self.t.name)}': {sorted(unknown)}")
        return {k: data[k] for k in data.keys() if k in colset}

    # -------------------- read --------------------

    def get(self, id: int) -> dict:
        t = self._ensure_table()
        row = self.sess.execute(select(t).where(t.c.id == id)).mappings().first()
        if not row:
            raise NotFound(f"{t.name} id={id} not found")
        return dict(row)

    def list_keyset(
        self,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
        eq_filters: Optional[Mapping[str, Any]] = None,
    ) -> Tuple[List[dict], Optional[str]]:
        t = self._ensure_table()
        last_id = decode_last_id_cursor(cursor) or 0

        stmt = (
            select(t)
            .where(t.c.id > last_id)
            .order_by(t.c.id.asc())
            .limit(limit)
        )
        if eq_filters:
            for k, v in eq_filters.items():
                if v is None:
                    continue
                col = getattr(t.c, k, None)
                if col is not None:
                    stmt = stmt.where(col == v)

        rows = self.sess.execute(stmt).mappings().all()
        items = [dict(r) for r in rows]
        next_cursor = encode_last_id_cursor(items[-1]["id"]) if items else None
        return items, next_cursor

    # -------------------- write --------------------

    def create(
        self,
        obj_in: Optional[Union[Mapping[str, Any], "_PydanticBaseModel"]] = None,
        /,
        **values: Any,
    ) -> dict:
        t = self._ensure_table()
        try:
            raw = self._coerce_to_dict(obj_in, values)
            data = self._sanitize_columns(raw)
            row = self.sess.execute(sa_insert(t).values(**data).returning(t)).mappings().one()
            return dict(row)
        except IntegrityError as e:
            raise Conflict(str(e.orig)) from e
        except DataError as e:
            raise Validation(str(e.orig)) from e
        except Validation:
            raise
        except Exception as e:
            raise Transient(str(e)) from e

    def update_by_id(
        self,
        id: int,
        set_map: Mapping[str, Any],
        params: Optional[Dict[str, Any]] = None,
    ) -> dict:
        t = self._ensure_table()
        try:
            # ★ ここを追加: ColumnElement キー（=式や excluded 等）が混ざる場合は
            #    _sanitize_columns を通さずにそのまま values(set_map) を使う
            has_expr_keys = any(not isinstance(k, str) for k in set_map.keys())

            if has_expr_keys:
                if not set_map:
                    raise Validation("No updatable fields given.")
                stmt = sa_update(t).where(t.c.id == id).values(set_map).returning(t)
            else:
                data = self._sanitize_columns(set_map)  # 文字列キーのみのときだけサニタイズ
                if not data:
                    raise Validation("No updatable fields given.")
                stmt = sa_update(t).where(t.c.id == id).values(**data).returning(t)

            row = self.sess.execute(stmt, params or {}).mappings().first()
            if not row:
                raise NotFound(f"{t.name} id={id} not found")
            return dict(row)
        except IntegrityError as e:
            raise Conflict(str(e.orig)) from e
        except DataError as e:
            raise Validation(str(e.orig)) from e
        except Validation:
            raise
        except Exception as e:
            raise Transient(str(e)) from e
        
    def delete_by_id(self, id: int) -> None:
        t = self._ensure_table()
        res = self.sess.execute(sa_delete(t).where(t.c.id == id))
        if res.rowcount == 0:
            raise NotFound(f"{t.name} id={id} not found")
