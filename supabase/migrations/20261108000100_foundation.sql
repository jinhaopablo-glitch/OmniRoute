-- =============================================================================
-- PUAVI AI · Migración 0001 · Cimientos
-- Tipos, roles técnicos, tablas núcleo, configuración y presupuestos.
--
-- Modelo de roles (permisos mínimos):
--   anon            -> sin acceso a nada.
--   authenticated   -> humanos del panel (Supabase Auth). Lectura según perfil;
--                      escritura limitada por RLS. Únicos que pueden aprobar.
--   puavi_agent     -> procesos de agentes. Solo lectura + funciones concretas
--                      (proponer, encolar, registrar). NUNCA aprueban.
--   puavi_supervisor-> agente supervisor. Revisa propuestas; NUNCA aprueba.
--   puavi_executor  -> único proceso que ejecuta acciones aprobadas.
-- Los roles puavi_* son NOLOGIN: el operador crea usuarios de login con
-- contraseña propia que heredan de ellos (ver docs/despliegue.md).
-- =============================================================================

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'puavi_agent') then
    create role puavi_agent nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'puavi_supervisor') then
    create role puavi_supervisor nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'puavi_executor') then
    create role puavi_executor nologin;
  end if;
end
$$;

grant usage on schema public to puavi_agent, puavi_supervisor, puavi_executor;

-- ---------------------------------------------------------------------------
-- Tipos
-- ---------------------------------------------------------------------------
create type public.proposal_status as enum (
  'pending_review',    -- creada por un agente, esperando al supervisor
  'pending_approval',  -- supervisor OK, esperando decisión humana
  'approved',          -- aprobada por un humano (owner)
  'rejected',
  'executing',
  'executed',
  'failed',
  'expired',
  'cancelled'
);

create type public.action_type as enum (
  'publish_content',       -- publicar contenido
  'change_price',          -- modificar precios
  'modify_product',        -- modificar productos de Shopify
  'launch_ad',             -- lanzar anuncios
  'spend_money',           -- gastar dinero
  'send_commercial_comm',  -- enviar comunicaciones comerciales
  'other_sensitive'
);

create type public.job_status as enum ('queued', 'running', 'done', 'failed', 'cancelled');
create type public.task_status as enum ('todo', 'in_progress', 'blocked', 'done', 'cancelled');
create type public.actor_type as enum ('human', 'agent', 'supervisor', 'executor', 'system');

-- ---------------------------------------------------------------------------
-- Perfiles humanos (vinculados a Supabase Auth)
-- ---------------------------------------------------------------------------
create table public.profiles (
  user_id      uuid primary key,
  display_name text not null check (length(display_name) between 1 and 80),
  role         text not null check (role in ('owner', 'viewer')),
  created_at   timestamptz not null default now()
);

do $$
begin
  if exists (select 1 from information_schema.tables
             where table_schema = 'auth' and table_name = 'users') then
    alter table public.profiles
      add constraint profiles_user_fk foreign key (user_id)
      references auth.users (id) on delete cascade;
  end if;
end
$$;

-- Rol del humano que hace la petición (null si no es un humano registrado).
create function public.current_human_role()
returns text
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select p.role from public.profiles p where p.user_id = auth.uid()
$$;

