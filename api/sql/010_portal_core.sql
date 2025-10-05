-- 010_portal_core.sql (TBD)
BEGIN;

------------------------------------------------------------
-- 1) コア: モデル
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.portal_model (
  id           bigserial PRIMARY KEY,
  model        text        NOT NULL UNIQUE, -- 例: 'sale.order'
  model_table  text        NOT NULL,        -- 例: 'sale_order'
  label_i18n   jsonb       NOT NULL DEFAULT '{}'::jsonb,
  notes        text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_portal_model_model_table ON public.portal_model(model_table);

DROP TRIGGER IF EXISTS trg_touch_portal_model ON public.portal_model;
CREATE TRIGGER trg_touch_portal_model
BEFORE UPDATE ON public.portal_model
FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();

------------------------------------------------------------
-- 2) フィールド定義（日本語列を含む）
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.portal_fields (
  id                 bigserial PRIMARY KEY,
  model_id           bigint      REFERENCES public.portal_model(id) ON DELETE CASCADE,
  model              text        NOT NULL,              -- 技術名
  model_table        text        NOT NULL,              -- 物理名
  field_name         text        NOT NULL,              -- 技術名（英語）
  ttype              text        NOT NULL,              -- char, integer, json, many2one...
  label_i18n         jsonb       NOT NULL DEFAULT '{}'::jsonb,
  code_status        text,
  notes              text,
  origin             text        DEFAULT 'portal',
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  -- 既存運用互換の日本語列
  "モデル技術名"       text        NOT NULL DEFAULT '',
  "モデル物理名"       text        NOT NULL DEFAULT '',
  "フィールド技術名"   text        NOT NULL DEFAULT '',
  "データ型"           text        NOT NULL DEFAULT '文字列'
);

-- 日本語データ型のチェック制約（広めに許容）
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'ck_ttype_jp'
       AND conrelid = 'public.portal_fields'::regclass
  ) THEN
    ALTER TABLE public.portal_fields
      ADD CONSTRAINT ck_ttype_jp CHECK (
        "データ型" IN (
          '文字列','テキスト','長文',
          '整数','数値','小数','実数',
          '真偽','ブール','論理値',
          '日付','日時','タイムスタンプ',
          'JSON','構造化',
          '参照','外部キー',
          '複数参照','1対多','多対多'
        )
      );
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_portal_fields_model     ON public.portal_fields(model);
CREATE INDEX IF NOT EXISTS idx_portal_fields_model_id  ON public.portal_fields(model_id);
CREATE INDEX IF NOT EXISTS idx_portal_fields_fieldname ON public.portal_fields(field_name);

DROP TRIGGER IF EXISTS trg_touch_portal_fields ON public.portal_fields;
CREATE TRIGGER trg_touch_portal_fields
BEFORE UPDATE ON public.portal_fields
FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();

------------------------------------------------------------
-- 3) ビュー定義（action-centric: portal_view_common + portal_view）
------------------------------------------------------------
-- portal_view_common（action_xmlid を業務キー、view_types は text[]）
CREATE TABLE IF NOT EXISTS public.portal_view_common (
  id                   bigserial PRIMARY KEY,

  -- ir_view_src 由来
  action_xmlid         text      NOT NULL,
  action_id            bigint,
  action_name          text,
  model_label          text,
  model_tech           text,
  model_table          text,
  view_types           text[]    NOT NULL DEFAULT ARRAY[]::text[],
  primary_view_type    text,
  help_i18n_html       jsonb     NOT NULL DEFAULT '{}'::jsonb,
  help_ja_html         text,
  help_ja_text         text,
  help_en_html         text,
  help_en_text         text,
  view_mode            text,
  context              jsonb,
  domain               jsonb,

  -- 共通UI
  display_fields       jsonb     NOT NULL DEFAULT '[]'::jsonb,
  sort_field           text,
  sort_dir             text      NOT NULL DEFAULT 'asc',
  default_group_by     text,
  default_filters      jsonb     NOT NULL DEFAULT '{}'::jsonb,

  -- AI向けメタ
  ai_purpose           text,
  ai_purpose_i18n      jsonb     NOT NULL DEFAULT '{}'::jsonb,

  -- 作成挙動
  creation_mode        text      NOT NULL DEFAULT 'open_new_page',
  default_values       text,
  allow_duplicate      boolean   NOT NULL DEFAULT false,
  enable_archive       boolean   NOT NULL DEFAULT true,

  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_pvc_action_xmlid UNIQUE (action_xmlid),
  CONSTRAINT ck_pvc_sort_dir CHECK (sort_dir IN ('asc','desc')),
  CONSTRAINT ck_pvc_creation_mode CHECK (creation_mode IN ('open_new_page','inline_create','modal_create','quick_create'))
);
CREATE INDEX IF NOT EXISTS idx_pvc_model_tech ON public.portal_view_common(model_tech);

