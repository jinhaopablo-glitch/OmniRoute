# Puesta en marcha de PUAVI AI

Guía paso a paso. Tiempo estimado: 2-3 horas la primera vez. Puedes hacerla por partes:
el sistema funciona con lo que conectes y avisa de lo que falta.

> **Nunca pegues contraseñas ni claves en chats, correos o documentos compartidos.**
> Van solo en los paneles de secretos de Supabase, Fly.io y Cloudflare.

## Resumen de piezas

| Pieza | Dónde vive | Coste aprox. |
|---|---|---|
| Base de datos, usuarios, archivos, tareas programadas | Supabase (plan Pro) | 25 $/mes |
| Worker de agentes | Fly.io, app `puavi-agents` | ~6 $/mes |
| Ejecutor | Fly.io, app `puavi-executor` | ~3 $/mes |
| Panel | Cloudflare Pages | 0 € |
| IA | API de Claude (Anthropic) | según uso, con topes |

---

## Paso 1 · Supabase (base de datos)

1. Crea un proyecto en <https://supabase.com> (región **Frankfurt**). Guarda la contraseña de
   la base de datos en tu gestor de contraseñas.
2. **Database → Extensions**: activa `pg_cron`.
3. **SQL Editor**: ejecuta, **en orden**, cada archivo de `supabase/migrations/`
   (del `…000100_foundation.sql` al último). Con la CLI: `supabase link` + `supabase db push`.
   *No* ejecutes `supabase/tests/local_bootstrap.sql` (solo es para pruebas).
4. **Usuarios técnicos de base de datos.** En el SQL Editor, con tres contraseñas largas
   generadas por tu gestor de contraseñas:
   ```sql
   create role puavi_agent_login      login password '<contraseña-1>' in role puavi_agent;
   create role puavi_supervisor_login login password '<contraseña-2>' in role puavi_supervisor;
   create role puavi_executor_login   login password '<contraseña-3>' in role puavi_executor;
   ```
   Las URL de conexión salen de **Connect → Session pooler**, cambiando el usuario por cada uno
   de estos (formato `postgresql://puavi_agent_login.<ref>:<contraseña>@<host>:5432/postgres`).
5. **Tu usuario (owner).** Authentication → Users → *Add user* con tu email y una contraseña.
   Después, en el SQL Editor:
   ```sql
   insert into public.profiles (user_id, display_name, role)
   select id, 'Tu nombre', 'owner' from auth.users where email = '<tu-email>';
   ```
   Activa también **MFA** (verificación en dos pasos) en Authentication.
6. **Usuario técnico de archivos** (para que los agentes guarden vídeos). Authentication → Users →
   *Add user* con un email tipo `storage@puavi.es` y contraseña larga. Después:
   ```sql
   insert into public.storage_service_users (user_id, label, can_write)
   select id, 'worker', true from auth.users where email = 'storage@puavi.es';
   ```
   Este usuario **no tiene perfil**: no puede ver el panel ni aprobar nada.
7. En **Authentication → Providers → Email**, desactiva *Enable sign ups* para que nadie más
   pueda registrarse.

## Paso 2 · Claves de servicios

Crea solo las que vayas a usar; puedes añadir más después.

| Servicio | Qué crear | Permisos |
|---|---|---|
| **Anthropic** | Clave de API en console.anthropic.com. Pon también un límite de gasto mensual allí. | — |
| **Shopify (lectura)** | Admin → Apps → Desarrollar apps → app "PUAVI lectura" | `read_products`, `read_orders`, `read_inventory` |
| **Shopify (escritura)** | Otra app "PUAVI escritura" | `write_products`, `read_products` |
| **Instagram** | App de Meta con tu cuenta Business/Creator vinculada a la página de Facebook. Token de **lectura** (`instagram_basic`, `instagram_manage_insights`) y token de **publicación** (`instagram_content_publish`). | Separados |
| **TikTok** | App en developers.tiktok.com con Content Posting API. Sin auditoría, usa `TIKTOK_POST_MODE=inbox` (el vídeo llega como borrador a tu app). | `video.upload`, `user.info.stats` |
| **ElevenLabs** | Clave de API y el ID de la voz elegida | — |
| **Meta Ads** (opcional) | `ads_management` en el token de publicación y el ID de la cuenta publicitaria | Las campañas se crean **en pausa** |
| **Brevo** (opcional) | Clave de API y email remitente verificado | Solo listas con consentimiento |

