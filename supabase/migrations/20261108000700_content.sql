-- =============================================================================
-- PUAVI AI · Migración 0007 · Contenido, investigación, métricas e informes
-- Los agentes escriben solo mediante funciones; los humanos leen y pueden
-- cambiar el estado/fecha del contenido (nunca publicarlo: eso es una propuesta).
-- =============================================================================

create type public.content_kind as enum ('trend', 'idea', 'script', 'video', 'post');
create type public.content_status as enum (
  'draft', 'in_review', 'ready', 'scheduled', 'published', 'discarded', 'flagged'
);

create table public.content_items (
  id             uuid primary key default gen_random_uuid(),
  kind           public.content_kind not null,
  platform       text check (platform in ('instagram', 'tiktok', 'both')),
  title          text not null check (length(title) between 3 and 200),
  body           jsonb not null default '{}'::jsonb,
  status         public.content_status not null default 'draft',
  parent_id      uuid references public.content_items (id),
  media_paths    text[] not null default '{}',
  scheduled_for  timestamptz,
  published_url  text,
  created_by     text not null references public.agents (id),
  source_job_id  uuid references public.jobs (id),
  review_notes   text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index content_items_kind_idx on public.content_items (kind, status, created_at desc);
create index content_items_sched_idx on public.content_items (scheduled_for);

create table public.research_products (
  id                 uuid primary key default gen_random_uuid(),
  name               text not null check (length(name) between 2 and 200),
  category           text not null default '',
  pet                text not null default 'ambos' check (pet in ('perro', 'gato', 'ambos')),
  supplier           text not null default '',
  supplier_url       text,
  unit_cost_eur      numeric(12, 2) check (unit_cost_eur >= 0),
  suggested_price_eur numeric(12, 2) check (suggested_price_eur >= 0),
  competitor_price_eur numeric(12, 2) check (competitor_price_eur >= 0),
  estimated_margin_pct numeric(6, 2),
  score              int check (score between 0 and 100),
  rationale          text not null default '',
  sources            jsonb not null default '[]'::jsonb,
  status             text not null default 'new' check (status in ('new', 'shortlisted', 'discarded', 'added')),
  created_by         text not null references public.agents (id),
  created_at         timestamptz not null default now()
);

create table public.competitors (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique,
  website     text,
  notes       text not null default '',
  created_at  timestamptz not null default now()
);

create table public.competitor_snapshots (
  id            uuid primary key default gen_random_uuid(),
  competitor_id uuid not null references public.competitors (id),
  taken_on      date not null default current_date,
  summary       text not null,
  data          jsonb not null default '{}'::jsonb,
  sources       jsonb not null default '[]'::jsonb,
  created_by    text not null references public.agents (id),
  created_at    timestamptz not null default now()
);

create table public.metrics_daily (
  day        date not null,
  source     text not null check (source in ('shopify', 'instagram', 'tiktok', 'ads')),
  metrics    jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (day, source)
);

create table public.reports (
  id         uuid primary key default gen_random_uuid(),
  day        date not null,
  kind       text not null default 'daily' check (kind in ('daily', 'weekly', 'adhoc')),
  title      text not null,
  body_md    text not null,
  data       jsonb not null default '{}'::jsonb,
  created_by text not null references public.agents (id),
  created_at timestamptz not null default now(),
  unique (day, kind)
);

-- Usuarios técnicos de Supabase Auth para Storage (sin perfil: no ven ni aprueban nada).
create table public.storage_service_users (
  user_id   uuid primary key,
  label     text not null,
  can_write boolean not null default false
);

-- ---------------------------------------------------------------------------
-- Funciones de escritura para agentes
-- ---------------------------------------------------------------------------
create function public.agent_save_content(
  p_agent_id text, p_kind public.content_kind, p_platform text, p_title text, p_body jsonb,
  p_parent_id uuid default null, p_media_paths text[] default '{}',
  p_scheduled_for timestamptz default null, p_job_id uuid default null,
  p_status public.content_status default 'draft'
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
begin
  if p_status not in ('draft', 'in_review', 'ready', 'flagged') then
    raise exception 'Un agente no puede marcar contenido como %', p_status
      using errcode = 'insufficient_privilege';
  end if;
  insert into public.content_items (kind, platform, title, body, parent_id, media_paths,
                                    scheduled_for, created_by, source_job_id, status)
  values (p_kind, p_platform, p_title, coalesce(p_body, '{}'::jsonb), p_parent_id,
          coalesce(p_media_paths, '{}'), p_scheduled_for, p_agent_id, p_job_id, p_status)
  returning id into v_id;
  perform public.audit_write('agent', p_agent_id, 'content.created', 'content', v_id::text,
          jsonb_build_object('kind', p_kind, 'title', p_title));
  return v_id;
end
$$;

create function public.agent_update_content(
  p_agent_id text, p_content_id uuid, p_status public.content_status,
  p_media_paths text[] default null, p_review_notes text default null
)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if p_status in ('published', 'scheduled') then
    raise exception 'Solo la ejecución aprobada publica o programa contenido'
      using errcode = 'insufficient_privilege';
  end if;
  update public.content_items
     set status = p_status,
         media_paths = coalesce(p_media_paths, media_paths),
         review_notes = coalesce(p_review_notes, review_notes),
         updated_at = now()
   where id = p_content_id and status not in ('published', 'discarded');
  if not found then
    raise exception 'Contenido no encontrado o cerrado' using errcode = 'no_data_found';
  end if;
  perform public.audit_write(case when p_agent_id = 'supervisor' then 'supervisor'::public.actor_type
                                  else 'agent'::public.actor_type end,
          p_agent_id, 'content.updated', 'content', p_content_id::text,
          jsonb_build_object('status', p_status, 'notes', p_review_notes));
end
$$;

create function public.agent_save_research_product(
  p_agent_id text, p_name text, p_category text, p_pet text, p_supplier text,
  p_supplier_url text, p_unit_cost numeric, p_suggested_price numeric,
  p_competitor_price numeric, p_score int, p_rationale text, p_sources jsonb
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
  v_margin numeric := case when coalesce(p_suggested_price, 0) > 0 and p_unit_cost is not null
                           then round((p_suggested_price / 1.21 - p_unit_cost) / (p_suggested_price / 1.21) * 100, 2)
                      end;
begin
  insert into public.research_products (name, category, pet, supplier, supplier_url, unit_cost_eur,
         suggested_price_eur, competitor_price_eur, estimated_margin_pct, score, rationale,
         sources, created_by)
  values (p_name, coalesce(p_category, ''), coalesce(p_pet, 'ambos'), coalesce(p_supplier, ''),
          p_supplier_url, p_unit_cost, p_suggested_price, p_competitor_price, v_margin, p_score,
          coalesce(p_rationale, ''), coalesce(p_sources, '[]'::jsonb), p_agent_id)
  returning id into v_id;
  return v_id;
end
$$;

create function public.agent_save_competitor_snapshot(
  p_agent_id text, p_name text, p_website text, p_summary text, p_data jsonb, p_sources jsonb
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_comp uuid;
  v_id uuid;
begin
  insert into public.competitors (name, website) values (p_name, p_website)
  on conflict (name) do update set website = coalesce(public.competitors.website, excluded.website)
  returning id into v_comp;
  insert into public.competitor_snapshots (competitor_id, summary, data, sources, created_by)
  values (v_comp, p_summary, coalesce(p_data, '{}'::jsonb), coalesce(p_sources, '[]'::jsonb), p_agent_id)
  returning id into v_id;
  return v_id;
end
$$;

create function public.agent_save_metrics(p_day date, p_source text, p_metrics jsonb)
returns void
language sql
security definer
set search_path = public, pg_temp
as $$
  insert into public.metrics_daily (day, source, metrics) values (p_day, p_source, p_metrics)
  on conflict (day, source) do update set metrics = excluded.metrics, updated_at = now()
$$;

create function public.agent_save_report(p_agent_id text, p_day date, p_kind text, p_title text,
                                         p_body_md text, p_data jsonb)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
begin
  insert into public.reports (day, kind, title, body_md, data, created_by)
  values (p_day, p_kind, p_title, p_body_md, coalesce(p_data, '{}'::jsonb), p_agent_id)
  on conflict (day, kind) do update
     set title = excluded.title, body_md = excluded.body_md, data = excluded.data,
         created_at = now()
  returning id into v_id;
  perform public.audit_write('agent', p_agent_id, 'report.saved', 'report', v_id::text,
          jsonb_build_object('day', p_day, 'kind', p_kind));
  return v_id;
end
$$;

-- El ejecutor marca contenido publicado tras una acción aprobada.
create function public.executor_mark_published(p_content_id uuid, p_url text)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  update public.content_items set status = 'published', published_url = p_url, updated_at = now()
   where id = p_content_id;
  perform public.audit_write('executor', 'executor', 'content.published', 'content',
          p_content_id::text, jsonb_build_object('url', p_url));
end
$$;

-- Auditoría de cambios humanos en contenido.
create trigger content_items_audit after update on public.content_items
  for each row when (auth.uid() is not null)
  execute function public.audit_row_change();

-- ---------------------------------------------------------------------------
-- Permisos
-- ---------------------------------------------------------------------------
revoke all on public.content_items, public.research_products, public.competitors,
              public.competitor_snapshots, public.metrics_daily, public.reports,
              public.storage_service_users
  from public, anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;
grant execute on function public.current_human_role(), public.approve_proposal(uuid, text, text),
                          public.reject_proposal(uuid, text), public.audit_verify_chain()
  to authenticated;

alter table public.content_items        enable row level security;
alter table public.research_products    enable row level security;
alter table public.competitors          enable row level security;
alter table public.competitor_snapshots enable row level security;
alter table public.metrics_daily        enable row level security;
alter table public.reports              enable row level security;
alter table public.storage_service_users enable row level security;

grant select on public.content_items, public.research_products, public.competitors,
                public.competitor_snapshots, public.metrics_daily, public.reports
  to authenticated, puavi_agent, puavi_supervisor;

create policy humans_read on public.content_items        for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.research_products    for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.competitors          for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.competitor_snapshots for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.metrics_daily        for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.reports              for select to authenticated using (public.current_human_role() is not null);

create policy processes_read on public.content_items        for select to puavi_agent, puavi_supervisor using (true);
create policy processes_read on public.research_products    for select to puavi_agent, puavi_supervisor using (true);
create policy processes_read on public.competitors          for select to puavi_agent, puavi_supervisor using (true);
create policy processes_read on public.competitor_snapshots for select to puavi_agent, puavi_supervisor using (true);
create policy processes_read on public.metrics_daily        for select to puavi_agent, puavi_supervisor using (true);
create policy processes_read on public.reports              for select to puavi_agent, puavi_supervisor using (true);

-- Humanos owner: descartar o reprogramar contenido, gestionar investigación.
grant update (status, scheduled_for, review_notes, updated_at) on public.content_items to authenticated;
create policy owners_update on public.content_items for update to authenticated
  using (public.current_human_role() = 'owner')
  with check (public.current_human_role() = 'owner' and status not in ('published', 'scheduled'));
grant update (status) on public.research_products to authenticated;
create policy owners_update on public.research_products for update to authenticated
  using (public.current_human_role() = 'owner') with check (public.current_human_role() = 'owner');
grant insert (name, website, notes), update (website, notes) on public.competitors to authenticated;
create policy owners_insert on public.competitors for insert to authenticated
  with check (public.current_human_role() = 'owner');
create policy owners_update on public.competitors for update to authenticated
  using (public.current_human_role() = 'owner') with check (public.current_human_role() = 'owner');

grant execute on function
  public.agent_save_content(text, public.content_kind, text, text, jsonb, uuid, text[], timestamptz, uuid, public.content_status),
  public.agent_update_content(text, uuid, public.content_status, text[], text),
  public.agent_save_research_product(text, text, text, text, text, text, numeric, numeric, numeric, int, text, jsonb),
  public.agent_save_competitor_snapshot(text, text, text, text, jsonb, jsonb),
  public.agent_save_metrics(date, text, jsonb),
  public.agent_save_report(text, date, text, text, text, jsonb)
  to puavi_agent;
grant execute on function public.agent_update_content(text, uuid, public.content_status, text[], text)
  to puavi_supervisor;
grant execute on function public.executor_mark_published(uuid, text) to puavi_executor;

-- ---------------------------------------------------------------------------
-- Storage (solo en Supabase): bucket privado 'media'
-- ---------------------------------------------------------------------------
do $$
begin
  if exists (select 1 from information_schema.tables
             where table_schema = 'storage' and table_name = 'buckets') then
    insert into storage.buckets (id, name, public) values ('media', 'media', false)
    on conflict (id) do nothing;
    execute $p$create policy puavi_media_read on storage.objects for select to authenticated
      using (bucket_id = 'media' and (public.current_human_role() is not null
             or auth.uid() in (select user_id from public.storage_service_users)))$p$;
    execute $p$create policy puavi_media_write on storage.objects for insert to authenticated
      with check (bucket_id = 'media'
             and auth.uid() in (select user_id from public.storage_service_users where can_write))$p$;
  end if;
end
$$;

-- Las políticas de storage evalúan esta tabla como el usuario autenticado.
grant select on public.storage_service_users to authenticated;
create policy self_read on public.storage_service_users for select to authenticated
  using (user_id = auth.uid() or public.current_human_role() = 'owner');
