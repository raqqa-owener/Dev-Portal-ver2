#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reindex portal_chroma_doc into v2 Chroma collections (OpenAI 1536-dim).
- Reads from DB via app.db / PortalChromaDocRepo
- Writes to Chroma using embeddings from OpenAI (text-embedding-3-small, 1536-dim)
- Normalizes metadata for Chroma (only str/int/float/bool allowed; others JSON-stringified)
- Supports migrating existing rows (optionally filtered) and queued rows (mark_upserted/failed)

Run inside the portal-api container (or any environment with app deps installed).

Usage (typical):
  python3 reindex_chroma_v2.py \
    --src portal_field_ja portal_view_common_ja \
    --dst-map portal_field_ja=portal_field_ja_v2 portal_view_common_ja=portal_view_common_ja_v2 \
    --batch 200 --embed-batch 16

Env vars:
  OPENAI_API_KEY (required)
  EMBED_MODEL (default: text-embedding-3-small)
  CHROMA_URL (default: http://chroma:8000)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, Iterable, List, Tuple, Any
from urllib.parse import urlparse

# --- App imports (must exist in the container/image) ---
try:
    from app.db import get_session
    from app.repos.portal_chroma_doc_repo import PortalChromaDocRepo
except Exception as e:
    print("FATAL: cannot import app modules:", e, file=sys.stderr)
    sys.exit(2)

# --- External clients ---
try:
    import chromadb
except Exception as e:
    print("FATAL: chromadb not available:", e, file=sys.stderr)
    sys.exit(2)


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------- Embedding client ----------------------
class Embedder:
    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model
        self._use_new = None  # type: bool | None
        # Probe which OpenAI lib is available
        try:
            from openai import OpenAI  # type: ignore
            self._client = OpenAI()
            self._use_new = True
        except Exception:
            import openai  # type: ignore
            self._client = openai
            if not getattr(self._client, "api_key", None):
                self._client.api_key = os.getenv("OPENAI_API_KEY")
            self._use_new = False

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if self._use_new:
            from openai.types import CreateEmbeddingResponse  # type: ignore
            resp = self._client.embeddings.create(model=self.model, input=texts)
            return [d.embedding for d in resp.data]
        else:
            resp = self._client.Embedding.create(model=self.model, input=texts)
            return [d["embedding"] for d in resp["data"]]


# ---------------------- Helpers ----------------------
def parse_chroma_url(default: str = "http://chroma:8000") -> Tuple[str, int]:
    url = os.getenv("CHROMA_URL", default)
    p = urlparse(url)
    host = p.hostname or "chroma"
    port = p.port or 8000
    return host, int(port)


def norm_meta(md: Any) -> Dict[str, Any]:
    """Chroma metadata must be primitive; convert others to JSON string; drop None."""
    out: Dict[str, Any] = {}
    if not isinstance(md, dict):
        return out
    for k, v in md.items():
        k = str(k)
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            try:
                out[k] = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                out[k] = str(v)
    return out


def chunked(iterable: Iterable[Any], size: int) -> Iterable[List[Any]]:
    buf: List[Any] = []
    for x in iterable:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def build_doc_id(row: Dict[str, Any]) -> str:
    if row.get("doc_id"):
        return row["doc_id"]
    return f"{row['entity']}:{row['natural_key']}:{row['lang']}"


# ---------------------- Core migrate ----------------------
def migrate_existing(
    repo: PortalChromaDocRepo,
    client,
    embedder: Embedder,
    src_colls: List[str],
    dst_map: Dict[str, str],
    batch: int,
    embed_batch: int,
    max_rows: int | None,
) -> int:
    """Migrate existing rows (any state) whose collection in src_colls."""
    total = 0
    cursor = None
    while True:
        rows, cursor = repo.list_keyset(limit=batch, cursor=cursor)
        rows = [r for r in rows if r.get("collection") in src_colls]
        if not rows:
            if cursor is None:
                break
            continue

        # Prepare per destination collection
        rows_by_dst: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            dst = dst_map.get(r["collection"], r["collection"] + "_v2")
            rows_by_dst.setdefault(dst, []).append(r)

        for dst, rlist in rows_by_dst.items():
            col = client.get_or_create_collection(dst, metadata={"hnsw:space": "cosine"})
            # embed & upsert in sub-batches
            for sub in chunked(rlist, embed_batch):
                if max_rows is not None and total >= max_rows:
                    return total
                docs = [(r.get("doc_text") or "").strip() for r in sub]
                ids = [build_doc_id(r) for r in sub]
                metas = [norm_meta(r.get("metadata") or {}) for r in sub]
                try:
                    vecs = embedder.embed_batch(docs)
                    col.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=vecs)
                    total += len(sub)
                except Exception as e:
                    log(f"ERROR upsert existing dst={dst}: {type(e).__name__}: {e}")
        if cursor is None:
            break

    return total


