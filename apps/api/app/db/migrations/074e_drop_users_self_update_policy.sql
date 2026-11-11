-- 074e: remove direct self-updates of public.users (role self-escalation).
--
-- Migration 001 created "users: update own non-privileged fields" (UPDATE TO authenticated,
-- USING/WITH CHECK (auth.uid() = id)). Its comment says role/status must not change, but
-- neither the policy nor a trigger enforced that: a signed-in user could set their own
-- users.role to 'admin' through PostgREST, and the API's admin dependencies
-- (require_admin_user_id, require_admin_or_university_admin_user_id) trust users.role.
--
-- No client writes public.users with a user JWT: the API writes it with the service-role
-- client (BYPASSRLS). Dropping the policy makes RLS deny every direct UPDATE by anon and
-- authenticated; "users: select own row" is unchanged.
--
-- Idempotent.

begin;

drop policy if exists "users: update own non-privileged fields" on public.users;

commit;
