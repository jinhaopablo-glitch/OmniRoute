import { useState } from "react";
import { Empty, ErrorBox, Loading, PageHead, StatusBadge } from "../components/ui";
import { useAuth } from "../lib/auth";
import { AGENT_NAMES, fmtDateTime, fmtUsd, JOB_KIND, JOB_STATUS, timeAgo } from "../lib/format";
import { supabase } from "../lib/supabase";
import type { Agent, AgentRun, Job } from "../lib/types";
import { translateError, unwrap, useData } from "../lib/useData";

const RUNNABLE = Object.keys(JOB_KIND);

export function Actividad() {
  const { isOwner } = useAuth();
  const [kind, setKind] = useState("daily.plan");
  const [msg, setMsg] = useState<string | null>(null);
  const state = useData(async () => {
    const [agents, jobs, runs] = await Promise.all([
      supabase.from("agents").select("*").order("id"),
      supabase.from("jobs").select("*").order("created_at", { ascending: false }).limit(40),
      supabase.from("agent_runs").select("*").order("created_at", { ascending: false }).limit(40),
    ]);
    return { agents: unwrap(agents) as Agent[], jobs: unwrap(jobs) as Job[], runs: unwrap(runs) as AgentRun[] };
  }, [], 20_000);

  async function runNow() {
    setMsg(null);
    const { error } = await supabase.rpc("request_run", { p_kind: kind });
    setMsg(error ? translateError(error.message) : `"${JOB_KIND[kind]}" añadido a la cola. Empezará en menos de un minuto.`);
    state.reload();
  }

  const d = state.data;
  return (
    <>
      <PageHead title="Actividad de los agentes" subtitle="Qué están haciendo y cuánto cuesta.">
        {isOwner && (
          <>
            <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Trabajo a lanzar" style={{ width: "auto" }}>
              {RUNNABLE.map((k) => (
                <option key={k} value={k}>
                  {JOB_KIND[k]}
                </option>
              ))}
            </select>
            <button className="btn primary" onClick={() => void runNow()}>
              Ejecutar ahora
            </button>
          </>
        )}
      </PageHead>
      {msg && <div className="notice" style={{ marginBottom: 12 }}>{msg}</div>}
      <ErrorBox error={state.error} />
      {state.loading && !d ? (
        <Loading lines={6} />
      ) : d ? (
        <>
          <div className="grid k4">
            {d.agents.map((a) => {
              const last = d.runs.find((r) => r.agent_id === a.id);
              return (
                <div key={a.id} className="card">
                  <div className="row">
                    <h3>{a.name}</h3>
                    <span className="spacer" />
                    <span className={`badge ${a.enabled ? "ok" : "gray"}`}>{a.enabled ? "Activo" : "Pausado"}</span>
                  </div>
                  <p className="muted" style={{ marginTop: 6 }}>
                    {a.description}
                  </p>
                  <p className="muted" style={{ marginTop: 8 }}>
                    {last ? `Última vez ${timeAgo(last.created_at)}` : "Sin ejecuciones todavía"}
                  </p>
                </div>
              );
            })}
          </div>

          <div className="card section">
            <h2 style={{ marginBottom: 10 }}>Cola de trabajos</h2>
            {d.jobs.length === 0 ? (
              <Empty>Sin trabajos. El plan diario se lanza automáticamente cada mañana.</Empty>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Trabajo</th>
                      <th>Agente</th>
                      <th>Estado</th>
                      <th>Intentos</th>
                      <th>Programado</th>
                      <th>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.jobs.map((j) => (
                      <tr key={j.id}>
                        <td>{JOB_KIND[j.kind] ?? j.kind}</td>
                        <td>{AGENT_NAMES[j.agent_id] ?? j.agent_id}</td>
                        <td>
                          <StatusBadge map={JOB_STATUS} value={j.status} />
                        </td>
                        <td>{j.attempts}</td>
                        <td>{fmtDateTime(j.run_after)}</td>
                        <td className="muted" style={{ maxWidth: 280 }}>
                          {j.last_error ?? ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card section">
            <h2 style={{ marginBottom: 10 }}>Ejecuciones de IA</h2>
            {d.runs.length === 0 ? (
              <Empty>Sin ejecuciones todavía.</Empty>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Cuándo</th>
                      <th>Agente</th>
                      <th>Resumen</th>
                      <th>Búsquedas</th>
                      <th>Coste</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.runs.map((r) => (
                      <tr key={r.id}>
                        <td>{fmtDateTime(r.created_at)}</td>
                        <td>{AGENT_NAMES[r.agent_id] ?? r.agent_id}</td>
                        <td>{r.summary}</td>
                        <td>{r.web_searches}</td>
                        <td>{fmtUsd(r.cost_usd)}</td>
                        <td>
                          <span className={`badge ${r.status === "ok" ? "ok" : r.status === "blocked" ? "warn" : "bad"}`}>
                            {r.status === "ok" ? "Bien" : r.status === "blocked" ? "Bloqueado" : "Error"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : null}
    </>
  );
}
