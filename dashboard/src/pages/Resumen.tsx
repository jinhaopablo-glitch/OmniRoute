import { Link } from "react-router-dom";
import { Empty, ErrorBox, Loading, Markdown, PageHead, Stat, StatusBadge } from "../components/ui";
import { AGENT_NAMES, fmtEur, fmtNum, fmtUsd, JOB_KIND, JOB_STATUS, madridMidnightISO, timeAgo } from "../lib/format";
import { supabase } from "../lib/supabase";
import type { Job, Metric, Report } from "../lib/types";
import { unwrap, useData } from "../lib/useData";

export function Resumen() {
  const state = useData(async () => {
    const since = madridMidnightISO();
    const [pending, report, metrics, jobs, budget, tasks] = await Promise.all([
      supabase.from("proposals").select("id", { count: "exact", head: true }).eq("status", "pending_approval"),
      supabase.from("reports").select("*").eq("kind", "daily").order("day", { ascending: false }).limit(1),
      supabase.from("metrics_daily").select("*").order("day", { ascending: false }).limit(6),
      supabase.from("jobs").select("*").order("created_at", { ascending: false }).limit(8),
      supabase.from("agent_runs").select("cost_usd").gte("created_at", since),
      supabase.from("tasks").select("id", { count: "exact", head: true }).in("status", ["todo", "in_progress"]),
    ]);
    const shopify = (unwrap(metrics) as Metric[]).find((m) => m.source === "shopify");
    const instagram = (unwrap(metrics) as Metric[]).find((m) => m.source === "instagram");
    return {
      pending: pending.count ?? 0,
      report: (unwrap(report) as Report[])[0] ?? null,
      shopify,
      instagram,
      jobs: unwrap(jobs) as Job[],
      spend: (unwrap(budget) as { cost_usd: string }[]).reduce((a, r) => a + Number(r.cost_usd), 0),
      openTasks: tasks.count ?? 0,
    };
  });

  const d = state.data;
  return (
    <>
      <PageHead title="Resumen" subtitle="Lo importante de hoy, de un vistazo." />
      <ErrorBox error={state.error} />
      {state.loading && !d ? (
        <Loading lines={5} />
      ) : d ? (
        <>
          {d.pending > 0 && (
            <div className="notice row" style={{ marginBottom: 16 }}>
              <strong>Tienes {d.pending} {d.pending === 1 ? "propuesta" : "propuestas"} esperando tu decisión.</strong>
              <span className="spacer" />
              <Link className="btn accent small" to="/aprobaciones">
                Revisar ahora
              </Link>
            </div>
          )}
          <div className="grid k4 keep2">
            <Stat
              label="Ventas (último día)"
              value={fmtEur(d.shopify?.metrics.revenue_eur as number | undefined)}
              hint={d.shopify ? `${fmtNum(d.shopify.metrics.orders as number)} ${Number(d.shopify.metrics.orders) === 1 ? "pedido" : "pedidos"} · ${d.shopify.day}` : "Sin datos de Shopify"}
            />
            <Stat
              label="Alcance Instagram"
              value={fmtNum(d.instagram?.metrics.reach as number | undefined)}
              hint={d.instagram ? `${fmtNum(d.instagram.metrics.followers as number)} seguidores` : "Sin datos de Instagram"}
            />
            <Stat label="Tareas abiertas" value={fmtNum(d.openTasks)} hint={<Link to="/tareas">Ver tareas</Link>} />
            <Stat label="Gasto de IA hoy" value={fmtUsd(d.spend)} hint={<Link to="/configuracion">Límites</Link>} />
          </div>

          <div className="grid k2 section">
            <div className="card">
              <div className="card-head">
                <h2>Informe diario</h2>
                {d.report && <span className="muted">{d.report.day}</span>}
              </div>
              {d.report ? (
                <>
                  <h3 style={{ marginBottom: 8 }}>{d.report.title}</h3>
                  <Markdown text={d.report.body_md} />
                </>
              ) : (
                <Empty>El primer informe aparecerá tras el primer día de trabajo de los agentes.</Empty>
              )}
            </div>
            <div className="card">
              <div className="card-head">
                <h2>Últimos trabajos</h2>
                <Link to="/actividad" className="muted">
                  Ver todo
                </Link>
              </div>
              {d.jobs.length === 0 ? (
                <Empty>Todavía no hay actividad.</Empty>
              ) : (
                d.jobs.map((j) => (
                  <div key={j.id} className="list-item row">
                    <div>
                      <strong>{JOB_KIND[j.kind] ?? j.kind}</strong>
                      <div className="muted">
                        {AGENT_NAMES[j.agent_id] ?? j.agent_id} · {timeAgo(j.created_at)}
                      </div>
                    </div>
                    <span className="spacer" />
                    <StatusBadge map={JOB_STATUS} value={j.status} />
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
