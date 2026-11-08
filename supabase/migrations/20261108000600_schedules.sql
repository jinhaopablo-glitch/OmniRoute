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