## Paso 3 · Agentes y ejecutor en Fly.io

1. Instala `flyctl` y entra con `fly auth login`.
2. Desde la raíz del repositorio:
   ```bash
   fly apps create puavi-agents
   fly apps create puavi-executor
   ```
3. Secretos del **worker** (solo el bloque 1 de `.env.example`):
   ```bash
   fly secrets set -a puavi-agents ANTHROPIC_API_KEY=... PUAVI_AGENT_DB_URL=... \
     PUAVI_SUPERVISOR_DB_URL=... SHOPIFY_STORE_DOMAIN=... SHOPIFY_READ_TOKEN=... \
     SUPABASE_URL=... SUPABASE_ANON_KEY=... PUAVI_STORAGE_EMAIL=... PUAVI_STORAGE_PASSWORD=...
   ```
4. Secretos del **ejecutor** (solo el bloque 2). Déjalo con `PUAVI_EXECUTOR_DRY_RUN=true`
   hasta haber probado el sistema unos días.
5. Despliega:
   ```bash
   fly deploy . --config deploy/fly.worker.toml   --dockerfile deploy/Dockerfile
   fly deploy . --config deploy/fly.executor.toml --dockerfile deploy/Dockerfile
   ```
6. Comprueba los registros: `fly logs -a puavi-agents` debe mostrar
   `Worker worker-1 iniciado · shopify=True …`.

## Paso 4 · Panel en Cloudflare Pages

1. En Cloudflare → Workers & Pages → *Create* → Pages → conecta el repositorio.
2. Configuración de compilación:
   - Directorio raíz: `dashboard`
   - Comando: `npm ci && npm run build`
   - Directorio de salida: `dist`
   - Variables: `VITE_SUPABASE_URL` y `VITE_SUPABASE_ANON_KEY` (Supabase → Project Settings → API).
3. Abre la URL que te da Cloudflare y entra con tu email. (Opcional: protege además la URL con
   Cloudflare Access para que solo tu email pueda abrirla.)
4. En Supabase → Authentication → URL Configuration, pon esa URL como *Site URL*.

## Paso 5 · Primera prueba

1. En el panel → **Actividad** → *Ejecutar ahora* → "Plan del día".
2. En unas dos horas tendrás tendencias, ideas, guiones, vídeos, propuestas e informe.
3. Revisa la **Bandeja de aprobaciones**. Con el ejecutor en modo prueba, lo aprobado se queda
   esperando (no se consume). Cuando confíes en el sistema, pon
   `fly secrets set -a puavi-executor PUAVI_EXECUTOR_DRY_RUN=false`.

## Funcionamiento diario automático

- **05:00 UTC** (06:00/07:00 en Madrid): `pg_cron` lanza el plan diario.
- El Agente Principal reparte el trabajo escalonado durante ~2 horas y termina con el informe.
- Cada 30 minutos el supervisor revisa lo nuevo.
- Tu único trabajo: abrir el panel, leer el informe y aprobar o rechazar.

## Si algo va mal

| Síntoma | Qué mirar |
|---|---|
| No aparece nada | Actividad → ¿hay trabajos en cola? `fly logs -a puavi-agents` |
| Trabajos con "Presupuesto" | Configuración → límites de gasto |
| Trabajos fallidos | La columna "Error" en Actividad; se reintentan solos 3 veces |
| Aprobé y no se ejecuta | ¿Ejecutor en modo prueba? `fly logs -a puavi-executor` |
| Quiero pararlo todo ya | Configuración → **Detener todo** |

## Desarrollo local y pruebas

```bash
cd backend && pip install -e ".[dev]"
PUAVI_TEST_ADMIN_DSN=postgresql://postgres:postgres@localhost:5432/postgres pytest
cd ../dashboard && npm ci && npm test && npm run build
```
Los tests de base de datos crean y borran una base de datos temporal: usa un Postgres
desechable, nunca el de producción.
