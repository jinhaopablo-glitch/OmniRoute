-- PUAVI AI · Instalación completa (todas las migraciones en orden).
-- Generado a partir de supabase/migrations/. Pégalo entero en el SQL Editor de Supabase y pulsa Run.


-- ===== 20261108000100_foundation.sql =====
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

-- ===== 20261108000200_audit_log.sql =====
-- =============================================================================
-- PUAVI AI · Migración 0002 · Registro de auditoría inalterable
--
-- * Solo inserción: UPDATE, DELETE y TRUNCATE quedan bloqueados por triggers
--   (también para el propietario de la tabla).
-- * Cadena de hashes: cada fila guarda el hash de la anterior. Cualquier
--   manipulación posterior se detecta con public.audit_verify_chain().
-- * Nadie tiene permiso directo de INSERT: se escribe solo mediante
--   funciones (audit_write interna, log_event para procesos).
-- =============================================================================

create table public.audit_log (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default clock_timestamp(),
  actor_type  public.actor_type not null,
  actor_id    text not null,
  action      text not null check (action ~ '^[a-z_.]{3,64}$'),
  entity_type text not null,
  entity_id   text not null default '',
  details     jsonb not null default '{}'::jsonb,
  prev_hash   text not null,
  hash        text not null
);

create index audit_log_entity_idx on public.audit_log (entity_type, entity_id);
create index audit_log_at_idx on public.audit_log (at);

