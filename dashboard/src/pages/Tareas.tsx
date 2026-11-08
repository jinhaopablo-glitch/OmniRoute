import { useState, type FormEvent } from "react";
import { Empty, ErrorBox, Loading, PageHead } from "../components/ui";
import { useAuth } from "../lib/auth";
import { AGENT_NAMES, fmtDate, TASK_STATUS } from "../lib/format";
import { supabase } from "../lib/supabase";
import type { Task } from "../lib/types";
import { translateError, unwrap, useData } from "../lib/useData";

const PRIORITY: Record<number, string> = { 1: "Urgente", 2: "Alta", 3: "Normal", 4: "Baja" };

export function Tareas() {
  const { isOwner } = useAuth();
  const [show, setShow] = useState<"open" | "done">("open");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState(3);
  const [due, setDue] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const state = useData(async () => {
    const statuses = show === "open" ? ["todo", "in_progress", "blocked"] : ["done", "cancelled"];
    return unwrap(
      await supabase
        .from("tasks")
        .select("*")
        .in("status", statuses)
        .order("priority")
        .order("created_at", { ascending: false })
        .limit(100),
    ) as Task[];
  }, [show]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    const { error } = await supabase.from("tasks").insert({ title, description, priority, due_date: due || null });
    if (error) setErr(translateError(error.message));
    else {
      setTitle("");
      setDescription("");
      setDue("");
      state.reload();
    }
  }

  async function setStatus(t: Task, status: string) {
    const { error } = await supabase.from("tasks").update({ status, updated_at: new Date().toISOString() }).eq("id", t.id);
    if (error) setErr(translateError(error.message));
    state.reload();
  }

  return (
    <>
      <PageHead title="Tareas pendientes" subtitle="Lo que tienes que hacer tú y lo que proponen los agentes.">
        <button className={`btn small ${show === "open" ? "primary" : ""}`} onClick={() => setShow("open")}>
          Abiertas
        </button>
        <button className={`btn small ${show === "done" ? "primary" : ""}`} onClick={() => setShow("done")}>
          Terminadas
        </button>
      </PageHead>
      <div className={isOwner ? "grid k2" : ""} style={isOwner ? { gridTemplateColumns: "2fr 1fr" } : undefined}>
        <div className="card">
          <ErrorBox error={state.error ?? err} />
          {state.loading && !state.data ? (
            <Loading />
          ) : state.data && state.data.length === 0 ? (
            <Empty>{show === "open" ? "¡Nada pendiente!" : "Sin tareas terminadas."}</Empty>
          ) : (
            state.data?.map((t) => (
              <div key={t.id} className="list-item">
                <div className="row">
                  <span className={`badge ${t.priority === 1 ? "bad" : t.priority === 2 ? "terra" : "gray"}`}>{PRIORITY[t.priority]}</span>
                  <strong>{t.title}</strong>
                  <span className="spacer" />
                  {isOwner ? (
                    <select
                      value={t.status}
                      onChange={(e) => void setStatus(t, e.target.value)}
                      aria-label="Estado"
                      style={{ width: "auto", minHeight: 32, padding: "4px 8px" }}
                    >
                      {Object.entries(TASK_STATUS).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="badge gray">{TASK_STATUS[t.status]}</span>
                  )}
                </div>
                {t.description && t.description !== t.title && <p className="muted" style={{ marginTop: 4 }}>{t.description}</p>}
                <div className="muted" style={{ marginTop: 4 }}>
                  {t.created_by_type === "agent" ? `Propuesta por ${AGENT_NAMES[t.created_by] ?? t.created_by}` : "Creada por ti"}
                  {t.due_date && ` · Para el ${fmtDate(t.due_date)}`}
                </div>
              </div>
            ))
          )}
        </div>
        {isOwner && (
          <form className="card stack" onSubmit={add}>
            <h2>Nueva tarea</h2>
            <div className="field">
              <label htmlFor="ttitle">Título</label>
              <input id="ttitle" required minLength={3} maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="tdesc">Descripción</label>
              <textarea id="tdesc" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="tprio">Prioridad</label>
              <select id="tprio" value={priority} onChange={(e) => setPriority(Number(e.target.value))}>
                {Object.entries(PRIORITY).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="tdue">Fecha límite</label>
              <input id="tdue" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            </div>
            <button className="btn primary" type="submit">
              Añadir tarea
            </button>
          </form>
        )}
      </div>
    </>
  );
}
