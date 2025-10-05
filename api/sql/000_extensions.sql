BEGIN;

-- 必要拡張
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- updated_at を自動更新する共通トリガ関数
CREATE OR REPLACE FUNCTION public.tg_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END
$$;

-- （任意ユーティリティ）日本語データ型ラベル選定補助
--  portal_fields の ck_ttype_jp と整合させたい時に利用
CREATE OR REPLACE FUNCTION public._pick_jp_datatype_label(p_ttype text)
RETURNS text
LANGUAGE plpgsql STABLE
AS $$
DECLARE
  allowed text[];
  cand    text[];
  v       text;
BEGIN
  SELECT array_agg(m[1]) INTO allowed
  FROM pg_constraint c
  CROSS JOIN LATERAL regexp_matches(pg_get_constraintdef(c.oid), '''([^'']+)''', 'g') AS m
  WHERE c.conname = 'ck_ttype_jp'
    AND c.conrelid = 'public.portal_fields'::regclass;

  IF allowed IS NULL OR array_length(allowed,1) IS NULL THEN
    RETURN '文字列';
  END IF;

  p_ttype := lower(coalesce(p_ttype,''));
  cand := CASE p_ttype
    WHEN 'char'      THEN ARRAY['テキスト','文字列','文字','テキスト型','文字列型']
    WHEN 'text'      THEN ARRAY['テキスト','長文','文字列']
    WHEN 'integer'   THEN ARRAY['整数','数値','整数型']
    WHEN 'float'     THEN ARRAY['小数','実数','浮動小数点']
    WHEN 'boolean'   THEN ARRAY['真偽','ブール','論理値']
    WHEN 'date'      THEN ARRAY['日付']
    WHEN 'datetime'  THEN ARRAY['日時','タイムスタンプ']
    WHEN 'json'      THEN ARRAY['JSON','構造化']
    WHEN 'many2one'  THEN ARRAY['参照','外部キー']
    WHEN 'one2many'  THEN ARRAY['複数参照','1対多']
    WHEN 'many2many' THEN ARRAY['多対多']
    ELSE ARRAY['テキスト','文字列']
  END;

  FOREACH v IN ARRAY cand LOOP
    IF v = ANY(allowed) THEN
      RETURN v;
    END IF;
  END LOOP;
  RETURN allowed[1];
END
$$;

COMMIT;