-- Representación canónica de una fila para el hash.
create function public.audit_row_digest(
  p_prev_hash text, p_at timestamptz, p_actor_type public.actor_type, p_actor_id text,
  p_action text, p_entity_type text, p_entity_id text, p_details jsonb
)
returns text
language sql
immutable
set search_path = public, pg_temp
as $$
  select encode(sha256(convert_to(concat_ws('|',
    p_prev_hash,
    to_char(p_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
    p_actor_type::text, p_actor_id, p_action, p_entity_type, p_entity_id,
    p_details::text
  ), 'UTF8')), 'hex')
$$;

-- Encadena cada inserción, venga de donde venga.
create function public.audit_log_chain()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_prev text;
begin
  -- Serializa las inserciones para que la cadena sea lineal.
  perform pg_advisory_xact_lock(hashtext('puavi.audit_chain'));
  select a.hash into v_prev from public.audit_log a order by a.id desc limit 1;
  new.prev_hash := coalesce(v_prev, repeat('0', 64));
  new.at := clock_timestamp();
  new.hash := public.audit_row_digest(new.prev_hash, new.at, new.actor_type, new.actor_id,
                                      new.action, new.entity_type, new.entity_id, new.details);
  return new;
end
$$;

create trigger audit_log_chain_bi
  before insert on public.audit_log
  for each row execute function public.audit_log_chain();

create function public.audit_log_immutable()
returns trigger
language plpgsql
as $$
begin
  raise exception 'audit_log es inmutable: solo se permiten inserciones'
    using errcode = 'insufficient_privilege';
end
$$;

create trigger audit_log_no_update_delete
  before update or delete on public.audit_log
  for each row execute function public.audit_log_immutable();

create trigger audit_log_no_truncate
  before truncate on public.audit_log
  for each statement execute function public.audit_log_immutable();

-- Escritura interna (la usan las funciones de negocio).
create function public.audit_write(
  p_actor_type public.actor_type, p_actor_id text, p_action text,
  p_entity_type text, p_entity_id text, p_details jsonb default '{}'::jsonb
)
returns bigint
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id bigint;
begin
  insert into public.audit_log (actor_type, actor_id, action, entity_type, entity_id, details,
                                prev_hash, hash)
  values (p_actor_type, coalesce(p_actor_id, ''), p_action, p_entity_type,
          coalesce(p_entity_id, ''), coalesce(p_details, '{}'::jsonb), '', '')
  returning id into v_id;
  return v_id;
end
$$;

-- Escritura para procesos (agentes, supervisor, ejecutor). Nunca puede
-- registrar en nombre de un humano.
create function public.log_event(
  p_actor_type public.actor_type, p_actor_id text, p_action text,
  p_entity_type text, p_entity_id text default '', p_details jsonb default '{}'::jsonb
)
returns bigint
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if p_actor_type = 'human' then
    raise exception 'Un proceso no puede registrar eventos como humano'
      using errcode = 'insufficient_privilege';
  end if;
  return public.audit_write(p_actor_type, p_actor_id, p_action, p_entity_type,
                            p_entity_id, p_details);
end
$$;

-- Verifica la cadena completa. Devuelve el primer id roto (o null si está bien).
create function public.audit_verify_chain()
returns table (ok boolean, rows_checked bigint, first_broken_id bigint)
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
  r record;
  v_prev text := repeat('0', 64);
  v_count bigint := 0;
begin
  for r in select * from public.audit_log order by id loop
    v_count := v_count + 1;
    if r.prev_hash <> v_prev
       or r.hash <> public.audit_row_digest(r.prev_hash, r.at, r.actor_type, r.actor_id,
                                            r.action, r.entity_type, r.entity_id, r.details) then
      return query select false, v_count, r.id;
      return;
    end if;
    v_prev := r.hash;
  end loop;
  return query select true, v_count, null::bigint;
end
$$;

-- Trigger genérico: registra cambios hechos por humanos desde el panel
-- (tareas, configuración, presupuestos, agentes, perfiles).
create function public.audit_row_change()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_uid uuid := auth.uid();
  v_actor_type public.actor_type;
  v_actor_id text;
  v_entity_id text;
  v_details jsonb;
begin
  -- Un humano autenticado siempre queda registrado como humano (no falsificable).
  if v_uid is not null then
    v_actor_type := 'human';
    v_actor_id := v_uid::text;
  else
    v_actor_type := coalesce(nullif(current_setting('puavi.actor_type', true), '')::public.actor_type,
                             'system'::public.actor_type);
    v_actor_id := coalesce(nullif(current_setting('puavi.actor_id', true), ''), session_user::text);
  end if;
  if tg_op = 'DELETE' then
    v_details := jsonb_build_object('old', to_jsonb(old));
    v_entity_id := coalesce(to_jsonb(old) ->> 'id', to_jsonb(old) ->> 'key',
                            to_jsonb(old) ->> 'user_id', '');
  elsif tg_op = 'UPDATE' then
    v_details := jsonb_build_object('old', to_jsonb(old), 'new', to_jsonb(new));
    v_entity_id := coalesce(to_jsonb(new) ->> 'id', to_jsonb(new) ->> 'key',
                            to_jsonb(new) ->> 'user_id', '');
  else
    v_details := jsonb_build_object('new', to_jsonb(new));
    v_entity_id := coalesce(to_jsonb(new) ->> 'id', to_jsonb(new) ->> 'key',
                            to_jsonb(new) ->> 'user_id', '');
  end if;
  perform public.audit_write(v_actor_type, v_actor_id, lower(tg_table_name || '.' || tg_op),
                             tg_table_name, v_entity_id, v_details);
  return null;
end
$$;

create trigger tasks_audit after insert or update or delete on public.tasks
  for each row execute function public.audit_row_change();
create trigger settings_audit after insert or update or delete on public.settings
  for each row execute function public.audit_row_change();
create trigger budget_limits_audit after insert or update or delete on public.budget_limits
  for each row execute function public.audit_row_change();
create trigger agents_audit after update or delete on public.agents
  for each row execute function public.audit_row_change();
create trigger profiles_audit after insert or update or delete on public.profiles
  for each row execute function public.audit_row_change();

-- ===== 20261108000300_approvals.sql =====
-- =============================================================================
-- PUAVI AI · Migración 0003 · Bandeja de aprobaciones
--
-- Flujo:  agente propone -> supervisor revisa -> HUMANO aprueba -> ejecutor
--
--   pending_review --(supervisor ok)--> pending_approval --(owner)--> approved
--        |                                    |                         |
--        +--(supervisor/owner rechaza)--> rejected                      v
--                                                       executing -> executed | failed
--
-- Garantías (impuestas por la base de datos, no por el código de los agentes):
--   1. Ningún rol de proceso tiene UPDATE/INSERT/DELETE directo sobre proposals.
--   2. Solo un humano con rol 'owner' (auth.uid()) puede aprobar.
--   3. El humano aprueba un hash concreto del contenido; si el contenido no
--      coincide, la aprobación falla. El contenido es inmutable tras crearse.
--   4. El ejecutor solo puede tomar propuestas aprobadas, vigentes y cuyo
--      aprobador sigue siendo owner. Cada ejecución lleva clave de idempotencia.
--   5. El supervisor no puede revisar propuestas propias y no puede aprobar.
--   6. Todas las transiciones quedan en audit_log.
-- =============================================================================

create table public.proposals (
  id                 uuid primary key default gen_random_uuid(),
  action_type        public.action_type not null,
  title              text not null check (length(title) between 3 and 200),
  summary            text not null default '' check (length(summary) <= 4000),
  payload            jsonb not null check (jsonb_typeof(payload) = 'object'),
  payload_hash       text not null,
  risk_level         text not null default 'medium' check (risk_level in ('low', 'medium', 'high')),
  estimated_cost_eur numeric(12, 2) not null default 0 check (estimated_cost_eur >= 0),
  proposed_by_agent  text not null references public.agents (id),
  source_run_id      uuid references public.agent_runs (id),
  idempotency_key    text not null unique check (length(idempotency_key) between 8 and 200),
  status             public.proposal_status not null default 'pending_review',
  supervisor_verdict text check (supervisor_verdict in ('ok', 'rejected')),
  supervisor_notes   text,
  reviewed_at        timestamptz,
  decided_by         uuid,
  decided_at         timestamptz,
  decision_note      text,
  approved_hash      text,
  execution_attempts int not null default 0,
  executed_at        timestamptz,
  execution_result   jsonb,
  expires_at         timestamptz not null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index proposals_status_idx on public.proposals (status, created_at);

create function public.payload_digest(p jsonb)
returns text
language sql
immutable
as $$
  -- jsonb::text es canónico (orden de claves determinista).
  select encode(sha256(convert_to(p::text, 'UTF8')), 'hex')
$$;

-- ---------------------------------------------------------------------------
-- Defensa en profundidad: triggers que validan cualquier escritura
-- ---------------------------------------------------------------------------
create function public.proposals_before_insert()
returns trigger
language plpgsql
as $$
begin
  new.status := 'pending_review';
  new.payload_hash := public.payload_digest(new.payload);
  new.supervisor_verdict := null;
  new.supervisor_notes := null;
  new.reviewed_at := null;
  new.decided_by := null;
  new.decided_at := null;
  new.decision_note := null;
  new.approved_hash := null;
  new.execution_attempts := 0;
  new.executed_at := null;
  new.execution_result := null;
  new.created_at := now();
  new.updated_at := now();
  return new;
end
$$;

create trigger proposals_bi before insert on public.proposals
  for each row execute function public.proposals_before_insert();

create function public.proposals_before_update()
returns trigger
language plpgsql
as $$
begin
  if new.action_type is distinct from old.action_type
     or new.title is distinct from old.title
     or new.summary is distinct from old.summary
     or new.payload is distinct from old.payload
     or new.payload_hash is distinct from old.payload_hash
     or new.risk_level is distinct from old.risk_level
     or new.estimated_cost_eur is distinct from old.estimated_cost_eur
     or new.proposed_by_agent is distinct from old.proposed_by_agent
     or new.idempotency_key is distinct from old.idempotency_key
     or new.source_run_id is distinct from old.source_run_id
     or new.created_at is distinct from old.created_at then
    raise exception 'El contenido de una propuesta es inmutable'
      using errcode = 'check_violation';
  end if;

  if new.status is distinct from old.status then
    if not (
      (old.status = 'pending_review'   and new.status in ('pending_approval', 'rejected', 'expired', 'cancelled')) or
      (old.status = 'pending_approval' and new.status in ('approved', 'rejected', 'expired', 'cancelled')) or
      (old.status = 'approved'         and new.status in ('executing', 'expired', 'cancelled')) or
      (old.status = 'executing'        and new.status in ('executed', 'failed')) or
      (old.status = 'failed'           and new.status in ('executing', 'cancelled'))
    ) then
      raise exception 'Transición no permitida: % -> %', old.status, new.status
        using errcode = 'check_violation';
    end if;
  end if;

  if new.status = 'approved' and old.status <> 'approved' then
    if new.decided_by is null or new.approved_hash is distinct from old.payload_hash then
      raise exception 'Aprobación inválida: falta aprobador o el hash no coincide'
        using errcode = 'check_violation';
    end if;
  end if;

  if new.status = 'executing' and new.approved_hash is distinct from public.payload_digest(new.payload) then
    raise exception 'El contenido no coincide con lo aprobado' using errcode = 'check_violation';
  end if;

  new.updated_at := now();
  return new;
end
$$;

create trigger proposals_bu before update on public.proposals
  for each row execute function public.proposals_before_update();

create function public.proposals_no_delete()
returns trigger
language plpgsql
as $$
begin
  raise exception 'Las propuestas no se borran; se cancelan' using errcode = 'insufficient_privilege';
end
$$;

create trigger proposals_bd before delete on public.proposals
  for each row execute function public.proposals_no_delete();

-- ---------------------------------------------------------------------------
-- 1) Agente: crear propuesta (idempotente)
-- ---------------------------------------------------------------------------
create function public.agent_submit_proposal(
  p_agent_id text,
  p_action_type public.action_type,
  p_title text,
  p_summary text,
  p_payload jsonb,
  p_risk_level text,
  p_estimated_cost_eur numeric,
  p_idempotency_key text,
  p_source_run_id uuid default null
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
  v_days int := coalesce(nullif(public.setting_text('approval_expiry_days', '7'), '')::int, 7);
begin
  if p_agent_id = 'supervisor' then
    raise exception 'El supervisor no puede crear propuestas' using errcode = 'insufficient_privilege';
  end if;
  if not exists (select 1 from public.agents where id = p_agent_id and enabled) then
    raise exception 'Agente desconocido o desactivado: %', p_agent_id using errcode = 'check_violation';
  end if;

  select id into v_id from public.proposals where idempotency_key = p_idempotency_key;
  if v_id is not null then
    return v_id;
  end if;

  insert into public.proposals (action_type, title, summary, payload, payload_hash, risk_level,
                                estimated_cost_eur, proposed_by_agent, source_run_id,
                                idempotency_key, expires_at)
  values (p_action_type, p_title, coalesce(p_summary, ''), p_payload, '', p_risk_level,
          coalesce(p_estimated_cost_eur, 0), p_agent_id, p_source_run_id, p_idempotency_key,
          now() + make_interval(days => v_days))
  returning id into v_id;

  perform public.audit_write('agent', p_agent_id, 'proposal.created', 'proposal', v_id::text,
          jsonb_build_object('action_type', p_action_type, 'title', p_title,
                             'risk_level', p_risk_level));
  return v_id;
end
$$;

-- ---------------------------------------------------------------------------
-- 2) Supervisor: revisar (nunca aprobar)
-- ---------------------------------------------------------------------------
create function public.supervisor_review(p_proposal_id uuid, p_verdict text, p_notes text)
returns public.proposal_status
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v public.proposals;
  v_new public.proposal_status;
begin
  if p_verdict not in ('ok', 'rejected') then
    raise exception 'Veredicto inválido' using errcode = 'check_violation';
  end if;
  select * into v from public.proposals where id = p_proposal_id for update;
  if not found then
    raise exception 'Propuesta no encontrada' using errcode = 'no_data_found';
  end if;
  if v.proposed_by_agent = 'supervisor' then
    raise exception 'El supervisor no puede revisar propuestas propias' using errcode = 'insufficient_privilege';
  end if;
  if v.status <> 'pending_review' then
    raise exception 'La propuesta no está pendiente de revisión (estado: %)', v.status
      using errcode = 'check_violation';
  end if;

  v_new := case when p_verdict = 'ok' then 'pending_approval'::public.proposal_status
                else 'rejected'::public.proposal_status end;
  update public.proposals
     set status = v_new, supervisor_verdict = p_verdict, supervisor_notes = p_notes,
         reviewed_at = now()
   where id = p_proposal_id;

  perform public.audit_write('supervisor', 'supervisor', 'proposal.reviewed', 'proposal',
          p_proposal_id::text, jsonb_build_object('verdict', p_verdict, 'notes', p_notes));
  return v_new;
end
$$;

-- ---------------------------------------------------------------------------
-- 3) Humano (owner): aprobar / rechazar
-- ---------------------------------------------------------------------------
create function public.approve_proposal(p_proposal_id uuid, p_expected_hash text,
                                        p_note text default null)
