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
