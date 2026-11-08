# Traspaso · PUAVI AI (estado a 8 nov 2026)

Documento para retomar el trabajo en otra sesión o con otra persona.
**No contiene contraseñas ni claves**: esas están solo en el gestor de contraseñas de la dueña/el dueño.

## 1. Dónde está todo

- **Código:** repositorio GitHub `jinhaopablo-glitch/OmniRoute`, rama
  `claude/puavi-ai-marketing-system-t87bwp`. La rama solo contiene PUAVI AI (no tiene relación
  con OmniRoute). Para moverlo a un repositorio propio:
  `git push https://github.com/jinhaopablo-glitch/puavi-ai claude/puavi-ai-marketing-system-t87bwp:main`
- **Guía de puesta en marcha:** `docs/despliegue.md` · **Seguridad:** `docs/seguridad.md`
- **Instalación de la base de datos en un solo archivo:** `supabase/instalacion_completa.sql`

## 2. Qué está construido (fases 0-6) ✅

| Parte | Estado |
|---|---|
| Base de datos: aprobaciones, auditoría inalterable, cola, presupuestos, contenido | Hecho y probado |
| 7 agentes + worker + plan diario automático | Hecho, probado con IA simulada |
| Integraciones: Shopify, Instagram, TikTok, ElevenLabs, Storage, Meta Ads, Brevo | Hecho, probado con APIs simuladas |
| Montaje de vídeo con FFmpeg | Hecho, probado con vídeo real |
| Panel web (10 secciones, móvil y escritorio) | Hecho, revisado en navegador |
| Despliegue (Docker, Railway/Fly.io, Cloudflare Pages) | Preparado, **sin probar** (no había Docker) |
| Tests | 91 backend + 6 panel, todos pasan |

## 3. Puesta en marcha: dónde nos quedamos

| Paso | Estado |
|---|---|
| 1. Proyecto Supabase creado, pg_cron activado, instalación ejecutada | ✅ |
| 2. Usuario propietario creado (rol `owner`) | ✅ |
| 2.3 Desactivar "Allow new users to sign up" | ❓ **sin confirmar** |
| 3. Usuarios técnicos de BD (`puavi_agent_login`, `puavi_supervisor_login`, `puavi_executor_login`) con contraseñas guardadas | ✅ |
| 4. Usuario técnico de vídeos `almacen@puavi.app` (sin perfil, `can_write = true`) | ✅ |
| 5. Clave de Anthropic creada y guardada | ✅ |
| 6. Configuración económica: 7 agentes en `claude-haiku-5-5` / `low`; límites 1 $/día y 15 $/mes | ✅ |
| **7. Railway: proyecto y servicio `puavi-agentes`** | ⏳ **EN CURSO** |
| 8. Variables del worker en Railway | Pendiente |
| 9. Servicio `puavi-ejecutor` (en modo prueba) | Pendiente |
| 10. Panel en Cloudflare Pages | Pendiente |
| 11. Primera prueba: "Ejecutar ahora → Plan del día" | Pendiente |
| 12. Conectar Shopify, Instagram, TikTok, ElevenLabs | Pendiente (opcional, uno a uno) |

### Paso 7 (en curso): lo que había que hacer en Railway
1. New Project → Deploy from GitHub repo → OmniRoute (el primer build falla: normal).
2. Settings del servicio: nombre `puavi-agentes`; **Branch** `claude/puavi-ai-marketing-system-t87bwp`;
   **Custom Start Command** `python -m puavi.worker`; **sin** dominio público.
3. Variables: `RAILWAY_DOCKERFILE_PATH=deploy/Dockerfile`.
4. Pendiente de confirmar: si el build termina bien (`Successfully built`) y qué error da al
   arrancar (esperado: faltan variables).

### Paso 8 (siguiente): variables del worker `puavi-agentes`
Pegarlas en Railway → Variables → **Raw Editor** (nunca en un chat):
```
PUAVI_AGENT_DB_URL=postgresql://puavi_agent_login.<ref>:<contraseña>@<host-pooler>:5432/postgres
PUAVI_SUPERVISOR_DB_URL=postgresql://puavi_supervisor_login.<ref>:<contraseña>@<host-pooler>:5432/postgres
ANTHROPIC_API_KEY=<clave sk-ant-...>
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=<clave anon o publishable>
PUAVI_STORAGE_EMAIL=almacen@puavi.app
PUAVI_STORAGE_PASSWORD=<contraseña de almacen>
```
- `<ref>` y `<host-pooler>`: Supabase → **Connect → Session pooler** (formato
  `postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-…pooler.supabase.com:5432/postgres`; cambiar
  `postgres.` por el usuario técnico).
- Clave anon: Supabase → Project Settings → API Keys.
- **No** poner en este servicio ninguna variable del ejecutor (el worker se niega a arrancar).
- Éxito = en los logs aparece `Worker worker-1 iniciado`.

## 4. Decisiones tomadas

- Base de datos y archivos: **Supabase** (plan gratuito para empezar).
- Hosting de agentes: **Railway** (sin terminal) en lugar de Fly.io.
- IA en **modo económico** (Haiku). Subir calidad por agente desde Configuración del panel.
- Ejecutor en **modo prueba** (`PUAVI_EXECUTOR_DRY_RUN=true`) hasta validar unos días.
- TikTok en modo **borrador** (`TIKTOK_POST_MODE=inbox`) hasta que TikTok audite la app.
- Colores oficiales: verde `#203D2B`, crema `#F5EBD8`, terracota `#C66A3D`
  (terracota oscura `#A4532C` para texto pequeño).

## 5. Credenciales que existen (solo nombres)

| Credencial | Dónde está guardada |
|---|---|
| Contraseña de la base de datos de Supabase | Gestor de contraseñas |
| Contraseñas de `puavi_agent_login`, `puavi_supervisor_login`, `puavi_executor_login` | Gestor de contraseñas |
| Contraseña de `almacen@puavi.app` | Gestor de contraseñas ("PUAVI almacén") |
| Contraseña del usuario propietario del panel | Gestor de contraseñas |
| Clave de API de Anthropic (`puavi-agentes`) | Gestor de contraseñas |

Si alguna se pierde: las de BD se regeneran volviendo a ejecutar el SQL del paso 3; la de
Anthropic se revoca y se crea otra en console.anthropic.com.

## 6. Avisos importantes

- La instalación SQL solo funciona en un proyecto Supabase **vacío** (tiene un freno de seguridad).
- Supabase muestra avisos de "destructive operation" y "RLS" al pegar el SQL: son falsas alarmas,
  se confirman con "Run this query" / "Run without RLS" (solo en la tabla temporal de contraseñas).
- Las versiones de API usadas: Shopify `2026-10`, Meta Graph `v23.0` (configurables por variable).
