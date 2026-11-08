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
