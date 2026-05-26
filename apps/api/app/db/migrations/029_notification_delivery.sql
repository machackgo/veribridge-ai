-- VeriBridge AI - Migration 029: Notification Delivery / Email Backend
--
-- Adds delivery tracking columns to notification_events so the backend can
-- queue, skip, retry, and record provider delivery state without requiring an
-- email provider in tests or development.

alter table public.notification_events
  add column if not exists delivery_attempts int not null default 0,
  add column if not exists last_attempted_at timestamptz,
  add column if not exists provider text,
  add column if not exists provider_message_id text,
  add column if not exists delivery_status text not null default 'pending',
  add column if not exists delivery_error text,
  add column if not exists scheduled_for timestamptz,
  add column if not exists delivered_at timestamptz;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'notification_events_delivery_status_check'
      and conrelid = 'public.notification_events'::regclass
  ) then
    alter table public.notification_events
      add constraint notification_events_delivery_status_check
      check (delivery_status in ('pending', 'queued', 'sent', 'skipped', 'failed', 'cancelled'));
  end if;
end $$;

create index if not exists notification_events_delivery_status_idx
  on public.notification_events (delivery_status);

create index if not exists notification_events_scheduled_for_idx
  on public.notification_events (scheduled_for);

create index if not exists notification_events_last_attempted_at_idx
  on public.notification_events (last_attempted_at);

create index if not exists notification_events_provider_idx
  on public.notification_events (provider);

create index if not exists notification_events_delivered_at_idx
  on public.notification_events (delivered_at);

