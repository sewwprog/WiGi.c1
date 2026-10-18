-- STONELAND II — DEDICATED PROJECT (spfpwknvesclrmjcbwce)
-- Run once to create the application schema with RLS.
-- Usernames are internal aliases based on @stoneland.invalid.
-- Admin account is set up separately (see supabase/bootstrap-admin.sql).
-- Disable Confirm Email through Supabase Auth settings for username-only signup.
-- NEVER put passwords or service-role keys in source control.

create schema if not exists sl2_private;
revoke all on schema sl2_private from public, anon, authenticated;

create table if not exists public.sl2_profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text not null unique check (username ~ '^[a-z][a-z0-9_]{2,19}$'),
  created_at timestamptz not null default now()
);
create table if not exists public.sl2_admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);
create table if not exists public.sl2_posts (
  id uuid primary key default gen_random_uuid(),
  author_id uuid not null references auth.users(id),
  title text not null check (char_length(trim(title)) between 1 and 100),
  body text not null check (char_length(trim(body)) between 1 and 5000),
  created_at timestamptz not null default now()
);
create table if not exists public.sl2_photos (
  id uuid primary key default gen_random_uuid(),
  author_id uuid not null references auth.users(id),
  title text not null check (char_length(trim(title)) between 1 and 100),
  path text not null unique,
  created_at timestamptz not null default now()
);
create index if not exists sl2_posts_created_idx on public.sl2_posts(created_at desc);
create index if not exists sl2_photos_created_idx on public.sl2_photos(created_at desc);
create index if not exists sl2_profiles_created_idx on public.sl2_profiles(created_at desc);

alter table public.sl2_profiles enable row level security;
alter table public.sl2_admins enable row level security;
alter table public.sl2_posts enable row level security;
alter table public.sl2_photos enable row level security;

-- Newly created tables may not be exposed automatically on recent Supabase projects.
grant usage on schema public to anon, authenticated;
grant select on public.sl2_profiles, public.sl2_posts, public.sl2_photos to anon, authenticated;
grant select on public.sl2_admins to authenticated;
grant insert, update, delete on public.sl2_posts, public.sl2_photos to authenticated;
revoke insert, update, delete on public.sl2_profiles, public.sl2_admins from anon, authenticated;

drop policy if exists sl2_profiles_read on public.sl2_profiles;
create policy sl2_profiles_read on public.sl2_profiles for select to anon, authenticated using (true);
drop policy if exists sl2_admins_self_read on public.sl2_admins;
create policy sl2_admins_self_read on public.sl2_admins for select to authenticated
using (user_id = (select auth.uid()));

drop policy if exists sl2_posts_read on public.sl2_posts;
create policy sl2_posts_read on public.sl2_posts for select to anon, authenticated using (true);
drop policy if exists sl2_posts_insert on public.sl2_posts;
create policy sl2_posts_insert on public.sl2_posts for insert to authenticated
with check (author_id = (select auth.uid()) and exists (
  select 1 from public.sl2_admins where user_id = (select auth.uid())
));
drop policy if exists sl2_posts_update on public.sl2_posts;
create policy sl2_posts_update on public.sl2_posts for update to authenticated
using (exists(select 1 from public.sl2_admins where user_id = (select auth.uid())))
with check (exists(select 1 from public.sl2_admins where user_id = (select auth.uid())));
drop policy if exists sl2_posts_delete on public.sl2_posts;
create policy sl2_posts_delete on public.sl2_posts for delete to authenticated
using (exists(select 1 from public.sl2_admins where user_id = (select auth.uid())));

drop policy if exists sl2_photos_read on public.sl2_photos;
create policy sl2_photos_read on public.sl2_photos for select to anon, authenticated using (true);
drop policy if exists sl2_photos_insert on public.sl2_photos;
create policy sl2_photos_insert on public.sl2_photos for insert to authenticated
with check (author_id = (select auth.uid()) and
            path like (auth.uid()::text || '/%') and
            exists(select 1 from public.sl2_admins where user_id = (select auth.uid())));
drop policy if exists sl2_photos_update on public.sl2_photos;
create policy sl2_photos_update on public.sl2_photos for update to authenticated
using (exists(select 1 from public.sl2_admins where user_id = (select auth.uid())))
with check (exists(select 1 from public.sl2_admins where user_id = (select auth.uid())));
drop policy if exists sl2_photos_delete on public.sl2_photos;
create policy sl2_photos_delete on public.sl2_photos for delete to authenticated
using (exists(select 1 from public.sl2_admins where user_id = (select auth.uid())));

-- Safe Auth trigger: maintains server-owned usernames and reserves admin login.
create or replace function sl2_private.on_auth_user_created()
returns trigger language plpgsql security definer set search_path = ''
as $$
declare nick text;
begin
  if new.email is null or lower(new.email) not like '%@stoneland.invalid' then
    return new;
  end if;
  nick := lower(split_part(new.email,'@',1));
  if nick = 'sewapro' then
    raise exception 'This username is reserved';
  end if;
  if nick !~ '^[a-z][a-z0-9_]{2,19}$' then
    raise exception 'Invalid StoneLand username';
  end if;
  insert into public.sl2_profiles (id,username) values (new.id,nick);
  return new;
end;
$$;
revoke all on function sl2_private.on_auth_user_created() from public, anon, authenticated;
drop trigger if exists sl2_on_auth_created on auth.users;
create trigger sl2_on_auth_created after insert on auth.users
for each row execute function sl2_private.on_auth_user_created();

-- A publicly readable bucket: uploaded Minecraft screenshots are public, writes are admin-only.
insert into storage.buckets (id,name,public,file_size_limit,allowed_mime_types)
values ('sl2-gallery','sl2-gallery',true,5242880,array['image/jpeg','image/png','image/webp'])
on conflict (id) do update set public=true,file_size_limit=5242880,
 allowed_mime_types=array['image/jpeg','image/png','image/webp'];

drop policy if exists sl2_gallery_read on storage.objects;
create policy sl2_gallery_read on storage.objects for select to anon, authenticated
using (bucket_id='sl2-gallery');
drop policy if exists sl2_gallery_upload on storage.objects;
create policy sl2_gallery_upload on storage.objects for insert to authenticated
with check (bucket_id='sl2-gallery' and split_part(name,'/',1) = (select auth.uid())::text
and exists(select 1 from public.sl2_admins where user_id = (select auth.uid())));
drop policy if exists sl2_gallery_delete on storage.objects;
create policy sl2_gallery_delete on storage.objects for delete to authenticated
using (bucket_id='sl2-gallery' and exists(select 1 from public.sl2_admins where user_id = (select auth.uid())));
