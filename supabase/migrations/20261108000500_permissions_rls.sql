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
