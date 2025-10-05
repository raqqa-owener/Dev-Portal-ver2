# api/app/routers/__init__.py

# ここでは「router を再エクスポート」しません。
# main.py は `extract as extract_router` のように「モジュール」を import し、
# その後 `extract_router.router` を参照するためです。

from . import status
from . import extract
from . import translate
from . import writeback
from . import package
from . import chroma_docs          # /chroma/upsert（Hフェーズ; まだ未実装でも可）
from . import chroma_docs     # /chroma/docs（Gフェーズ）
from . import portal_field
from . import portal_view_common
# 必要なら他の portal_* も同様に追加

__all__ = [
    "status",
    "extract",
    "translate",
    "writeback",
    "package",
    "chroma_docs",
    "chroma_docs",
    "portal_field",
    "portal_view_common",
]
