-- 074c: remove two production-only ("drift") policies on the evidence-access tables.
--
-- Production verification (2026-11-10) found these policies in production although no migration creates them:
--   evidence_access_grants  "Public can read access grants by token"  — SELECT to anon, authenticated with a predicate
--     that never checks a token, exposing every active grant row (legacy plaintext access_token, requester_email).
--   evidence_access_requests "Public can create evidence access requests" — INSERT to anon, authenticated WITH CHECK (true).
-- The API uses the service-role client for both tables; web and extension never query them. Recording the drops here
-- keeps the migration chain and production in agreement and prevents a rebuild from reintroducing them.
-- Idempotent (if exists); a no-op on environments built from migrations.
begin;
set local lock_timeout = '5s';
drop policy if exists "Public can read access grants by token" on public.evidence_access_grants;
drop policy if exists "Public can create evidence access requests" on public.evidence_access_requests;
commit;