returns public.proposal_status
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_uid uuid := auth.uid();
  v public.proposals;
begin
  if v_uid is null or public.current_human_role() is distinct from 'owner' then
    raise exception 'Solo un humano con rol owner puede aprobar' using errcode = 'insufficient_privilege';
  end if;
  select * into v from public.proposals where id = p_proposal_id for update;
  if not found then
    raise exception 'Propuesta no encontrada' using errcode = 'no_data_found';
  end if;
  if v.status <> 'pending_approval' then
    raise exception 'La propuesta no está pendiente de aprobación (estado: %)', v.status
      using errcode = 'check_violation';
  end if;
  if v.expires_at <= now() then
    raise exception 'La propuesta ha caducado' using errcode = 'check_violation';
  end if;
  if p_expected_hash is distinct from v.payload_hash then
    raise exception 'El contenido ha cambiado desde que lo revisaste; vuelve a cargarlo'
      using errcode = 'check_violation';
  end if;

  update public.proposals
     set status = 'approved', decided_by = v_uid, decided_at = now(),
         decision_note = p_note, approved_hash = v.payload_hash
   where id = p_proposal_id;

  perform public.audit_write('human', v_uid::text, 'proposal.approved', 'proposal',
          p_proposal_id::text, jsonb_build_object('hash', v.payload_hash, 'note', p_note));
  return 'approved';
