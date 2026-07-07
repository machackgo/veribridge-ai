-- ============================================================
-- VeriBridge AI — Migration 054: Passport Card profile photo
--
-- Adds a recruiter-safe profile photo to the Verified Work Passport /
-- Passport Card. Two parts:
--
--   1. student_onboarding_profiles.avatar_url — the PUBLIC URL of the
--      candidate's chosen profile photo (or NULL). Only ever a public,
--      non-signed storage URL; the passport service additionally sanitizes
--      it before it reaches any surface.
--
--   2. A PUBLIC Supabase Storage bucket `passport-avatars` with per-user
--      write isolation. Objects live under a `<auth.uid()>/…` prefix so a
--      student can only write/replace/delete their OWN avatar, while anyone
--      may read (the photo is deliberately public — it appears on the public
--      Passport Card). No signed URLs are ever needed or stored.
--
-- Safe to run more than once (idempotent guards throughout).
-- ============================================================

-- ── 1. Profile photo URL column ─────────────────────────────
alter table public.student_onboarding_profiles
  add column if not exists avatar_url text;

-- ── 2. Public storage bucket for passport avatars ───────────
-- `public = true` → objects are readable via a plain public URL (no token),
-- which is exactly what the recruiter-safe Passport Card needs.
insert into storage.buckets (id, name, public)
values ('passport-avatars', 'passport-avatars', true)
on conflict (id) do update set public = true;

-- ── 3. Storage RLS: per-user write isolation, public read ───
-- The first path segment must equal the caller's auth uid, so a student can
-- only ever create/replace/delete objects under their own folder.

drop policy if exists "passport-avatars: public read" on storage.objects;
create policy "passport-avatars: public read"
  on storage.objects for select
  using (bucket_id = 'passport-avatars');

drop policy if exists "passport-avatars: owner insert" on storage.objects;
create policy "passport-avatars: owner insert"
  on storage.objects for insert
  to authenticated
  with check (
    bucket_id = 'passport-avatars'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

drop policy if exists "passport-avatars: owner update" on storage.objects;
create policy "passport-avatars: owner update"
  on storage.objects for update
  to authenticated
  using (
    bucket_id = 'passport-avatars'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  )
  with check (
    bucket_id = 'passport-avatars'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

drop policy if exists "passport-avatars: owner delete" on storage.objects;
create policy "passport-avatars: owner delete"
  on storage.objects for delete
  to authenticated
  using (
    bucket_id = 'passport-avatars'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );
