BEGIN;

-- 旧スタイルの一意制約があれば落とす（無ければスキップ）
ALTER TABLE public.portal_translate
  DROP CONSTRAINT IF EXISTS uq_translate_uniqueness;

-- uq_translate_nk 制約が未作成なら作る（既存を尊重）
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM pg_constraint c
      JOIN pg_class r ON r.oid = c.conrelid
      JOIN pg_namespace n ON n.oid = r.relnamespace
     WHERE c.conname = 'uq_translate_nk'
       AND n.nspname = 'public'
       AND r.relname = 'portal_translate'
  ) THEN
    -- 既に同名インデックスがあるか？
    IF EXISTS (
      SELECT 1
        FROM pg_class i
        JOIN pg_namespace n ON n.oid = i.relnamespace
       WHERE i.relkind = 'i'
         AND n.nspname = 'public'
         AND i.relname = 'uq_translate_nk'
    ) THEN
      -- 既存の uq_translate_nk インデックスを制約として採用
      ALTER TABLE public.portal_translate
        ADD CONSTRAINT uq_translate_nk UNIQUE USING INDEX uq_translate_nk;

    ELSE
      -- 中立名のユニークインデックスを作成（なければ）
      CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_translate_nk
        ON public.portal_translate(entity, natural_key, src_lang, tgt_lang);

      -- そのインデックスを制約として採用
      ALTER TABLE public.portal_translate
        ADD CONSTRAINT uq_translate_nk UNIQUE USING INDEX idx_portal_translate_nk;
    END IF;
  END IF;
END$$;

-- ハッシュ検索用の補助インデックス（冪等）
CREATE INDEX IF NOT EXISTS idx_translate_source_hash
  ON public.portal_translate(source_hash);

COMMIT;