end
$$;

create function public.reject_proposal(p_proposal_id uuid, p_note text default null)
returns public.proposal_status
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_uid uuid := auth.uid();
  v public.proposals;
begin
  if v_uid is null or public.current_human_role() is distinct from 'owner' then
    raise exception 'Solo un humano con rol owner puede rechazar' using errcode = 'insufficient_privilege';
  end if;
  select * into v from public.proposals where id = p_proposal_id for update;
  if not found then
    raise exception 'Propuesta no encontrada' using errcode = 'no_data_found';
  end if;
  if v.status not in ('pending_review', 'pending_approval', 'approved') then
    raise exception 'No se puede rechazar en estado %', v.status using errcode = 'check_violation';
  end if;

  update public.proposals
     set status = case when v.status = 'approved' then 'cancelled'::public.proposal_status
                       else 'rejected'::public.proposal_status end,
         decided_by = v_uid, decided_at = now(), decision_note = p_note
   where id = p_proposal_id;

  perform public.audit_write('human', v_uid::text, 'proposal.rejected', 'proposal',
          p_proposal_id::text, jsonb_build_object('note', p_note, 'previous_status', v.status));
  return 'rejected';
end
$$;

-- ---------------------------------------------------------------------------
-- 4) Ejecutor
-- ---------------------------------------------------------------------------
create function public.executor_list_ready(p_limit int default 20)
returns table (id uuid, action_type public.action_type)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select p.id, p.action_type
    from public.proposals p
   where (p.status = 'approved' or (p.status = 'failed' and p.execution_attempts < 3))
     and p.expires_at > now()
   order by p.decided_at nulls last
   limit least(greatest(p_limit, 1), 100)
$$;

create function public.executor_claim_proposal(p_proposal_id uuid)
returns table (id uuid, action_type public.action_type, payload jsonb, idempotency_key text,
               attempt int)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v public.proposals;
