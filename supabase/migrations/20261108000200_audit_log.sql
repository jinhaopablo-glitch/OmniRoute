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
