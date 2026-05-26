-- VeriBridge AI - Migration 024: Student Notification Center Backend
--
-- Expands notification_events from email placeholders into an in-app student
-- notification center. This migration does not send email.

alter table public.notification_events
  add column if not exists title text,
  add column if not exists message text,
  add column if not exists action_url text,
  add column if not exists action_label text,
  add column if not exists priority text not null default 'normal',
  add column if not exists category text not null default 'general',
  add column if not exists read_at timestamptz,
  add column if not exists archived_at timestamptz,
  add column if not exists dismissed_at timestamptz;

update public.notification_events
set
  title = coalesce(title, subject),
  message = coalesce(message, body)
where title is null
   or message is null;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'notification_events_priority_check'
      and conrelid = 'public.notification_events'::regclass
  ) then
    alter table public.notification_events
      add constraint notification_events_priority_check
      check (priority in ('low', 'normal', 'high', 'urgent'));
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'notification_events_category_check'
      and conrelid = 'public.notification_events'::regclass
  ) then
    alter table public.notification_events
      add constraint notification_events_category_check
      check (
        category in (
          'access_request',
          'access_decision',
          'verification',
          'ai_domain_review',
          'project_defense',
          'privacy',
          'passport',
          'system',
          'general'
        )
      );
  end if;
end $$;

create index if not exists notification_events_category_idx
  on public.notification_events (category);

create index if not exists notification_events_priority_idx
  on public.notification_events (priority);

create index if not exists notification_events_read_at_idx
  on public.notification_events (read_at);

create index if not exists notification_events_archived_at_idx
  on public.notification_events (archived_at);

drop policy if exists "notification_events: own row select"
  on public.notification_events;
create policy "notification_events: own row select"
  on public.notification_events for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "notification_events: own row update"
  on public.notification_events;
create policy "notification_events: own row update"
  on public.notification_events for update
  to authenticated
  using (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "notification_events: service role all"
  on public.notification_events;
create policy "notification_events: service role all"
  on public.notification_events for all
  to service_role
  using (true)
  with check (true);