begin
  select * into v from public.proposals p where p.id = p_proposal_id for update skip locked;
  if not found then
    return; -- no existe o la está tomando otro ejecutor
  end if;
  if not (v.status = 'approved' or (v.status = 'failed' and v.execution_attempts < 3)) then
    return;
  end if;
  if v.expires_at <= now() then
    update public.proposals set status = case when v.status = 'approved'
                                              then 'expired'::public.proposal_status
                                              else 'cancelled'::public.proposal_status end
     where proposals.id = v.id;
    perform public.audit_write('executor', 'executor', 'proposal.expired_before_execution',
            'proposal', v.id::text, '{}'::jsonb);
    return;
  end if;
  -- Revalidaciones: hash aprobado y aprobador que sigue siendo owner.
  if v.approved_hash is null or v.approved_hash <> public.payload_digest(v.payload)
     or v.decided_by is null
     or not exists (select 1 from public.profiles pr where pr.user_id = v.decided_by and pr.role = 'owner') then
    perform public.audit_write('executor', 'executor', 'proposal.claim_refused', 'proposal',
            v.id::text, jsonb_build_object('reason', 'revalidation_failed'));
    return;
  end if;

  update public.proposals
     set status = 'executing', execution_attempts = v.execution_attempts + 1
   where proposals.id = v.id;
  perform public.audit_write('executor', 'executor', 'proposal.executing', 'proposal', v.id::text,
          jsonb_build_object('attempt', v.execution_attempts + 1));

  return query select v.id, v.action_type, v.payload, v.idempotency_key, v.execution_attempts + 1;
end
$$;

create function public.executor_complete(p_proposal_id uuid, p_success boolean, p_result jsonb)
returns public.proposal_status
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_status public.proposal_status := case when p_success then 'executed'::public.proposal_status
                                          else 'failed'::public.proposal_status end;
begin
  update public.proposals
     set status = v_status, execution_result = coalesce(p_result, '{}'::jsonb),
         executed_at = case when p_success then now() else null end
   where id = p_proposal_id and status = 'executing';
  if not found then
    raise exception 'La propuesta no está en ejecución' using errcode = 'check_violation';
  end if;
  perform public.audit_write('executor', 'executor',
          case when p_success then 'proposal.executed' else 'proposal.execution_failed' end,
          'proposal', p_proposal_id::text, coalesce(p_result, '{}'::jsonb));
  return v_status;
end
$$;

-- ---------------------------------------------------------------------------
-- 5) Mantenimiento: caducar propuestas pendientes
-- ---------------------------------------------------------------------------
create function public.expire_proposals()
returns int
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_count int;
begin
  with expired as (
    update public.proposals set status = 'expired'
     where status in ('pending_review', 'pending_approval', 'approved') and expires_at <= now()
    returning id
  )
  select count(*) into v_count from expired;
  if v_count > 0 then
    perform public.audit_write('system', 'cron', 'proposal.expired_batch', 'proposal', '',
            jsonb_build_object('count', v_count));
  end if;
  return v_count;
end
$$;

