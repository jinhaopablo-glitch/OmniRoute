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
