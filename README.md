# PUAVI AI

Sistema de agentes de IA para el marketing de **PUAVI** (productos para perros y gatos):
investigación, contenido, tienda y análisis, con **aprobación humana obligatoria** para
cualquier acción sensible.

> Los agentes proponen · el supervisor revisa · tú decides · solo el ejecutor actúa.

## Estado

| Fase | Contenido | Estado |
|---|---|---|
| **F0 · Cimientos** | Esquema Supabase, RLS, aprobaciones, auditoría inalterable, cola, presupuestos, ejecutor seguro, CI | ✅ |
| F1 · Panel base | Login, resumen, tareas, bandeja de aprobaciones, historial, configuración | ⏳ |
| F2 · Agentes núcleo | Orquestador, marketing, investigación, creativo, supervisor, informe diario | — |
| F3 · Shopify + analítico | Auditoría de fichas, propuestas de cambios, ejecución aprobada | — |
| F4 · Vídeo | Guiones, voz, montaje vertical, calendario | — |
| F5 · Publicación + métricas | Instagram / TikTok con aprobación | — |
| F6 · Opcional | Anuncios y email comercial | — |

## Estructura

```
supabase/migrations/   Esquema, funciones de aprobación, auditoría, RLS, pg_cron
supabase/tests/        Arranque mínimo para probar en Postgres normal
backend/puavi/core/    Config, BD, auditoría, presupuesto, cola, propuestas
backend/puavi/llm/     Precios y coste por ejecución
backend/puavi/security Contenido no confiable, control de credenciales
backend/puavi/executor Único componente que ejecuta acciones aprobadas
backend/tests/         Tests unitarios y de base de datos (garantías de seguridad)
brand/                 Guía de marca que leen los agentes
docs/                  Seguridad y despliegue
```

## Desarrollo

```bash
cd backend
pip install -e ".[dev]"
ruff check . && ruff format --check .
PUAVI_TEST_ADMIN_DSN=postgresql://postgres:postgres@localhost:5432/postgres pytest
```

- Seguridad: [`docs/seguridad.md`](docs/seguridad.md)
- Despliegue: [`docs/despliegue.md`](docs/despliegue.md)
- Marca: [`brand/puavi-brand.md`](brand/puavi-brand.md)