-- ===== 20261108000400_jobs_budget.sql =====
-- =============================================================================
-- PUAVI AI · Migración 0004 · Cola de trabajos, ejecuciones, presupuesto, tareas
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Cola de trabajos
-- ---------------------------------------------------------------------------
create function public.enqueue_job(
  p_agent_id text, p_kind text, p_payload jsonb default '{}'::jsonb,
  p_run_after timestamptz default now(), p_priority int default 100,
  p_dedupe_key text default null, p_parent_job_id uuid default null
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
begin
  if p_dedupe_key is not null then
    select id into v_id from public.jobs where dedupe_key = p_dedupe_key;
    if v_id is not null then
      return v_id;
    end if;
  end if;
  insert into public.jobs (agent_id, kind, payload, run_after, priority, dedupe_key, parent_job_id)
  values (p_agent_id, p_kind, coalesce(p_payload, '{}'::jsonb), coalesce(p_run_after, now()),
          coalesce(p_priority, 100), p_dedupe_key, p_parent_job_id)
  returning id into v_id;
  return v_id;
end
$$;

-- Toma trabajos listos sin bloquear a otros workers. Recupera trabajos
-- atascados (worker caído) tras 15 minutos.
create function public.claim_jobs(p_worker_id text, p_limit int default 1,
                                  p_agent_ids text[] default null)
returns setof public.jobs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if public.setting_text('kill_switch', 'false') = 'true' then
    return;
  end if;
  return query
  with ready as (
    select j.id from public.jobs j
     join public.agents a on a.id = j.agent_id and a.enabled
     where ((j.status = 'queued' and j.run_after <= now())
            or (j.status = 'running' and j.locked_at < now() - interval '15 minutes'))
       and (p_agent_ids is null or j.agent_id = any (p_agent_ids))
     order by j.priority, j.run_after
     limit least(greatest(p_limit, 1), 20)
     for update of j skip locked
  )
  update public.jobs j
     set status = 'running', locked_by = p_worker_id, locked_at = now(),
         attempts = j.attempts + 1
    from ready
   where j.id = ready.id
  returning j.*;
end
$$;

create function public.complete_job(p_job_id uuid, p_worker_id text, p_result jsonb default null)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  update public.jobs
     set status = 'done', result = p_result, finished_at = now(), locked_by = null, locked_at = null
   where id = p_job_id and status = 'running' and locked_by = p_worker_id;
  if not found then
    raise exception 'El trabajo no está en ejecución por este worker' using errcode = 'check_violation';
  end if;
end
$$;

create function public.fail_job(p_job_id uuid, p_worker_id text, p_error text)
returns public.job_status
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v public.jobs;
  v_status public.job_status;
begin
  select * into v from public.jobs where id = p_job_id and status = 'running'
     and locked_by = p_worker_id for update;
  if not found then
    raise exception 'El trabajo no está en ejecución por este worker' using errcode = 'check_violation';
  end if;
  -- Reintento con espera exponencial: 2, 4, 8... minutos.
  v_status := case when v.attempts < v.max_attempts then 'queued'::public.job_status
                   else 'failed'::public.job_status end;
  update public.jobs
     set status = v_status, last_error = left(p_error, 2000), locked_by = null, locked_at = null,
         run_after = case when v_status = 'queued'
                          then now() + make_interval(mins => power(2, v.attempts)::int)
                          else run_after end,
         finished_at = case when v_status = 'failed' then now() else null end
   where id = p_job_id;
  return v_status;
end
$$;

-- ---------------------------------------------------------------------------
-- Registro de ejecuciones de agentes (coste incluido)
-- ---------------------------------------------------------------------------
create function public.record_agent_run(
  p_agent_id text, p_job_id uuid, p_model text,
  p_input_tokens int, p_output_tokens int, p_cache_read_tokens int, p_cache_write_tokens int,
  p_web_searches int, p_cost_usd numeric, p_status text, p_summary text, p_output jsonb
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
begin
  insert into public.agent_runs (job_id, agent_id, model, input_tokens, output_tokens,
                                 cache_read_tokens, cache_write_tokens, web_searches, cost_usd,
                                 status, summary, output)
  values (p_job_id, p_agent_id, p_model, coalesce(p_input_tokens, 0), coalesce(p_output_tokens, 0),
          coalesce(p_cache_read_tokens, 0), coalesce(p_cache_write_tokens, 0),
          coalesce(p_web_searches, 0), coalesce(p_cost_usd, 0), p_status,
          left(coalesce(p_summary, ''), 4000), p_output)
  returning id into v_id;
  return v_id;
end
$$;

-- ---------------------------------------------------------------------------
-- Presupuesto: ¿puede este agente gastar ahora?
-- Comprueba interruptor de emergencia, límites globales y por agente.
-- Los periodos se calculan en la zona horaria configurada (Europe/Madrid).
-- ---------------------------------------------------------------------------
create function public.check_budget(p_agent_id text)
returns table (allowed boolean, reason text, global_daily_spent numeric,
               global_monthly_spent numeric, agent_daily_spent numeric)
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
  v_tz text := public.setting_text('timezone', 'Europe/Madrid');
  v_day_start timestamptz := date_trunc('day', now() at time zone v_tz) at time zone v_tz;
  v_month_start timestamptz := date_trunc('month', now() at time zone v_tz) at time zone v_tz;
  v_gd numeric; v_gm numeric; v_ad numeric; v_am numeric;
  v_lim record;
begin
  select coalesce(sum(cost_usd), 0) into v_gd from public.agent_runs where created_at >= v_day_start;
  select coalesce(sum(cost_usd), 0) into v_gm from public.agent_runs where created_at >= v_month_start;
  select coalesce(sum(cost_usd), 0) into v_ad from public.agent_runs
   where created_at >= v_day_start and agent_id = p_agent_id;
  select coalesce(sum(cost_usd), 0) into v_am from public.agent_runs
   where created_at >= v_month_start and agent_id = p_agent_id;

  if public.setting_text('kill_switch', 'false') = 'true' then
    return query select false, 'Interruptor de emergencia activado', v_gd, v_gm, v_ad;
    return;
  end if;
  if not exists (select 1 from public.agents where id = p_agent_id and enabled) then
    return query select false, 'Agente desactivado o desconocido', v_gd, v_gm, v_ad;
    return;
  end if;

  for v_lim in select scope, period, limit_usd from public.budget_limits
                where scope in ('global', p_agent_id) loop
    if (v_lim.scope = 'global' and v_lim.period = 'daily' and v_gd >= v_lim.limit_usd)
       or (v_lim.scope = 'global' and v_lim.period = 'monthly' and v_gm >= v_lim.limit_usd)
       or (v_lim.scope = p_agent_id and v_lim.period = 'daily' and v_ad >= v_lim.limit_usd)
       or (v_lim.scope = p_agent_id and v_lim.period = 'monthly' and v_am >= v_lim.limit_usd) then
      return query select false,
        format('Límite %s %s alcanzado (%s USD)',
               case when v_lim.scope = 'global' then 'global' else 'del agente' end,
               case when v_lim.period = 'daily' then 'diario' else 'mensual' end,
               v_lim.limit_usd),
        v_gd, v_gm, v_ad;
      return;
    end if;
  end loop;

  return query select true, 'ok'::text, v_gd, v_gm, v_ad;
end
$$;

-- ---------------------------------------------------------------------------
-- Tareas creadas/actualizadas por agentes
-- ---------------------------------------------------------------------------
create function public.agent_create_task(p_agent_id text, p_title text, p_description text,
                                         p_priority int default 2, p_assigned_agent text default null,
                                         p_due_date date default null)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
begin
  perform set_config('puavi.actor_type', 'agent', true);
  perform set_config('puavi.actor_id', p_agent_id, true);
  insert into public.tasks (title, description, priority, assigned_agent, created_by_type,
                            created_by, due_date)
  values (p_title, coalesce(p_description, ''), coalesce(p_priority, 2), p_assigned_agent,
          'agent', p_agent_id, p_due_date)
  returning id into v_id;
  return v_id;
end
$$;

create function public.agent_update_task_status(p_agent_id text, p_task_id uuid,
                                                p_status public.task_status)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  perform set_config('puavi.actor_type', 'agent', true);
  perform set_config('puavi.actor_id', p_agent_id, true);
  -- Un agente solo modifica tareas que tiene asignadas o que creó él.
  update public.tasks set status = p_status, updated_at = now()
   where id = p_task_id
     and (assigned_agent = p_agent_id or (created_by_type = 'agent' and created_by = p_agent_id));
  if not found then
    raise exception 'Tarea no encontrada o no asignada a %', p_agent_id
      using errcode = 'insufficient_privilege';
  end if;
end
$$;

-- ---------------------------------------------------------------------------
-- Plan diario: lo dispara pg_cron; el agente principal reparte el resto.
-- ---------------------------------------------------------------------------
create function public.enqueue_daily_plan()
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_tz text := public.setting_text('timezone', 'Europe/Madrid');
  v_day text := to_char(now() at time zone v_tz, 'YYYY-MM-DD');
begin
  return public.enqueue_job('principal', 'daily.plan', jsonb_build_object('date', v_day),
                            now(), 10, 'daily.plan:' || v_day);
end
$$;

-- ===== 20261108000500_permissions_rls.sql =====
-- =============================================================================
-- PUAVI AI · Migración 0005 · Permisos mínimos y RLS
--
-- Supabase concede por defecto privilegios amplios a anon/authenticated sobre
-- el esquema public. Aquí se revocan TODOS y se conceden solo los necesarios.
-- tests/db/test_permissions.py verifica que no quede nada abierto.
-- =============================================================================

-- 1) Cerrar todo -------------------------------------------------------------
revoke all on all tables in schema public from public, anon, authenticated;
revoke all on all sequences in schema public from public, anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;

alter default privileges in schema public revoke all on tables from public, anon, authenticated;
alter default privileges in schema public revoke all on sequences from public, anon, authenticated;
alter default privileges in schema public revoke execute on functions from public, anon, authenticated;

-- 2) RLS en todas las tablas -------------------------------------------------
alter table public.profiles      enable row level security;
alter table public.agents        enable row level security;
alter table public.settings      enable row level security;
alter table public.jobs          enable row level security;
alter table public.agent_runs    enable row level security;
alter table public.tasks         enable row level security;
alter table public.budget_limits enable row level security;
alter table public.audit_log     enable row level security;
alter table public.proposals     enable row level security;

