// Formato y textos en español para todo el panel.

const eur = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });
const usd = new Intl.NumberFormat("es-ES", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const num = new Intl.NumberFormat("es-ES");
const dateFmt = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", timeZone: "Europe/Madrid" });
const dateTimeFmt = new Intl.DateTimeFormat("es-ES", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid",
});

export const fmtEur = (v: number | string | null | undefined) =>
  v === null || v === undefined || v === "" ? "—" : eur.format(Number(v));
export const fmtUsd = (v: number | string | null | undefined) =>
  v === null || v === undefined ? "—" : usd.format(Number(v));
export const fmtNum = (v: number | string | null | undefined) =>
  v === null || v === undefined ? "—" : num.format(Number(v));
export const fmtDate = (v: string | null | undefined) => (v ? dateFmt.format(new Date(v)) : "—");
export const fmtDateTime = (v: string | null | undefined) => (v ? dateTimeFmt.format(new Date(v)) : "—");

export function timeAgo(v: string, now: Date = new Date()): string {
  const s = Math.round((now.getTime() - new Date(v).getTime()) / 1000);
  if (s < 60) return "hace un momento";
  const m = Math.round(s / 60);
  if (m < 60) return `hace ${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `hace ${h} h`;
  const d = Math.round(h / 24);
  return `hace ${d} ${d === 1 ? "día" : "días"}`;
}

/** Día en Madrid como AAAA-MM-DD. */
export function madridDay(d: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Madrid" }).format(d);
}

export const ACTION_LABELS: Record<string, string> = {
  publish_content: "Publicar contenido",
  change_price: "Cambiar precio",
  modify_product: "Modificar producto",
  launch_ad: "Lanzar anuncio",
  spend_money: "Gastar dinero",
  send_commercial_comm: "Comunicación comercial",
  other_sensitive: "Otra acción sensible",
};

export const PROPOSAL_STATUS: Record<string, [string, string]> = {
  pending_review: ["En revisión del supervisor", "gray"],
  pending_approval: ["Pendiente de tu aprobación", "terra"],
  approved: ["Aprobada", "ok"],
  rejected: ["Rechazada", "bad"],
  executing: ["Ejecutando", "warn"],
  executed: ["Ejecutada", "ok"],
  failed: ["Falló", "bad"],
  expired: ["Caducada", "gray"],
  cancelled: ["Cancelada", "gray"],
};

export const RISK: Record<string, [string, string]> = {
  low: ["Riesgo bajo", "ok"],
  medium: ["Riesgo medio", "warn"],
  high: ["Riesgo alto", "bad"],
};

export const CONTENT_STATUS: Record<string, [string, string]> = {
  draft: ["Borrador", "gray"],
  in_review: ["En revisión", "warn"],
  ready: ["Listo", "ok"],
  scheduled: ["Programado", "terra"],
  published: ["Publicado", "ok"],
  discarded: ["Descartado", "gray"],
  flagged: ["Con problemas", "bad"],
};

export const CONTENT_KIND: Record<string, string> = {
  trend: "Tendencia", idea: "Idea", script: "Guion", video: "Vídeo", post: "Publicación",
};

export const TASK_STATUS: Record<string, string> = {
  todo: "Pendiente", in_progress: "En curso", blocked: "Bloqueada", done: "Hecha", cancelled: "Cancelada",
};

export const JOB_STATUS: Record<string, [string, string]> = {
  queued: ["En cola", "gray"],
  running: ["Trabajando", "warn"],
  done: ["Hecho", "ok"],
  failed: ["Falló", "bad"],
  cancelled: ["Cancelado", "gray"],
};

export const JOB_KIND: Record<string, string> = {
  "daily.plan": "Plan del día",
  "daily.report": "Informe diario",
  "trends.daily": "Tendencias",
  "research.daily": "Investigación",
  "content.scripts": "Guiones",
  "video.render": "Vídeos",
  "shopify.audit": "Auditoría Shopify",
  "metrics.daily": "Métricas",
  "review.pending": "Revisión de calidad",
};

export const AGENT_NAMES: Record<string, string> = {
  principal: "Principal", marketing: "Marketing", creativo: "Creativo", investigacion: "Investigación",
  shopify: "Shopify", analitico: "Analítico", supervisor: "Supervisor", executor: "Ejecutor",
};

/** Texto legible para una línea del historial. */
export function describeAudit(action: string): string {
  const map: Record<string, string> = {
    "proposal.created": "Propuesta creada",
    "proposal.reviewed": "Propuesta revisada por el supervisor",
    "proposal.approved": "Propuesta aprobada",
    "proposal.rejected": "Propuesta rechazada",
    "proposal.executing": "Ejecución iniciada",
    "proposal.executed": "Acción ejecutada",
    "proposal.execution_failed": "La ejecución falló",
    "proposal.claim_refused": "Ejecución bloqueada por seguridad",
    "proposal.expired_batch": "Propuestas caducadas",
    "content.created": "Contenido creado",
    "content.updated": "Contenido actualizado",
    "content.published": "Contenido publicado",
    "report.saved": "Informe guardado",
    "job.completed": "Trabajo completado",
    "job.requested": "Trabajo lanzado a mano",
    "security.injection_warning": "Posible manipulación detectada en una web",
  };
  if (map[action]) return map[action];
  const [table, op] = action.split(".");
  const ops: Record<string, string> = { insert: "creado", update: "modificado", delete: "eliminado" };
  return ops[op] ? `${table}: ${ops[op]}` : action;
}

/** Medianoche de hoy en Madrid como ISO con su desfase (horario de verano incluido). */
export function madridMidnightISO(d: Date = new Date()): string {
  const off =
    new Intl.DateTimeFormat("en-US", { timeZone: "Europe/Madrid", timeZoneName: "shortOffset" })
      .formatToParts(d)
      .find((p) => p.type === "timeZoneName")?.value ?? "GMT+1";
  const m = off.match(/GMT([+-])(\d+)/);
  const sign = m ? m[1] : "+";
  const hours = m ? m[2].padStart(2, "0") : "01";
  return `${madridDay(d)}T00:00:00${sign}${hours}:00`;
}
