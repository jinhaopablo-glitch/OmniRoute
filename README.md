# PUAVI AI

Sistema de agentes de IA para el marketing de **PUAVI** (productos para perros y gatos):
investigación, contenido, tienda y análisis, con **aprobación humana obligatoria** para
cualquier acción sensible.

> Los agentes proponen · el supervisor revisa · tú decides · solo el ejecutor actúa.

## Qué hace cada día, solo

| Hora (Madrid) | Agente | Trabajo |
|---|---|---|
| ~06:00 | Principal | Planifica el día y reparte tareas |
| ~06:00 | Analítico | Ventas de Shopify, alcance de Instagram, datos de TikTok |
| ~06:00 | Marketing | Tendencias en TikTok/Instagram e ideas de contenido |
| ~06:05 | Investigación | Productos con potencial, proveedores, competencia y márgenes |
| ~06:10 | Shopify | Auditoría de fichas → propuestas de mejora y precio |
| ~06:30 | Creativo | Guiones, subtítulos y pies de foto |
| ~07:00 | Creativo | Vídeos verticales con voz → propuestas de publicación |
| cada 30 min | Supervisor | Control de calidad y normas de marca (nunca aprueba) |
| ~08:00 | Principal | Informe diario y tareas prioritarias para ti |

Tú: abres el panel, lees el informe y **apruebas o rechazas**.

## Estado

| Fase | Contenido | Estado |
|---|---|---|
| F0 · Cimientos | Esquema, RLS, aprobaciones, auditoría inalterable, cola, presupuestos | ✅ |
| F1 · Panel | 10 secciones en español, responsive, identidad PUAVI | ✅ |
| F2 · Agentes | Orquestador, 7 agentes, informe diario, control de coste | ✅ |
| F3 · Shopify + analítico | Auditoría de fichas, cambios de precio/ficha aprobados, métricas | ✅ |
| F4 · Vídeo | Guiones, voz (ElevenLabs), montaje vertical con FFmpeg, galería, calendario | ✅ |
| F5 · Publicación | Instagram Reels; TikTok como borrador (o directo tras auditoría) | ✅ |
| F6 · Anuncios y email | Meta Ads (siempre en pausa) y Brevo | ✅ |

Las integraciones están probadas con simulaciones de sus APIs; la primera conexión real con
tus cuentas se verifica en el Paso 5 de la guía de despliegue.

## Estructura

```
supabase/migrations/   Esquema, aprobaciones, auditoría, RLS, pg_cron
backend/puavi/agents/  Los 7 agentes y sus tareas
backend/puavi/llm/     Cliente de Claude con presupuesto y coste
backend/puavi/integrations/  Shopify, Instagram, TikTok, ElevenLabs, Storage, Meta Ads, Brevo
backend/puavi/media/   Montaje de vídeo con FFmpeg
backend/puavi/worker/  Proceso que ejecuta a los agentes
backend/puavi/executor/  Único proceso que ejecuta acciones aprobadas
dashboard/             Panel web (React + TypeScript)
deploy/                Dockerfile y configuración de Fly.io
brand/                 Guía de marca que leen los agentes
docs/                  Despliegue y seguridad
```

## Documentación

- **Puesta en marcha paso a paso:** [`docs/despliegue.md`](docs/despliegue.md)
- Seguridad: [`docs/seguridad.md`](docs/seguridad.md)
- Marca: [`brand/puavi-brand.md`](brand/puavi-brand.md)

## Desarrollo

```bash
cd backend && pip install -e ".[dev]"
ruff check . && ruff format --check .
PUAVI_TEST_ADMIN_DSN=postgresql://postgres:postgres@localhost:5432/postgres pytest

cd dashboard && npm ci && npm run typecheck && npm test && npm run build
```