-- 3) Humanos del panel (authenticated) --------------------------------------
grant execute on function public.current_human_role() to authenticated;

-- Lectura para cualquier humano con perfil (owner o viewer).
grant select on public.profiles, public.agents, public.settings, public.jobs, public.agent_runs,
                public.tasks, public.budget_limits, public.audit_log, public.proposals
  to authenticated;

create policy humans_read on public.profiles      for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.agents        for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.settings      for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.jobs          for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.agent_runs    for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.tasks         for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.budget_limits for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.audit_log     for select to authenticated using (public.current_human_role() is not null);
create policy humans_read on public.proposals     for select to authenticated using (public.current_human_role() is not null);

-- Escritura solo para owners, y solo donde tiene sentido.
grant insert (title, description, status, priority, assigned_agent, due_date),
      update (title, description, status, priority, assigned_agent, due_date, updated_at)
  on public.tasks to authenticated;
create policy owners_insert on public.tasks for insert to authenticated
  with check (public.current_human_role() = 'owner' and created_by_type = 'human');
create policy owners_update on public.tasks for update to authenticated
  using (public.current_human_role() = 'owner') with check (public.current_human_role() = 'owner');

grant update (value, updated_at, updated_by) on public.settings to authenticated;
create policy owners_update on public.settings for update to authenticated
  using (public.current_human_role() = 'owner')
  with check (public.current_human_role() = 'owner' and updated_by = auth.uid());

grant insert (scope, period, limit_usd), update (limit_usd, updated_at) on public.budget_limits to authenticated;
create policy owners_insert on public.budget_limits for insert to authenticated
  with check (public.current_human_role() = 'owner');
create policy owners_update on public.budget_limits for update to authenticated
  using (public.current_human_role() = 'owner') with check (public.current_human_role() = 'owner');

grant update (model, effort, enabled, updated_at) on public.agents to authenticated;
create policy owners_update on public.agents for update to authenticated
  using (public.current_human_role() = 'owner') with check (public.current_human_role() = 'owner');

-- Aprobaciones: solo mediante funciones (que exigen owner).
grant execute on function public.approve_proposal(uuid, text, text) to authenticated;
grant execute on function public.reject_proposal(uuid, text) to authenticated;
grant execute on function public.audit_verify_chain() to authenticated;

