from typing import Iterable, List

CANONICAL_ORDER = [
    "form",
    "kanban",
    "list",
    "calendar",
    "search",
    "graph",
    "pivot",
    "dashboard",
    "tree",
    "map",
]

ALIAS = {"tree": "list"}  # 比較・一意キー用のみ


def split_view_mode(view_mode: str) -> List[str]:
    # 例: "tree,form,kanban" -> ["tree","form","kanban"]
    if not view_mode:
        return []
    return [x.strip() for x in view_mode.split(',') if x.strip()]


def to_store_order(view_types_or_view_mode: Iterable[str] | str) -> List[str]:
    """IR 順（与えられた順）をそのまま保存する。
    文字列 view_mode の場合は分解する。
    """
    if isinstance(view_types_or_view_mode, str):
        vt = split_view_mode(view_types_or_view_mode)
    else:
        vt = list(view_types_or_view_mode)
    # 重複は保存時も一応除去
    seen = set()
    stored: List[str] = []
    for v in vt:
        if v not in seen:
            stored.append(v)
            seen.add(v)
    return stored


def to_uniqueness_key(view_types: Iterable[str]) -> str:
    """一意性比較用キー。tree→list 置換し、正規順でソート＋重複除去。"""
    mapped = [ALIAS.get(v, v) for v in view_types]
    # 正規順に並べ替え
    order_map = {v: i for i, v in enumerate(CANONICAL_ORDER)}
    dedup_sorted = sorted(set(mapped), key=lambda v: order_map.get(v, 999))
    return "|".join(dedup_sorted)