from __future__ import annotations

import logging
from importlib import import_module

from fastapi import FastAPI, Response
from fastapi import status as http_status
from fastapi.responses import RedirectResponse

from app.db import ping
from app.config import settings

log = logging.getLogger(__name__)

app = FastAPI(
    title="Dev Portal & Translation → Chroma Pipeline API",
    version="0.2.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# ---- startup logging (Embedding/Chroma spec) ----
@app.on_event("startup")
def _log_startup_specs() -> None:
    try:
        openai_key_present = bool(settings.OPENAI_API_KEY)
    except Exception:
        openai_key_present = False

    log.info(
        "[startup] EMBEDDING: provider=%s model=%s dims=%s batch_size=%s",
        settings.EMBED_PROVIDER,
        settings.EMBED_MODEL,
        settings.EMBED_DIMENSIONS,
        settings.EMBED_BATCH_SIZE,
    )
    log.info(
        "[startup] CHROMA: url=%s allow_upsert=%s timeout_s=%s",
        settings.CHROMA_URL,
        settings.ALLOW_CHROMA_UPSERT,
        getattr(settings, "CHROMA_TIMEOUT_S", None),
    )
    if (settings.EMBED_PROVIDER or "").lower() == "openai":
        log.info("[startup] OPENAI_API_KEY: %s", "SET" if openai_key_present else "NOT SET")

# ---- root / health ----
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs", status_code=307)

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/livez")
def livez():
    return {"ok": True}

@app.get("/startupz")
def startupz():
    try:
        ping()
        return {"db": "ok"}
    except Exception as e:
        return Response(content=str(e), status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE)

# ==== ルーター取り込みヘルパ（相対/絶対/既存prefixを自動判定、重複includeを防ぐ） ====
def _include_router_detect_prefix(module_name: str, expected_prefix: str) -> bool:
    """
    module_name: 'app.routers.<module>'
    expected_prefix: '/portal/model' や '/chroma' など

    ルーター側の prefix と個々の route.path を検査して、二重 prefix（/chroma/chroma）を防ぐ。
    - router.prefix が expected_prefix で始まっていれば prefix なしで include
    - router.routes の path が expected_prefix で始まる（= 絶対定義）なら prefix なしで include
    - それ以外は expected_prefix を付けて include
    """
    try:
        mod = import_module(module_name)
    except ModuleNotFoundError:
        log.warning("router module '%s' not found; skipping", module_name)
        return False

    router = getattr(mod, "router", None)
    if router is None:
        log.warning("module '%s' has no 'router'; skipping", module_name)
        return False

    paths = []
    for r in getattr(router, "routes", []):
        try:
            p = getattr(r, "path", "") or ""
            if p:
                paths.append(p)
        except Exception:
            pass

    router_prefix = getattr(router, "prefix", "") or ""

    try:
        if router_prefix.startswith(expected_prefix) or any(p.startswith(expected_prefix) for p in paths if p):
            app.include_router(router)
            log.info("included router: %s (no prefix; prefix='%s' paths=%s)", module_name, router_prefix, paths[:3])
        else:
            app.include_router(router, prefix=expected_prefix)
            log.info("included router: %s (with prefix: %s; prefix='%s' paths=%s)",
                     module_name, expected_prefix, router_prefix, paths[:3])
        return True
    except Exception as e:
        log.error("include router '%s' failed: %s", module_name, e)
        return False

# ==== ルーター登録 ====
# パイプライン系（dev専用もあり）：/extract, /translate, /writeback
_include_router_detect_prefix("app.routers.extract",   "/extract")
_include_router_detect_prefix("app.routers.translate", "/translate")
_include_router_detect_prefix("app.routers.writeback", "/writeback")

# Chroma 配下（/chroma）
# _include_router_detect_prefix("app.routers.package",     "/chroma")  # /chroma/package（必要時に解放）
_include_router_detect_prefix("app.routers.chroma",      "/chroma")    # /chroma/upsert, /chroma/search, /chroma/query
_include_router_detect_prefix("app.routers.chroma_docs", "/chroma")    # /chroma/docs

# ステータス（/status）
_include_router_detect_prefix("app.routers.status", "/status")

# ---- Portal 系（可変 include：直 include はしない） ----
def include_portal_router(module_basename: str, expected_prefix: str) -> bool:
    return _include_router_detect_prefix(f"app.routers.{module_basename}", expected_prefix)

# field は単数/複数ファイル名の差異に対応
if not include_portal_router("portal_field", "/portal/field"):
    include_portal_router("portal_fields", "/portal/field")

include_portal_router("portal_model",         "/portal/model")
include_portal_router("portal_view_common",   "/portal/view_common")
include_portal_router("portal_view",          "/portal/view")
include_portal_router("portal_tab",           "/portal/tab")
include_portal_router("portal_smart_button",  "/portal/smart_button")
include_portal_router("portal_menu",          "/portal/menu")