-- 4) Agentes (puavi_agent) ---------------------------------------------------
grant select on public.agents, public.settings, public.tasks, public.budget_limits,
                public.proposals, public.jobs
  to puavi_agent, puavi_supervisor;

create policy processes_read on public.agents        for select to puavi_agent, puavi_supervisor using (true);
create policy processes_read on public.settings      for select to puavi_agent, puavi_supervisor using (true);
create policy processes_read on public.tasks         for select to puavi_agent, puavi_supervisor using (true);
create policy processes_read on public.budget_limits for select to puavi_agent, puavi_supervisor using (true);
create policy processes_read on public.proposals     for select to puavi_agent, puavi_supervisor using (true);
create policy processes_read on public.jobs          for select to puavi_agent, puavi_supervisor using (true);

grant execute on function
  public.agent_submit_proposal(text, public.action_type, text, text, jsonb, text, numeric, text, uuid),
  public.agent_create_task(text, text, text, int, text, date),
  public.agent_update_task_status(text, uuid, public.task_status)
  to puavi_agent;

grant execute on function
  public.enqueue_job(text, text, jsonb, timestamptz, int, text, uuid),
  public.claim_jobs(text, int, text[]),
  public.complete_job(uuid, text, jsonb),
  public.fail_job(uuid, text, text),
  public.record_agent_run(text, uuid, text, int, int, int, int, int, numeric, text, text, jsonb),
  public.check_budget(text),
  public.log_event(public.actor_type, text, text, text, text, jsonb)
  to puavi_agent, puavi_supervisor;

-- 5) Supervisor ---------------------------------------------------------------
grant execute on function public.supervisor_review(uuid, text, text) to puavi_supervisor;

-- 6) Ejecutor -------------------------------------------------------------------
grant execute on function
  public.executor_list_ready(int),
  public.executor_claim_proposal(uuid),
  public.executor_complete(uuid, boolean, jsonb),
  public.log_event(public.actor_type, text, text, text, text, jsonb)
  to puavi_executor;

-- ===== 20261108000600_schedules.sql =====
-- =============================================================================
-- PUAVI AI · Migración 0006 · Tareas programadas (pg_cron)
--
-- pg_cron trabaja en UTC. 05:00 UTC = 06:00 (invierno) / 07:00 (verano) en
-- Madrid. Si pg_cron no está disponible (p. ej. Postgres local de pruebas),
-- la migración no hace nada.
-- =============================================================================

do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'pg_cron') then
    create extension if not exists pg_cron;
    perform cron.schedule('puavi-daily-plan', '0 5 * * *', 'select public.enqueue_daily_plan()');
    perform cron.schedule('puavi-expire-proposals', '*/15 * * * *', 'select public.expire_proposals()');
  else
    raise notice 'pg_cron no disponible: tareas programadas omitidas';
  end if;
end
$$;

-- ===== 20261108000700_content.sql =====
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

-- ===== 20261108000800_operations.sql =====
-- =============================================================================
-- PUAVI AI · Migración 0008 · Operación: revisiones periódicas y "ejecutar ahora"
-- =============================================================================

-- Revisión del supervisor cada 30 minutos (deduplicada por franja).
create function public.enqueue_periodic_review()
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_slot text := to_char(date_trunc('hour', now()) + floor(extract(minute from now()) / 30)
                         * interval '30 minutes', 'YYYY-MM-DD"T"HH24:MI');
begin
  return public.enqueue_job('supervisor', 'review.pending', '{}'::jsonb, now(), 20,
                            'review.pending:' || v_slot, null);
end
$$;

-- El owner puede lanzar a mano un trabajo de la lista permitida desde el panel.
create function public.request_run(p_kind text)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_agent text;
  v_id uuid;
begin
  if auth.uid() is null or public.current_human_role() is distinct from 'owner' then
    raise exception 'Solo un owner puede lanzar trabajos' using errcode = 'insufficient_privilege';
  end if;
  v_agent := case p_kind
    when 'daily.plan' then 'principal'
    when 'daily.report' then 'principal'
    when 'trends.daily' then 'marketing'
    when 'research.daily' then 'investigacion'
    when 'content.scripts' then 'creativo'
    when 'video.render' then 'creativo'
    when 'shopify.audit' then 'shopify'
    when 'metrics.daily' then 'analitico'
    when 'review.pending' then 'supervisor'
  end;
  if v_agent is null then
    raise exception 'Trabajo no permitido: %', p_kind using errcode = 'check_violation';
  end if;
  v_id := public.enqueue_job(v_agent, p_kind,
            jsonb_build_object('date', to_char(now() at time zone public.setting_text('timezone', 'Europe/Madrid'), 'YYYY-MM-DD'),
                               'manual', true),
            now(), 5, null, null);
  perform public.audit_write('human', auth.uid()::text, 'job.requested', 'job', v_id::text,
          jsonb_build_object('kind', p_kind));
  return v_id;
end
$$;

revoke execute on function public.enqueue_periodic_review() from public, anon, authenticated;
revoke execute on function public.request_run(text) from public, anon;
grant execute on function public.request_run(text) to authenticated;

do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    perform cron.schedule('puavi-periodic-review', '*/30 * * * *',
                          'select public.enqueue_periodic_review()');
  end if;
end
$$;
