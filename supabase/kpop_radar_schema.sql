-- K-pop Radar MVP schema.
-- Run this in Supabase SQL editor before enabling the LINE Bot integration.

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  line_user_id text unique not null,
  display_name text,
  picture_url text,
  created_at timestamptz default now()
);

create table if not exists user_preferences (
  id uuid primary key default gen_random_uuid(),
  line_user_id text unique not null
    references users(line_user_id) on delete cascade,
  preferred_gender text not null default 'all'
    check (preferred_gender in ('girl_group','boy_group','all')),
  updated_at timestamptz default now()
);

create table if not exists kpop_items (
  id uuid primary key default gen_random_uuid(),
  item_type text not null
    check (item_type in ('mv','fancam','photo')),
  gender_category text not null
    check (gender_category in ('girl_group','boy_group','solo','mixed')),
  artist text not null,
  member text,
  title text not null,
  url text not null,
  thumbnail_url text,
  source text,
  created_at timestamptz default now()
);

create table if not exists user_saved_items (
  id uuid primary key default gen_random_uuid(),
  line_user_id text not null
    references users(line_user_id) on delete cascade,
  item_id uuid not null references kpop_items(id) on delete cascade,
  item_type text not null,
  created_at timestamptz default now(),
  unique(line_user_id, item_id)
);

create table if not exists user_draw_history (
  id uuid primary key default gen_random_uuid(),
  line_user_id text not null
    references users(line_user_id) on delete cascade,
  item_id uuid not null references kpop_items(id) on delete cascade,
  item_type text not null,
  source_feature text,
  created_at timestamptz default now(),
  unique(line_user_id, item_id, source_feature)
);

create index if not exists idx_kpop_items_type_gender
  on kpop_items (item_type, gender_category);

create index if not exists idx_saved_user_type
  on user_saved_items (line_user_id, item_type);

create index if not exists idx_draw_user_feature
  on user_draw_history (line_user_id, source_feature);
