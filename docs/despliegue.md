# Puesta en marcha de la Fase 0

## 1. Proyecto Supabase
1. Crea un proyecto en Supabase (región UE, p. ej. Frankfurt).
2. Aplica las migraciones de `supabase/migrations/` en orden:
   - Con la CLI: `supabase link --project-ref <ref>` y `supabase db push`, o
   - Pegando cada archivo, en orden, en el editor SQL.
   - **No** ejecutes `supabase/tests/local_bootstrap.sql` en Supabase (solo es para tests).
3. Activa la extensión `pg_cron` (Database → Extensions) **antes** de la migración
   `..._schedules.sql`, o vuelve a ejecutarla después.

## 2. Usuarios técnicos de base de datos
En el editor SQL, con contraseñas largas y aleatorias (generadas por ti, no las pegues en chats):

```sql
create role puavi_agent_login      login password '<contraseña-1>' in role puavi_agent;
create role puavi_supervisor_login login password '<contraseña-2>' in role puavi_supervisor;
create role puavi_executor_login   login password '<contraseña-3>' in role puavi_executor;
```

Construye las URL de conexión (Settings → Database → Connection string, modo *session pooler*)
con cada usuario y guárdalas como `PUAVI_AGENT_DB_URL`, `PUAVI_SUPERVISOR_DB_URL` y
`PUAVI_EXECUTOR_DB_URL` en el gestor de secretos del hosting.

## 3. Tu usuario owner
1. Authentication → Users → *Add user* con tu email.
2. En el editor SQL:
   ```sql
   insert into public.profiles (user_id, display_name, role)
   select id, 'Nombre', 'owner' from auth.users where email = '<tu-email>';
   ```
3. Activa la verificación en dos pasos (MFA) en Authentication cuando esté el panel (Fase 1).

## 4. Comprobación
```bash
cd backend
pip install -e ".[dev]"
PUAVI_TEST_ADMIN_DSN=postgresql://postgres:postgres@localhost:5432/postgres pytest
```
Los tests de base de datos necesitan un Postgres desechable (nunca el de producción).

## 5. Ejecutor
`python -m puavi.executor` con `PUAVI_EXECUTOR_DRY_RUN=true` (por defecto). En modo prueba solo
informa de lo que haría y **no consume** aprobaciones. Las integraciones reales llegan en F3+.
