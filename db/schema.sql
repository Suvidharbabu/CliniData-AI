-- CliniData AI - Supabase Postgres schema
-- Run once in the Supabase SQL editor (safe to re-run).
--
-- The FastAPI backend connects as the `postgres` role through the pooler and
-- bypasses RLS. RLS is enabled on every table with NO policies, so the public
-- anon/publishable key used by the browser cannot read or write any of it.

-- ---------------------------------------------------------------------------
-- Users (one row per Supabase auth user; created on first API call)
-- ---------------------------------------------------------------------------
create table if not exists profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text not null default '',
  role        text not null default 'compliance_officer'
              check (role in ('compliance_officer', 'compliance_manager', 'cco', 'auditor')),
  created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Compliance catalogue (shared seed data, mirrored into Neo4j + Pinecone)
-- ---------------------------------------------------------------------------
create table if not exists regulations (
  id              text primary key,
  name            text not null,
  framework       text not null,
  jurisdiction    text not null,
  version         text not null,
  effective_date  date,
  source_url      text
);

create table if not exists obligations (
  id               text primary key,
  regulation_id    text not null references regulations(id) on delete cascade,
  article_ref      text not null,
  title            text not null,
  text             text not null,
  obligation_type  text not null,
  severity         text not null check (severity in ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')),
  deadline_hours   integer,
  deadline_label   text
);
create index if not exists obligations_regulation_idx on obligations(regulation_id);

create table if not exists entities (
  id           text primary key,
  name         text not null,
  entity_type  text not null,
  jurisdiction text
);

create table if not exists assets (
  id              text primary key,
  name            text not null,
  asset_type      text not null check (asset_type in ('system', 'data_store', 'process', 'third_party', 'device')),
  classification  text not null,
  owner_id        text references entities(id),
  location        text
);

create table if not exists controls (
  id                     text primary key,
  name                   text not null,
  description            text not null,
  control_type           text not null,
  owner_id               text references entities(id),
  implementation_status  text not null
                         check (implementation_status in ('not_started', 'in_progress', 'implemented', 'failed')),
  effectiveness          numeric(3,2) not null default 0,
  sla_hours              integer,
  last_assessed          date
);

create table if not exists control_obligations (
  control_id     text references controls(id) on delete cascade,
  obligation_id  text references obligations(id) on delete cascade,
  primary key (control_id, obligation_id)
);

create table if not exists control_assets (
  control_id  text references controls(id) on delete cascade,
  asset_id    text references assets(id) on delete cascade,
  primary key (control_id, asset_id)
);

create table if not exists obligation_mappings (
  from_obligation  text references obligations(id) on delete cascade,
  to_obligation    text references obligations(id) on delete cascade,
  rationale        text,
  primary key (from_obligation, to_obligation)
);

create table if not exists risks (
  id          text primary key,
  name        text not null,
  category    text not null,
  likelihood  integer not null check (likelihood between 1 and 5),
  impact      integer not null check (impact between 1 and 5),
  asset_id    text references assets(id)
);

create table if not exists risk_obligations (
  risk_id        text references risks(id) on delete cascade,
  obligation_id  text references obligations(id) on delete cascade,
  primary key (risk_id, obligation_id)
);

create table if not exists evidence (
  id            text primary key,
  control_id    text not null references controls(id) on delete cascade,
  document_ref  text not null,
  collected_at  date not null,
  verified_by   text,
  doc_hash      text not null
);

-- Retrieval corpus: the sparse (keyword) side of hybrid search.
create table if not exists doc_chunks (
  id              text primary key,
  source_node_id  text not null,
  node_type       text not null,
  framework       text,
  text            text not null,
  tsv             tsvector generated always as (to_tsvector('english', text)) stored
);
create index if not exists doc_chunks_tsv_idx on doc_chunks using gin(tsv);

-- ---------------------------------------------------------------------------
-- Adaptive instruction codebook
-- ---------------------------------------------------------------------------
create table if not exists instructions (
  id            text primary key,
  domain        text not null,
  title         text not null,
  text          text not null,
  success_rate  numeric(4,3) not null default 0.700,
  version       integer not null default 1,
  active        boolean not null default true,
  created_at    timestamptz not null default now()
);

create table if not exists instruction_feedback (
  id          bigint generated always as identity primary key,
  run_id      uuid not null,
  user_id     uuid not null references profiles(id) on delete cascade,
  helpful     boolean not null,
  created_at  timestamptz not null default now(),
  unique (run_id, user_id)
);

-- ---------------------------------------------------------------------------
-- Agent runs, gaps, approvals, remediation (scoped to the user who ran them)
-- ---------------------------------------------------------------------------
create table if not exists agent_runs (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references profiles(id) on delete cascade,
  query_text         text not null,
  status             text not null default 'running' check (status in ('running', 'completed', 'failed')),
  started_at         timestamptz not null default now(),
  finished_at        timestamptz,
  trace_log          jsonb not null default '[]'::jsonb,
  instructions_used  jsonb not null default '[]'::jsonb,
  answer             text,
  guard_report       jsonb,
  result             jsonb,
  model              text,
  response_hash      text
);
create index if not exists agent_runs_user_idx on agent_runs(user_id, started_at desc);

create table if not exists gaps (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references profiles(id) on delete cascade,
  run_id         uuid not null references agent_runs(id) on delete cascade,
  obligation_id  text not null references obligations(id),
  gap_type       text not null,
  severity       text not null,
  summary        text not null,
  detail         text,
  risk_score     numeric(5,2),
  created_at     timestamptz not null default now()
);

create table if not exists approval_requests (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references profiles(id) on delete cascade,
  gap_id         uuid not null references gaps(id) on delete cascade,
  required_role  text not null,
  status         text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'escalated')),
  confidence     numeric(3,2),
  deadline       timestamptz not null default now() + interval '3 days',
  approver_id    uuid references profiles(id),
  approver_role  text,
  decision       text,
  comments       text,
  decided_at     timestamptz,
  created_at     timestamptz not null default now()
);
create index if not exists approvals_user_idx on approval_requests(user_id, status);

