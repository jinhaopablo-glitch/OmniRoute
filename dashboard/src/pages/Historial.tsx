import { useState } from "react";
import { Badge, Empty, ErrorBox, Loading, PageHead } from "../components/ui";
import { AGENT_NAMES, describeAudit, fmtDateTime } from "../lib/format";
import { supabase } from "../lib/supabase";
import type { AuditRow } from "../lib/types";
import { translateError, unwrap, useData } from "../lib/useData";

const ACTOR: Record<string, [string, string]> = {
  human: ["Persona", "terra"],
  agent: ["Agente", ""],
  supervisor: ["Supervisor", "warn"],
  executor: ["Ejecutor", "ok"],
  system: ["Sistema", "gray"],
};

export function Historial() {
  const [page, setPage] = useState(0);
  const [verify, setVerify] = useState<string | null>(null);
  const size = 50;
  const state = useData(async () => {
    return unwrap(
      await supabase
        .from("audit_log")
        .select("id, at, actor_type, actor_id, action, entity_type, entity_id, details")
        .order("id", { ascending: false })
        .range(page * size, page * size + size - 1),
    ) as AuditRow[];
  }, [page]);

  async function check() {
    setVerify("Comprobando…");
    const { data, error } = await supabase.rpc("audit_verify_chain");
    if (error) return setVerify(translateError(error.message));
    const r = (data as { ok: boolean; rows_checked: number; first_broken_id: number | null }[])[0];
    setVerify(
      r.ok
        ? `✅ Historial íntegro: ${r.rows_checked} registros verificados, ninguno alterado.`
        : `⚠️ Se ha detectado una alteración a partir del registro #${r.first_broken_id}.`,
    );
  }

  return (
    <>
      <PageHead title="Historial de acciones" subtitle="Registro inalterable de todo lo que hacen personas y agentes.">
        <button className="btn" onClick={() => void check()}>
          Verificar integridad
        </button>
      </PageHead>
      {verify && <div className="notice" style={{ marginBottom: 12 }}>{verify}</div>}
      <ErrorBox error={state.error} />
      <div className="card">
        {state.loading && !state.data ? (
          <Loading lines={6} />
        ) : state.data && state.data.length === 0 ? (
          <Empty>Sin registros.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Cuándo</th>
                  <th>Quién</th>
                  <th>Qué</th>
                  <th>Detalles</th>
                </tr>
              </thead>
              <tbody>
                {state.data?.map((r) => {
                  const [label, tone] = ACTOR[r.actor_type] ?? [r.actor_type, "gray"];
                  return (
                    <tr key={r.id}>
                      <td style={{ whiteSpace: "nowrap" }}>{fmtDateTime(r.at)}</td>
                      <td>
                        <Badge tone={tone}>{label}</Badge>{" "}
                        <span className="muted">{r.actor_type === "human" ? "" : AGENT_NAMES[r.actor_id] ?? r.actor_id}</span>
                      </td>
                      <td>{describeAudit(r.action)}</td>
                      <td>
                        <details>
                          <summary className="muted">Ver</summary>
                          <pre className="payload">{JSON.stringify(r.details, null, 2)}</pre>
                        </details>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn small" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            ← Más recientes
          </button>
          <span className="spacer" />
          <button className="btn small" disabled={(state.data?.length ?? 0) < size} onClick={() => setPage((p) => p + 1)}>
            Más antiguos →
          </button>
        </div>
      </div>
    </>
  );
}
