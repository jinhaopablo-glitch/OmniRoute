# Modelo de seguridad de PUAVI AI

## Principio central: los agentes proponen, los humanos deciden y solo el ejecutor actúa

| Componente | Puede | No puede |
|---|---|---|
| Agentes (`puavi_agent`) | Leer config/tareas/propuestas, crear propuestas validadas, usar la cola, registrar costes y eventos | Modificar o aprobar propuestas, escribir tablas directamente, tener credenciales de escritura (el proceso no arranca si las detecta) |
| Supervisor (`puavi_supervisor`) | Revisar propuestas de otros agentes (OK / rechazo) | Crear propuestas, revisar las suyas, aprobar |
| Humano `viewer` | Ver el panel | Escribir nada |
| Humano `owner` | Aprobar/rechazar, gestionar tareas, presupuestos, interruptor de emergencia | Saltarse al supervisor, cambiar el contenido de una propuesta, borrar el historial |
| Ejecutor (`puavi_executor`) | Reclamar propuestas aprobadas y ejecutar el manejador | Leer o escribir tablas directamente, ejecutar algo no aprobado |
| `anon` | Nada | Todo |

Estas restricciones están comprobadas por tests contra Postgres real en `backend/tests/db/`.

## Garantías que impone la base de datos
- **Aprobación ligada al contenido**: el owner aprueba un hash concreto del contenido. El
  contenido es inmutable (trigger) y el ejecutor vuelve a calcular el hash antes de actuar.
- **Aprobador vigente**: si el aprobador deja de ser owner, el ejecutor no ejecuta.
- **Caducidad**: las propuestas caducan (7 días por defecto).
- **Idempotencia**: cada propuesta tiene una clave única, que se envía a las APIs externas.
- **Reintentos limitados**: máximo 3 intentos de ejecución.
- **Historial inalterable**: `audit_log` solo admite inserciones (ni el administrador puede
  modificarlo sin desactivar triggers) y forma una cadena de hashes verificable con
  `audit_verify_chain()`.
- **Presupuesto**: `check_budget()` antes de cada llamada a la IA; interruptor de emergencia
  `kill_switch` que detiene la cola y el gasto.
- **Mínimo privilegio en Supabase**: se revocan los permisos que Supabase da por defecto a
  `anon`/`authenticated`; RLS activa en todas las tablas.

## Contenido externo (inyección de instrucciones)
- Todo texto web/documento se limpia (caracteres invisibles) y se envuelve en delimitadores
  aleatorios marcados como **no confiables** (`puavi/security/untrusted.py`).
- Se detectan señales típicas de inyección y se adjuntan para el supervisor.
- Los agentes que leen contenido externo no tienen herramientas de acción: lo peor que puede
  pasar es una propuesta, que revisa el supervisor y decide un humano.
- Las salidas de los agentes se validan con esquemas Pydantic estrictos (`extra="forbid"`).

## Secretos
- Solo en variables de entorno del hosting; `.env.example` sin valores; escaneo con gitleaks en CI.
- Los secretos se cargan como `SecretStr` (no aparecen en logs ni `repr`).
- La `service_role` key de Supabase no la usa ningún proceso de PUAVI.
- Tokens separados por proceso: Shopify lectura (agentes) y escritura (ejecutor).