def migrate_queued(
    repo: PortalChromaDocRepo,
    client,
    embedder: Embedder,
    src_colls: List[str],
    dst_map: Dict[str, str],
    limit_once: int,
    embed_batch: int,
) -> Tuple[int, int]:
    """Migrate queued rows only; mark_upserted / mark_failed."""
    ok = fail = 0
    while True:
        rows = repo.list_queued(collections=src_colls, limit=limit_once)
        if not rows:
            break

        # group by dst
        buckets: Dict[str, List[Any]] = {}
        for r in rows:
            dst = dst_map.get(r.collection, r.collection + "_v2")
            buckets.setdefault(dst, []).append(r)

        for dst, rlist in buckets.items():
            col = client.get_or_create_collection(dst, metadata={"hnsw:space": "cosine"})
            # process in sub-batches
            for sub in chunked(rlist, embed_batch):
                docs = [(r.doc_text or "").strip() for r in sub]
                ids = [r.doc_id or f"{r.entity}:{r.natural_key}:{r.lang}" for r in sub]
                metas = [norm_meta(getattr(r, "metadata", {}) or {}) for r in sub]
                try:
                    vecs = embedder.embed_batch(docs)
                    col.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=vecs)
                    for r in sub:
                        repo.mark_upserted(id_=r.id)
                    ok += len(sub)
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    log(f"ERROR upsert queued dst={dst}: {msg[:200]}")
                    for r in sub:
                        try:
                            repo.mark_failed(id_=r.id, error=msg)
                        except Exception:
                            pass
                    fail += len(sub)
        # persist after each cycle
        repo.s.commit()
    return ok, fail


def main() -> int:
    ap = argparse.ArgumentParser(description="Reindex Chroma collections to 1536-dim v2")
    ap.add_argument("--src", nargs="+", required=True, help="Source collection names")
    ap.add_argument("--dst-map", nargs="+", default=[],
                    help="Mapping src=dst (space separated). Example: portal_field_ja=portal_field_ja_v2")
    ap.add_argument("--batch", type=int, default=200, help="DB page size for list_keyset")
    ap.add_argument("--embed-batch", type=int, default=16, help="Embedding batch size")
    ap.add_argument("--max-rows", type=int, default=None, help="Cap total migrated rows for existing set")
    ap.add_argument("--skip-existing", action="store_true", help="Skip migrating existing rows")
    ap.add_argument("--skip-queued", action="store_true", help="Skip migrating queued rows")
    args = ap.parse_args()

    # Build dst map
    dst_map: Dict[str, str] = {}
    for m in args.dst_map:
        if "=" not in m:
            print(f"Invalid mapping: {m}", file=sys.stderr)
            return 2
        src, dst = m.split("=", 1)
        dst_map[src] = dst

    # OpenAI key/model check
    if not os.getenv("OPENAI_API_KEY"):
        print("FATAL: OPENAI_API_KEY is not set in environment", file=sys.stderr)
        return 2
    model = os.getenv("EMBED_MODEL", "text-embedding-3-small")
    embedder = Embedder(model=model)

    # Chroma client
    host, port = parse_chroma_url()
    client = chromadb.HttpClient(host=host, port=port)

    # DB session & repo
    g = get_session(); s = next(g)
    repo = PortalChromaDocRepo(s)

    log(f"Start reindex: src={args.src} dst_map={dst_map} model={model} chroma={host}:{port}")

    total_existing = 0
    if not args.skip_existing:
        total_existing = migrate_existing(
            repo, client, embedder, args.src, dst_map, args.batch, args.embed_batch, args.max_rows
        )
        log(f"Migrated existing rows: {total_existing}")

    ok = fail = 0
    if not args.skip_queued:
        ok, fail = migrate_queued(
            repo, client, embedder, args.src, dst_map, args.batch, args.embed_batch
        )
        log(f"Migrated queued rows: ok={ok} fail={fail}")

    # Close generator
    try:
        next(g)
    except StopIteration:
        pass

    log("Done.")
    # Return non-zero if any queued failed
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