-- ---------------------------------------------------------------------------
-- Agentes
-- ---------------------------------------------------------------------------
create table public.agents (
  id          text primary key check (id ~ '^[a-z_]{3,32}$'),
  name        text not null,
  description text not null default '',
  model       text not null default 'claude-opus-5-5',
  effort      text not null default 'medium' check (effort in ('low', 'medium', 'high', 'xhigh', 'max')),
  enabled     boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Configuración clave/valor (incluye el interruptor de emergencia)
-- ---------------------------------------------------------------------------
create table public.settings (
  key        text primary key check (key ~ '^[a-z_.]{3,64}$'),
  value      jsonb not null,
  updated_at timestamptz not null default now(),
  updated_by uuid
);

create function public.setting_text(p_key text, p_default text)
returns text
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select coalesce((select value #>> '{}' from public.settings where key = p_key), p_default)
$$;

-- ---------------------------------------------------------------------------
-- Cola de trabajos
-- ---------------------------------------------------------------------------
create table public.jobs (
  id            uuid primary key default gen_random_uuid(),
  agent_id      text not null references public.agents (id),
  kind          text not null check (kind ~ '^[a-z_.]{3,64}$'),
  payload       jsonb not null default '{}'::jsonb,
  status        public.job_status not null default 'queued',
  priority      int not null default 100,
  run_after     timestamptz not null default now(),
  attempts      int not null default 0,
  max_attempts  int not null default 3 check (max_attempts between 1 and 10),
  locked_by     text,
  locked_at     timestamptz,
  last_error    text,
  result        jsonb,
  parent_job_id uuid references public.jobs (id),
  dedupe_key    text unique,
  created_at    timestamptz not null default now(),
  finished_at   timestamptz
);

create index jobs_ready_idx on public.jobs (status, run_after, priority);

-- ---------------------------------------------------------------------------
-- Ejecuciones de agentes (coste y trazabilidad)
-- ---------------------------------------------------------------------------
create table public.agent_runs (
  id                 uuid primary key default gen_random_uuid(),
  job_id             uuid references public.jobs (id),
  agent_id           text not null references public.agents (id),
  model              text not null,
  input_tokens       int not null default 0 check (input_tokens >= 0),
  output_tokens      int not null default 0 check (output_tokens >= 0),
  cache_read_tokens  int not null default 0 check (cache_read_tokens >= 0),
  cache_write_tokens int not null default 0 check (cache_write_tokens >= 0),
  web_searches       int not null default 0 check (web_searches >= 0),
  cost_usd           numeric(12, 6) not null default 0 check (cost_usd >= 0),
  status             text not null check (status in ('ok', 'error', 'blocked')),
  summary            text not null default '',
  output             jsonb,
  created_at         timestamptz not null default now()
);

create index agent_runs_agent_time_idx on public.agent_runs (agent_id, created_at);
create index agent_runs_time_idx on public.agent_runs (created_at);

-- ---------------------------------------------------------------------------
-- Tareas pendientes (humanos y agentes)
-- ---------------------------------------------------------------------------
create table public.tasks (
  id              uuid primary key default gen_random_uuid(),
  title           text not null check (length(title) between 3 and 200),
  description     text not null default '',
  status          public.task_status not null default 'todo',
  priority        int not null default 2 check (priority between 1 and 4),
  assigned_agent  text references public.agents (id),
  created_by_type public.actor_type not null default 'human',
  created_by      text not null default '',
  due_date        date,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index tasks_status_idx on public.tasks (status, priority);

-- ---------------------------------------------------------------------------
-- Presupuestos de gasto de IA
-- scope = 'global' o el id de un agente
-- ---------------------------------------------------------------------------
create table public.budget_limits (
  id         bigint generated always as identity primary key,
  scope      text not null,
  period     text not null check (period in ('daily', 'monthly')),
  limit_usd  numeric(12, 2) not null check (limit_usd >= 0),
  updated_at timestamptz not null default now(),
  unique (scope, period)
);

-- ---------------------------------------------------------------------------
-- Datos iniciales
-- ---------------------------------------------------------------------------
insert into public.agents (id, name, description) values
  ('principal',     'Agente Principal',     'Coordina a los agentes, asigna tareas, comprueba resultados y prepara informes.'),
  ('marketing',     'Agente de Marketing',  'Investiga tendencias, planifica campañas y crea estrategias para TikTok e Instagram.'),
  ('creativo',      'Agente Creativo',      'Genera ideas, guiones, vídeos publicitarios, subtítulos y creatividades.'),
  ('investigacion', 'Agente de Investigación', 'Busca productos, analiza proveedores, competencia española y márgenes.'),
  ('shopify',       'Agente Shopify',       'Analiza fichas, descripciones, precios e imágenes y propone mejoras de conversión.'),
  ('analitico',     'Agente Analítico',     'Analiza visitas, ventas, conversiones y rendimiento del contenido.'),
  ('supervisor',    'Agente Supervisor',    'Comprueba la calidad, detecta errores y verifica las normas de PUAVI. No aprueba acciones.');

insert into public.settings (key, value) values
  ('timezone',             '"Europe/Madrid"'),
  ('kill_switch',          'false'),
  ('approval_expiry_days', '7'),
  ('brand.version',        '"1.0"');

insert into public.budget_limits (scope, period, limit_usd) values
  ('global', 'daily',   5.00),
  ('global', 'monthly', 100.00);
