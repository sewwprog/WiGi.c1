-- Applied to StoneLand II Supabase on 2026-10-18.
-- One-time invitation for reserved "SeWapro" account.
-- Tokens are generated in the database, never stored in this repository.
create table if not exists sl2_private.admin_invitations (
  code_hash text primary key,
  expires_at timestamptz not null,
  claimed_at timestamptz
);
revoke all on sl2_private.admin_invitations from public, anon, authenticated;

create or replace function sl2_private.on_auth_user_created()
returns trigger language plpgsql security definer set search_path = ''
as $$
declare nick text; invite_hash text; accepted_hash text;
begin
  if new.email is null or lower(new.email) not like '%@stoneland.invalid' then
    return new;
  end if;
  nick := lower(split_part(new.email,'@',1));
  if nick !~ '^[a-z][a-z0-9_]{2,19}$' then
    raise exception 'Invalid StoneLand username';
  end if;
  if nick = 'sewapro' then
    if length(coalesce(new.raw_user_meta_data->>'sl2_activation','')) != 48 then
      raise exception 'SeWapro requires an activation code';
    end if;
    invite_hash := encode(extensions.digest(new.raw_user_meta_data->>'sl2_activation','sha256'),'hex');
    update sl2_private.admin_invitations
      set claimed_at=now()
      where code_hash=invite_hash and claimed_at is null and expires_at>now()
      returning code_hash into accepted_hash;
    if accepted_hash is null then
      raise exception 'Invalid or used StoneLand activation code';
    end if;
  end if;
  insert into public.sl2_profiles (id,username) values (new.id,nick);
  if nick = 'sewapro' then
    insert into public.sl2_admins (user_id) values (new.id);
  end if;
  return new;
end;
$$;
revoke all on function sl2_private.on_auth_user_created() from public,anon,authenticated;
