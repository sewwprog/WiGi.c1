-- Applied to StoneLand II Supabase on 2026-10-18.
-- Rate limit the public self-service signup Edge Function.
create table if not exists sl2_private.signup_limits (
  bucket text primary key,
  attempts integer not null default 0,
  period_started timestamptz not null default now()
);
revoke all on sl2_private.signup_limits from public,anon,authenticated;

create or replace function public.sl2_signup_quota(bucket_hash text)
returns boolean language plpgsql security definer set search_path = ''
as $$
declare attempts_now integer;
begin
  if bucket_hash is null or bucket_hash !~ '^[0-9a-f]{64}$' then
    return false;
  end if;
  insert into sl2_private.signup_limits as limiter (bucket, attempts, period_started)
  values (bucket_hash, 1, now())
  on conflict (bucket)
  do update set
     attempts = case when limiter.period_started < now() - interval '1 hour'
                then 1 else limiter.attempts + 1 end,
     period_started = case when limiter.period_started < now() - interval '1 hour'
                      then now() else limiter.period_started end
  returning attempts into attempts_now;
  return attempts_now <= 5;
end;
$$;
revoke all on function public.sl2_signup_quota(text) from public,anon,authenticated;
grant execute on function public.sl2_signup_quota(text) to service_role;
