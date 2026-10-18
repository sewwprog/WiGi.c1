-- StoneLand II: run ONCE in your Supabase project's SQL Editor
-- IMMEDIATELY before creating the reserved admin account in the Auth Dashboard.
--
-- The signup trigger rejects the reserved SeWapro username as a precaution.
-- This temporary step must only be used during initial admin setup.
-- IMPORTANT: Do not leave the trigger disabled while publicly accepting signups.

alter table auth.users disable trigger sl2_on_auth_created;
