-- StoneLand II: run IMMEDIATELY after creating the administrator in Auth > Users
-- using email sewapro@stoneland.invalid, a NEW strong password, and auto-confirmed email.
-- This restores the signup trigger even if the admin user was not created.

alter table auth.users enable trigger sl2_on_auth_created;

-- If the Auth user does not exist yet, the inserts below simply affect zero rows.
-- The trigger is still re-enabled; no exception or rollback is caused.

insert into public.sl2_profiles (id, username, created_at)
select id, 'sewapro', created_at
from auth.users
where lower(email) = 'sewapro@stoneland.invalid'
on conflict (id) do update set username=excluded.username;

insert into public.sl2_admins (user_id)
select id from auth.users where lower(email) = 'sewapro@stoneland.invalid'
on conflict (user_id) do nothing;

-- Verify: should return exactly 1 row and show the correct username.
select p.username, a.created_at as admin_since
from public.sl2_admins a
join public.sl2_profiles p on p.id=a.user_id
where p.username='sewapro';
