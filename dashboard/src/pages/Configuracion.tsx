import { useState } from "react";
import { ErrorBox, Loading, Modal, PageHead } from "../components/ui";
import { useAuth } from "../lib/auth";
import { supabase } from "../lib/supabase";
import type { Agent } from "../lib/types";
import { translateError, unwrap, useData } from "../lib/useData";

const MODELS = [
  { id: "claude-opus-5-5", label: "Claude Opus 5.5 (mejor calidad)" },
  { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5 (equilibrado)" },
  { id: "claude-haiku-5-5", label: "Claude Haiku 5.5 (más barato)" },
];
const EFFORTS = [
  { id: "low", label: "Bajo" },
  { id: "medium", label: "Medio" },
  { id: "high", label: "Alto" },
];

interface Budget {
  id: number;
  scope: string;
  period: string;
  limit_usd: string;
}

export function Configuracion() {
  const { isOwner, session } = useAuth();
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirmKill, setConfirmKill] = useState(false);
  const state = useData(async () => {
    const [agents, budgets, settings] = await Promise.all([
      supabase.from("agents").select("*").order("id"),
      supabase.from("budget_limits").select("*").order("scope"),
      supabase.from("settings").select("key, value"),
    ]);
    const s = Object.fromEntries((unwrap(settings) as { key: string; value: unknown }[]).map((r) => [r.key, r.value]));
    return { agents: unwrap(agents) as Agent[], budgets: unwrap(budgets) as Budget[], settings: s };
  }, [], 0);

  async function run(p: PromiseLike<{ error: { message: string } | null }>, ok: string) {
    setErr(null);
    const { error } = await p;
    if (error) setErr(translateError(error.message));
    else {
      setMsg(ok);
      state.reload();
    }
  }

  const updateAgent = (a: Agent, patch: Partial<Agent>) =>
    run(supabase.from("agents").update({ ...patch, updated_at: new Date().toISOString() }).eq("id", a.id), "Agente actualizado.");

  const saveBudget = (scope: string, period: string, value: string, existing?: Budget) => {
    const limit = Number(value.replace(",", "."));
    if (!Number.isFinite(limit) || limit < 0) return setErr("Introduce un importe válido.");
    return run(
      existing
        ? supabase.from("budget_limits").update({ limit_usd: limit, updated_at: new Date().toISOString() }).eq("id", existing.id)
        : supabase.from("budget_limits").insert({ scope, period, limit_usd: limit }),
      "Límite guardado.",
    );
  };

  const setKill = (on: boolean) =>
    run(
      supabase
        .from("settings")
        .update({ value: on, updated_at: new Date().toISOString(), updated_by: session?.user.id })
        .eq("key", "kill_switch"),
      on ? "Sistema detenido. Ningún agente trabajará ni gastará hasta que lo reactives." : "Sistema reactivado.",
    );

  const d = state.data;
  const killed = d?.settings.kill_switch === true;
  const budget = (scope: string, period: string) => d?.budgets.find((b) => b.scope === scope && b.period === period);

  return (
    <>
      <PageHead title="Configuración" subtitle="Agentes, modelos, límites de gasto y parada de emergencia." />
      {msg && <div className="notice" style={{ marginBottom: 12 }}>{msg}</div>}
      <ErrorBox error={state.error ?? err} />
      {!isOwner && <div className="notice">Tienes acceso de solo lectura.</div>}
      {state.loading && !d ? (
        <Loading lines={6} />
      ) : d ? (
        <>
          <div className="card" style={{ borderColor: killed ? "var(--bad)" : undefined }}>
            <div className="row">
              <div>
                <h2>Parada de emergencia</h2>
                <p className="muted">Detiene al instante todos los agentes y cualquier gasto de IA.</p>
              </div>
              <span className="spacer" />
              {killed ? (
                <button className="btn primary" disabled={!isOwner} onClick={() => void setKill(false)}>
                  Reactivar sistema
                </button>
              ) : (
                <button className="btn danger" disabled={!isOwner} onClick={() => setConfirmKill(true)}>
                  Detener todo
                </button>
              )}
            </div>
          </div>

          <div className="card section">
            <h2 style={{ marginBottom: 10 }}>Límites de gasto de IA (USD)</h2>
            <div className="grid k2">
              {(["daily", "monthly"] as const).map((period) => (
                <BudgetField
                  key={period}
                  label={period === "daily" ? "Límite diario global" : "Límite mensual global"}
                  initial={budget("global", period)?.limit_usd ?? ""}
                  disabled={!isOwner}
                  onSave={(v) => void saveBudget("global", period, v, budget("global", period))}
                />
              ))}
            </div>
            <p className="muted" style={{ marginTop: 10 }}>
              Al llegar al límite los agentes se pausan solos y lo verás en Actividad.
            </p>
          </div>

          <div className="card section">
            <h2 style={{ marginBottom: 10 }}>Agentes</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Agente</th>
                    <th>Modelo</th>
                    <th>Esfuerzo</th>
                    <th>Límite diario (USD)</th>
                    <th>Activo</th>
                  </tr>
                </thead>
                <tbody>
                  {d.agents.map((a) => (
                    <tr key={a.id}>
                      <td>
                        <strong>{a.name}</strong>
                      </td>
                      <td>
                        <select
                          value={a.model}
                          disabled={!isOwner}
                          onChange={(e) => void updateAgent(a, { model: e.target.value })}
                          aria-label={`Modelo de ${a.name}`}
                        >
                          {MODELS.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <select
                          value={a.effort}
                          disabled={!isOwner}
                          onChange={(e) => void updateAgent(a, { effort: e.target.value })}
                          aria-label={`Esfuerzo de ${a.name}`}
                        >
                          {EFFORTS.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td style={{ minWidth: 150 }}>
                        <BudgetField
                          compact
                          initial={budget(a.id, "daily")?.limit_usd ?? ""}
                          disabled={!isOwner}
                          onSave={(v) => void saveBudget(a.id, "daily", v, budget(a.id, "daily"))}
                        />
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          style={{ width: 22, minHeight: 22 }}
                          checked={a.enabled}
                          disabled={!isOwner}
                          onChange={(e) => void updateAgent(a, { enabled: e.target.checked })}
                          aria-label={`Activar ${a.name}`}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card section">
            <h2 style={{ marginBottom: 8 }}>Seguridad</h2>
            <ul className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
              <li>Los agentes solo pueden proponer; publicar, cambiar precios o gastar requiere tu aprobación.</li>
              <li>El supervisor revisa cada propuesta, pero no puede aprobar.</li>
              <li>Las claves de API están en el servidor, nunca en este panel.</li>
              <li>Activa la verificación en dos pasos en tu cuenta de Supabase.</li>
            </ul>
          </div>
        </>
      ) : null}
      {confirmKill && (
        <Modal title="¿Detener todos los agentes?" onClose={() => setConfirmKill(false)}>
          <p>Ningún agente trabajará ni gastará hasta que pulses "Reactivar sistema".</p>
          <div className="row" style={{ marginTop: 16 }}>
            <span className="spacer" />
            <button className="btn" onClick={() => setConfirmKill(false)}>
              Cancelar
            </button>
            <button
              className="btn danger"
              onClick={() => {
                setConfirmKill(false);
                void setKill(true);
              }}
            >
              Sí, detener
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

function BudgetField({
  label,
  initial,
  onSave,
  disabled,
  compact,
}: {
  label?: string;
  initial: string;
  onSave: (v: string) => void;
  disabled?: boolean;
  compact?: boolean;
}) {
  const [v, setV] = useState(initial);
  return (
    <div className="field">
      {label && <label>{label}</label>}
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <input
          inputMode="decimal"
          value={v}
          placeholder={compact ? "Sin límite" : ""}
          disabled={disabled}
          onChange={(e) => setV(e.target.value)}
          aria-label={label ?? "Límite diario"}
        />
        <button className="btn small" disabled={disabled || v === initial || v === ""} onClick={() => onSave(v)}>
          Guardar
        </button>
      </div>
    </div>
  );
}
