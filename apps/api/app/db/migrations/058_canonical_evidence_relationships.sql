-- ============================================================
-- VeriBridge AI — Migration 058: Canonical Evidence Relationships
--
-- Adds the two normalized edges that the existing proof/report tables lack:
--   project -> skill claim
--   proof -> project relationship
-- and a durable, citation-bearing claim -> evidence link.
--
-- Existing source rows remain authoritative and are never rewritten. Legacy
-- evidence is classified, not guessed. The application remains read-compatible
-- before this migration is deployed by also reading explicit project metadata
-- from existing proof sessions and proof_artifacts.
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists public.vbr_project_skill_claims (
  id                  uuid primary key default gen_random_uuid(),
  project_id          uuid not null references public.vbr_projects (id) on delete cascade,
  skill_key           text not null,
  skill_name          text not null,
  claim_text          text not null,
  claim_state         text not null default 'claimed'
                        check (claim_state in ('claimed', 'confirmed', 'withdrawn')),
  evidence_status     text not null default 'not_assessed'
                        check (evidence_status in (
                          'demonstrated',
                          'partially_demonstrated',
                          'not_assessed',
                          'insufficient_evidence',
                          'inconsistency_noted'
                        )),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (project_id, skill_key)
);

create index if not exists vbr_project_skill_claims_project_idx
  on public.vbr_project_skill_claims (project_id);

-- PostgreSQL requires a unique target for the composite ownership foreign keys
-- below. ``id`` is already the primary key; this additive index makes the
-- project+owner pair a valid FK target without rewriting any project row.
create unique index if not exists vbr_projects_id_user_unique_idx
  on public.vbr_projects (id, user_id);

create table if not exists public.proof_project_relationships (
  id                  uuid primary key default gen_random_uuid(),
  owner_user_id       uuid not null references public.users (id) on delete cascade,
  proof_type          text not null
                        check (proof_type in ('github', 'website', 'document', 'project_defense', 'video')),
  proof_id            text not null,
  project_id          uuid references public.vbr_projects (id) on delete cascade,
  relationship_state  text not null
                        check (relationship_state in (
                          'directly_linked',
                          'suggested_match',
                          'mismatched_project',
                          'vault_only',
                          'legacy_unresolved'
                        )),
  match_method        text not null default 'legacy'
                        check (match_method in (
                          'explicit_project_id',
                          'proof_session_project_id',
                          'artifact_project_id',
                          'repository_relationship',
                          'website_domain_relationship',
                          'project_title_relationship',
                          'proof_objective_relationship',
                          'user_confirmation',
                          'legacy'
                        )),
  confirmed_by_user   boolean not null default false,
  provenance          jsonb not null default '{}',
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  constraint proof_project_relationships_project_state_ck check (
    (relationship_state = 'vault_only' and project_id is null)
    or (
      relationship_state in ('directly_linked', 'suggested_match', 'mismatched_project')
      and project_id is not null
    )
    or relationship_state = 'legacy_unresolved'
  ),
  constraint proof_project_relationships_owner_project_fk
    foreign key (project_id, owner_user_id)
    references public.vbr_projects (id, user_id)
    on delete cascade
);

-- ``create table if not exists`` is not enough for a partially-created schema:
-- add the integrity constraints when the table pre-existed an interrupted run.
-- NOT VALID avoids rewriting or rejecting historical rows while still enforcing
-- each new/updated relationship.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'proof_project_relationships_project_state_ck'
      and conrelid = 'public.proof_project_relationships'::regclass
  ) then
    alter table public.proof_project_relationships
      add constraint proof_project_relationships_project_state_ck
      check (
        (relationship_state = 'vault_only' and project_id is null)
        or (
          relationship_state in ('directly_linked', 'suggested_match', 'mismatched_project')
          and project_id is not null
        )
        or relationship_state = 'legacy_unresolved'
      ) not valid;
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'proof_project_relationships_owner_project_fk'
      and conrelid = 'public.proof_project_relationships'::regclass
  ) then
    alter table public.proof_project_relationships
      add constraint proof_project_relationships_owner_project_fk
      foreign key (project_id, owner_user_id)
      references public.vbr_projects (id, user_id)
      on delete cascade
      not valid;
  end if;
end
$$;

create unique index if not exists proof_project_relationships_scoped_unique_idx
  on public.proof_project_relationships (
    owner_user_id,
    proof_type,
    proof_id,
    coalesce(project_id, '00000000-0000-0000-0000-000000000000'::uuid)
  );
create index if not exists proof_project_relationships_project_idx
  on public.proof_project_relationships (project_id, relationship_state);
create index if not exists proof_project_relationships_proof_idx
  on public.proof_project_relationships (owner_user_id, proof_type, proof_id);

-- One proof may have several review-only suggestions/mismatches, but it can be
-- counted for at most one project. This is the database-level duplicate and
-- cross-project counting guard; the API performs the same check before write.
create unique index if not exists proof_project_relationships_one_direct_idx
  on public.proof_project_relationships (owner_user_id, proof_type, proof_id)
  where relationship_state = 'directly_linked';

