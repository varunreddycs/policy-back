-- Ensure pgcrypto exists for gen_random_uuid()
create extension if not exists pgcrypto;

-- Variables (edit if needed)
-- tenant_id: 00000000-0000-0000-0000-000000000001

with
dept_policy as (
  insert into policies (
    id, tenant_id, external_id, name, status, jurisdiction, category,
    authority_level, department_scope, policy_type, current_version_id,
    created_at, updated_at
  )
  values (
    gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid,
    'claims-appeals-sop', 'Claims Appeals SOP', 'active', 'us', 'claims',
    60, 'claims_ops', 'claims', null,
    now(), now()
  )
  returning *
),
ent_policy as (
  insert into policies (
    id, tenant_id, external_id, name, status, jurisdiction, category,
    authority_level, department_scope, policy_type, current_version_id,
    created_at, updated_at
  )
  values (
    gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid,
    'enterprise-appeals-policy', 'Enterprise Appeals Policy', 'active', 'us', 'enterprise',
    80, 'all', 'claims', null,
    now(), now()
  )
  returning *
),
dept_version as (
  insert into policy_versions (
    id, tenant_id, policy_id,
    version_number, version_label, supersedes_policy_version_id,
    title, effective_date,
    parse_status, is_current, parse_status_updated_at,
    created_at, correlation_id
  )
  select
    gen_random_uuid(), dp.tenant_id, dp.id,
    1, 'v1', null,
    'Claims Appeals SOP v1', current_date,
    'ready', true, now(),
    now(), 'conflict-test-dept'
  from dept_policy dp
  returning *
),
ent_version as (
  insert into policy_versions (
    id, tenant_id, policy_id,
    version_number, version_label, supersedes_policy_version_id,
    title, effective_date,
    parse_status, is_current, parse_status_updated_at,
    created_at, correlation_id
  )
  select
    gen_random_uuid(), ep.tenant_id, ep.id,
    1, 'v1', null,
    'Enterprise Appeals Policy v1', current_date,
    'ready', true, now(),
    now(), 'conflict-test-ent'
  from ent_policy ep
  returning *
),
dept_section as (
  insert into policy_sections (
    id, tenant_id, policy_version_id,
    section_index, section_path, title, text,
    start_offset, end_offset, content_sha256, created_at
  )
  select
    gen_random_uuid(), dv.tenant_id, dv.id,
    1, 'Member Appeals', 'Member Appeals',
    'Members may file an appeal within 90 days of the adverse determination notice date.',
    0, 96,
    encode(digest('Members may file an appeal within 90 days of the adverse determination notice date.', 'sha256'),'hex'),
    now()
  from dept_version dv
  returning *
),
ent_section as (
  insert into policy_sections (
    id, tenant_id, policy_version_id,
    section_index, section_path, title, text,
    start_offset, end_offset, content_sha256, created_at
  )
  select
    gen_random_uuid(), ev.tenant_id, ev.id,
    1, 'Member Appeals', 'Member Appeals',
    'Members may file an appeal within 60 days of the adverse determination notice date.',
    0, 95,
    encode(digest('Members may file an appeal within 60 days of the adverse determination notice date.', 'sha256'),'hex'),
    now()
  from ent_version ev
  returning *
)
-- Set policies.current_version_id
update policies p
set current_version_id = pv.id
from policy_versions pv
where pv.policy_id = p.id and pv.is_current = true;

-- Quick verification
select p.name, p.authority_level, p.department_scope, pv.id as version_id, pv.is_current, pv.parse_status
from policies p
join policy_versions pv on pv.policy_id = p.id
where p.external_id in ('claims-appeals-sop','enterprise-appeals-policy');