-- 020_portal_translate.sql (Phase E finalized)
BEGIN;

CREATE TABLE IF NOT EXISTS public.portal_translate (
  id              bigserial PRIMARY KEY,
  entity          text      NOT NULL CHECK (entity IN ('field','view_common')),
  natural_key     text      NOT NULL,
  src_lang        text      NOT NULL DEFAULT 'ja_JP',
  tgt_lang        text      NOT NULL DEFAULT 'en_US',
  source_text     text      NOT NULL,
  translated_text text,
  source_hash     text      NOT NULL,
  state           text      NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','translated','failed')),
  last_error      text,
  model           text,
  model_table     text,
  metadata        jsonb     NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

-- 旧ユニークキー（source_hash を含む）があれば削除
ALTER TABLE public.portal_translate
  DROP CONSTRAINT IF EXISTS uq_translate_uniqueness;

-- 新ユニークキー（最新版のみ保持の方針）
ALTER TABLE public.portal_translate
  ADD CONSTRAINT uq_translate_nk UNIQUE (entity, natural_key, src_lang, tgt_lang);

-- インデックス（検索・重複検知の補助）
CREATE INDEX IF NOT EXISTS idx_translate_source_hash ON public.portal_translate(source_hash);
CREATE INDEX IF NOT EXISTS idx_translate_state       ON public.portal_translate(state);
CREATE INDEX IF NOT EXISTS idx_translate_entity_key  ON public.portal_translate(entity, natural_key);

DROP TRIGGER IF EXISTS trg_touch_portal_translate ON public.portal_translate;
CREATE TRIGGER trg_touch_portal_translate
BEFORE UPDATE ON public.portal_translate
FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();

COMMIT;