-- Migration 056 intentionally left proof_artifacts.project_id unconstrained.
-- Enforce owner/project consistency for every new or updated artifact while
-- accepting any legacy rows for later audit (NOT VALID performs no destructive
-- backfill and does not block this additive migration on historical data).
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'proof_artifacts_owner_project_fk'
      and conrelid = 'public.proof_artifacts'::regclass
  ) then
    alter table public.proof_artifacts
      add constraint proof_artifacts_owner_project_fk
      foreign key (project_id, owner_user_id)
      references public.vbr_projects (id, user_id)
      on delete cascade
      not valid;
  end if;
end
$$;

create table if not exists public.vbr_claim_evidence_links (
  id                        uuid primary key default gen_random_uuid(),
  project_skill_claim_id    uuid not null references public.vbr_project_skill_claims (id) on delete cascade,
  evidence_item_id          uuid references public.vbr_evidence_items (id) on delete set null,
  proof_type                text not null
                              check (proof_type in ('github', 'website', 'document', 'project_defense', 'video')),
  proof_id                  text not null,
  citation_type             text not null,
  citation_locator          jsonb not null default '{}',
  link_status               text not null default 'pending'
                              check (link_status in ('counted', 'pending', 'excluded')),
  evidence_quality          text not null default 'context'
                              check (evidence_quality in ('primary', 'supporting', 'context', 'insufficient')),
  link_reason               text not null,
  limitations              jsonb not null default '[]',
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  unique (project_skill_claim_id, proof_type, proof_id, citation_type)
);

create index if not exists vbr_claim_evidence_links_claim_idx
  on public.vbr_claim_evidence_links (project_skill_claim_id, link_status);

-- A claim may cite a vbr_evidence_items row only when both belong to the same
-- project. The ordinary FKs prove each row exists; this trigger proves the
-- cross-table project identity and prevents accidental Boston↔VeriBridge links.
create or replace function public.enforce_vbr_claim_evidence_project_identity()
returns trigger
language plpgsql
set search_path = public
as $$
declare
  claim_project_id uuid;
  evidence_project_id uuid;
begin
  if new.evidence_item_id is null then
    return new;
  end if;

  select c.project_id into claim_project_id
  from public.vbr_project_skill_claims c
  where c.id = new.project_skill_claim_id;

  select e.project_id into evidence_project_id
  from public.vbr_evidence_items e
  where e.id = new.evidence_item_id;

  if claim_project_id is distinct from evidence_project_id then
    raise exception 'claim evidence must belong to the same project'
      using errcode = '23514';
  end if;
  return new;
end
$$;

drop trigger if exists vbr_claim_evidence_project_identity_trg
  on public.vbr_claim_evidence_links;
create trigger vbr_claim_evidence_project_identity_trg
  before insert or update of project_skill_claim_id, evidence_item_id
  on public.vbr_claim_evidence_links
  for each row
  execute function public.enforce_vbr_claim_evidence_project_identity();

-- Owner reads traverse the owned project. Writes remain service-role only so
-- source ownership and confirmation provenance are enforced by API services.
alter table public.vbr_project_skill_claims enable row level security;
alter table public.proof_project_relationships enable row level security;
alter table public.vbr_claim_evidence_links enable row level security;

drop policy if exists "vbr_project_skill_claims: own select" on public.vbr_project_skill_claims;
create policy "vbr_project_skill_claims: own select"
  on public.vbr_project_skill_claims for select to authenticated
  using (exists (
    select 1 from public.vbr_projects p
    where p.id = project_id and p.user_id::text = (select auth.uid())::text
  ));

drop policy if exists "proof_project_relationships: own select" on public.proof_project_relationships;
create policy "proof_project_relationships: own select"
  on public.proof_project_relationships for select to authenticated
  using (owner_user_id::text = (select auth.uid())::text);

drop policy if exists "vbr_claim_evidence_links: own select" on public.vbr_claim_evidence_links;
create policy "vbr_claim_evidence_links: own select"
  on public.vbr_claim_evidence_links for select to authenticated
  using (exists (
    select 1
    from public.vbr_project_skill_claims c
    join public.vbr_projects p on p.id = c.project_id
    where c.id = project_skill_claim_id
      and p.user_id::text = (select auth.uid())::text
  ));

drop policy if exists "vbr_project_skill_claims: service role all" on public.vbr_project_skill_claims;
create policy "vbr_project_skill_claims: service role all"
  on public.vbr_project_skill_claims for all to service_role using (true) with check (true);

drop policy if exists "proof_project_relationships: service role all" on public.proof_project_relationships;
create policy "proof_project_relationships: service role all"
  on public.proof_project_relationships for all to service_role using (true) with check (true);

drop policy if exists "vbr_claim_evidence_links: service role all" on public.vbr_claim_evidence_links;
create policy "vbr_claim_evidence_links: service role all"
  on public.vbr_claim_evidence_links for all to service_role using (true) with check (true);