DROP TRIGGER IF EXISTS trg_touch_portal_view_common ON public.portal_view_common;
CREATE TRIGGER trg_touch_portal_view_common
BEFORE UPDATE ON public.portal_view_common
FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();

-- portal_view（view_typeごとの詳細設定。calendar_*_field は text で運用）
CREATE TABLE IF NOT EXISTS public.portal_view (
  id                         bigserial PRIMARY KEY,
  common_id                  bigint NOT NULL REFERENCES public.portal_view_common(id) ON DELETE CASCADE,
  view_type                  text   NOT NULL,
  -- 共通
  view_name                  text,
  model                      text,
  priority_num               integer,
  enabled                    boolean NOT NULL DEFAULT true,
  is_primary                 boolean NOT NULL DEFAULT false,

  -- Form
  form_show_header           boolean,
  form_show_footer           boolean,

  -- Kanban
  kanban_default_group_by    text,
  kanban_quick_create        boolean,
  kanban_draggable_field     text,

  -- List
  list_inline_edit           boolean,
  list_export_button         boolean,
  list_page_size             integer,

  -- Calendar（フィールド名を text で保持）
  calendar_start_field       text,
  calendar_end_field         text,
  calendar_color_field       text,
  calendar_default_view      text,

  -- Search
  search_fields              jsonb,
  search_filters             jsonb,
  search_group_by_filters    jsonb,

  -- Graph
  graph_type                 text,
  graph_measure_fields       jsonb,
  graph_row_group_by         text,
  graph_col_group_by         text,
  graph_stacked              boolean,

  -- Pivot
  pivot_measures             jsonb,
  pivot_rows                 jsonb,
  pivot_cols                 jsonb,
  pivot_show_totals          boolean,

  -- Dashboard
  dashboard_layout           jsonb,
  dashboard_widgets          jsonb,
  dashboard_refresh_secs     integer,

  -- Tree
  tree_parent_field          text,
  tree_expand_all            boolean,

  -- Map
  map_lat_field              text,
  map_lng_field              text,
  map_address_field          text,
  map_color_field            text,
  map_cluster                boolean,
  map_default_zoom           integer,

  created_at                 timestamptz NOT NULL DEFAULT now(),
  updated_at                 timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_pv_common_viewtype UNIQUE (common_id, view_type),
  CONSTRAINT ck_pv_view_type CHECK (
    view_type IN (
      'form','kanban','list','calendar','search','graph','pivot','dashboard','tree','map'
    )
  ),
  CONSTRAINT ck_pv_calendar_default_view CHECK (
    calendar_default_view IS NULL OR calendar_default_view IN ('month','week','day')
  )
);
CREATE INDEX IF NOT EXISTS idx_pv_common_id ON public.portal_view(common_id);
CREATE INDEX IF NOT EXISTS idx_pv_view_type  ON public.portal_view(view_type);

DROP TRIGGER IF EXISTS trg_touch_portal_view ON public.portal_view;
CREATE TRIGGER trg_touch_portal_view
BEFORE UPDATE ON public.portal_view
FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();

-- is_primary を common_id 内で単一化
CREATE OR REPLACE FUNCTION public.tg_enforce_single_primary_per_common()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.is_primary THEN
    UPDATE public.portal_view
       SET is_primary = false, updated_at = now()
     WHERE common_id = NEW.common_id
       AND id <> NEW.id
       AND is_primary = true;
  END IF;
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_single_primary_per_common ON public.portal_view;
CREATE TRIGGER trg_single_primary_per_common
BEFORE INSERT OR UPDATE OF is_primary, common_id ON public.portal_view
FOR EACH ROW EXECUTE FUNCTION public.tg_enforce_single_primary_per_common();