create table if not exists remediation_tasks (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references profiles(id) on delete cascade,
  gap_id           uuid not null references gaps(id) on delete cascade,
  title            text not null,
  status           text not null default 'open' check (status in ('open', 'in_progress', 'complete')),
  priority         text not null,
  deadline         date not null,
  policy_template  text not null,
  created_at       timestamptz not null default now(),
  completed_at     timestamptz
);

-- ---------------------------------------------------------------------------
-- Public contact form and audit log
-- ---------------------------------------------------------------------------
create table if not exists contact_requests (
  id            bigint generated always as identity primary key,
  name          text not null,
  email         text not null,
  organization  text,
  role          text,
  message       text,
  ip_addr       text,
  created_at    timestamptz not null default now()
);

create table if not exists audit_logs (
  id           bigint generated always as identity primary key,
  user_id      uuid,
  action       text not null,
  entity_type  text,
  entity_id    text,
  detail       jsonb,
  ip_addr      text,
  created_at   timestamptz not null default now()
);

-- Append-only: block UPDATE and DELETE on the audit log for every role.
create or replace function audit_logs_immutable() returns trigger language plpgsql as $$
begin
  raise exception 'audit_logs is append-only';
end $$;
drop trigger if exists audit_logs_no_update on audit_logs;
create trigger audit_logs_no_update before update or delete on audit_logs
  for each row execute function audit_logs_immutable();

-- ---------------------------------------------------------------------------
-- Row-level security: on everywhere, no policies (server-side access only)
-- ---------------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'profiles', 'regulations', 'obligations', 'entities', 'assets', 'controls',
    'control_obligations', 'control_assets', 'obligation_mappings', 'risks',
    'risk_obligations', 'evidence', 'doc_chunks', 'instructions', 'instruction_feedback',
    'agent_runs', 'gaps', 'approval_requests', 'remediation_tasks', 'contact_requests', 'audit_logs'
  ] loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;
