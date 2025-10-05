-- 030_portal_chroma_doc.sql (TBD)
BEGIN;

-- Chroma 送り込み用の完成ドキュメント（日本語ベース）
--  entity: 'field' | 'view_common'
--  natural_key: 上記と同一規則
--  lang: 'ja'（基本）/ 必要なら他言語も
CREATE TABLE IF NOT EXISTS public.portal_chroma_doc (
  id             bigserial PRIMARY KEY,
  entity         text   NOT NULL CHECK (entity IN ('field','view_common')),
  natural_key    text   NOT NULL,
  lang           text   NOT NULL DEFAULT 'ja',

  -- ドキュメントID（列合成の安定キー）※pgcrypto の digest() を使用
  doc_id         text   GENERATED ALWAYS AS (
                  encode(digest(entity || ':' || natural_key || ':' || lang, 'sha256'), 'hex')
                 ) STORED,

  doc_text       text   NOT NULL,
  meta           jsonb  NOT NULL DEFAULT '{}'::jsonb,   -- モデル名/テーブル名/フィールド名/アクションxmlid 等
  source_hash    text   NOT NULL,                       -- 元テキストのハッシュ（翻訳/整形の元が同一か検知）
  collection     text   NOT NULL,                       -- Chroma コレクション名（例: portal_field_ja）
  state          text   NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','upserted','failed')),
  last_error     text,

  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_chroma_doc_unique UNIQUE (entity, natural_key, lang)
);

CREATE INDEX IF NOT EXISTS idx_chroma_doc_state       ON public.portal_chroma_doc(state);
CREATE INDEX IF NOT EXISTS idx_chroma_doc_collection  ON public.portal_chroma_doc(collection);
CREATE INDEX IF NOT EXISTS idx_chroma_doc_docid       ON public.portal_chroma_doc(doc_id);

DROP TRIGGER IF EXISTS trg_touch_portal_chroma_doc ON public.portal_chroma_doc;
CREATE TRIGGER trg_touch_portal_chroma_doc
BEFORE UPDATE ON public.portal_chroma_doc
FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();

COMMIT;