------------------------------------------------------------
-- 4) タブ
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.portal_tab_portal (
  id                  bigserial PRIMARY KEY,
  view_id             bigint NOT NULL REFERENCES public.portal_view(id) ON DELETE CASCADE,
  model               text,                       -- ★ 追加（モデル名保持）
  tab_key             text   NOT NULL,
  page_idx            integer NOT NULL DEFAULT 10,
  tab_label_ja        text,
  tab_label_en        text,
  child_model         text,
  child_link_field    text,
  origin              text,
  module              text,
  is_codegen_target   boolean DEFAULT false,
  notes               text,
  github_url          text,
  view_mode           text,
  tree_view_xmlid     text,
  form_view_xmlid     text,
  subview_policy_tree text,
  subview_policy_form text,
  use_domain          boolean,
  domain_raw          text,
  use_context         boolean,
  context_raw         text,
  inline_edit         boolean,
  allow_create_rows   boolean,
  allow_delete_rows   boolean,
  options_raw         jsonb,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_portal_tab_portal_view_tab UNIQUE(view_id, tab_key)
);
CREATE INDEX IF NOT EXISTS idx_portal_tab_portal_view  ON public.portal_tab_portal(view_id);
CREATE INDEX IF NOT EXISTS idx_portal_tab_portal_model ON public.portal_tab_portal(model);

DROP TRIGGER IF EXISTS trg_touch_portal_tab_portal ON public.portal_tab_portal;
CREATE TRIGGER trg_touch_portal_tab_portal
BEFORE UPDATE ON public.portal_tab_portal
FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();

------------------------------------------------------------
-- 5) スマートボタン
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.portal_smart_button (
  id                 bigserial PRIMARY KEY,
  view_id            bigint  NOT NULL REFERENCES public.portal_view(id) ON DELETE CASCADE,
  model              text,                       -- ★ 追加（モデル名保持）
  label_i18n         jsonb   NOT NULL DEFAULT '{}'::jsonb,
  button_key         text    NOT NULL,
  target_model       text,
  origin             text,
  action_type        text,
  action_ref         text,
  target             text,
  show_count         boolean,
  sequence           integer,
  notes              text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  notes_i18n         jsonb,
  view_xmlid         text,
  cached_ui_view_id  bigint,
  dest_view_url      text,
  is_codegen_target  boolean,
  show_in_inspection boolean,
  groups             jsonb,
  badge_count_expr   text,
  domain             jsonb,
  context            jsonb,
  CONSTRAINT uq_portal_smart_button_view_key UNIQUE(view_id, button_key)
);
CREATE INDEX IF NOT EXISTS idx_portal_smart_button_view  ON public.portal_smart_button(view_id);
CREATE INDEX IF NOT EXISTS idx_portal_smart_button_model ON public.portal_smart_button(model);

DROP TRIGGER IF EXISTS trg_touch_portal_smart_button ON public.portal_smart_button;
CREATE TRIGGER trg_touch_portal_smart_button
BEFORE UPDATE ON public.portal_smart_button
FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();

------------------------------------------------------------
-- 6) メニュー（軽量）
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.portal_menu (
  id           bigserial PRIMARY KEY,
  menu_key     text    NOT NULL,                    -- 業務キー
  label_i18n   jsonb   NOT NULL DEFAULT '{}'::jsonb,
  parent_key   text,
  model        text,                                 -- ★ モデル名
  common_id    bigint   REFERENCES public.portal_view_common(id) ON DELETE SET NULL, -- 紐付け任意
  sequence     integer,
  enabled      boolean  NOT NULL DEFAULT true,
  notes        text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_portal_menu_key UNIQUE(menu_key)
);
CREATE INDEX IF NOT EXISTS idx_portal_menu_parent ON public.portal_menu(parent_key);
CREATE INDEX IF NOT EXISTS idx_portal_menu_model  ON public.portal_menu(model);

DROP TRIGGER IF EXISTS trg_touch_portal_menu ON public.portal_menu;
CREATE TRIGGER trg_touch_portal_menu
BEFORE UPDATE ON public.portal_menu
FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();

COMMIT;
