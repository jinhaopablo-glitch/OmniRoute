import { useState } from "react";
import { Empty, ErrorBox, Loading, PageHead, StatusBadge } from "../components/ui";
import { CONTENT_KIND, CONTENT_STATUS, madridDay, timeAgo } from "../lib/format";
import { supabase } from "../lib/supabase";
import type { ContentItem } from "../lib/types";
import { unwrap, useData } from "../lib/useData";
import { useAuth } from "../lib/auth";

export function Calendario() {
  const { isOwner } = useAuth();
  const [start] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); // lunes de esta semana
    return d;
  });
  const days = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return madridDay(d);
  });
  const state = useData(async () => {
    const [planned, board] = await Promise.all([
      supabase
        .from("content_items")
        .select("*")
        .in("kind", ["video", "post"])
        .or(`scheduled_for.gte.${days[0]},status.eq.published`)
        .order("created_at", { ascending: false })
        .limit(200),
      supabase
        .from("content_items")
        .select("*")
        .in("kind", ["idea", "script", "video"])
        .in("status", ["draft", "in_review", "ready", "flagged"])
        .order("created_at", { ascending: false })
        .limit(60),
    ]);
    return { planned: unwrap(planned) as ContentItem[], board: unwrap(board) as ContentItem[] };
  });

  async function schedule(item: ContentItem, day: string) {
    await supabase
      .from("content_items")
      .update({ scheduled_for: day ? `${day}T10:00:00+01:00` : null, updated_at: new Date().toISOString() })
      .eq("id", item.id);
    state.reload();
  }

  async function discard(item: ContentItem) {
    await supabase.from("content_items").update({ status: "discarded" }).eq("id", item.id);
    state.reload();
  }

  const today = madridDay(new Date());
  const d = state.data;
  const byDay = (day: string) =>
    (d?.planned ?? []).filter((c) => {
      const when = c.scheduled_for ?? (c.status === "published" ? c.created_at : null);
      return when && madridDay(new Date(when)) === day;
    });

  return (
    <>
      <PageHead
        title="Calendario de publicaciones"
        subtitle="Planifica fechas. Publicar siempre requiere tu aprobación en la bandeja."
      />
      <ErrorBox error={state.error} />
      {state.loading && !d ? (
        <Loading />
      ) : (
        <>
          <div className="cal">
            {days.map((day) => {
              const items = byDay(day);
              const label = new Date(`${day}T12:00:00`).toLocaleDateString("es-ES", {
                weekday: "short",
                day: "numeric",
                month: "short",
              });
              return (
                <div key={day} className={`cal-day ${day === today ? "today" : ""} ${items.length ? "" : "empty-day"}`}>
                  <div className="d">{label}</div>
                  {items.map((c) => (
                    <div key={c.id} className={`cal-item ${c.status === "published" ? "published" : ""}`} title={c.title}>
                      {c.platform === "tiktok" ? "🎵" : "📸"} {c.title}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>

          <div className="card section">
            <h2 style={{ marginBottom: 10 }}>Contenido en preparación</h2>
            {d && d.board.length === 0 ? (
              <Empty>Los agentes irán dejando aquí ideas, guiones y vídeos.</Empty>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Tipo</th>
                      <th>Título</th>
                      <th>Estado</th>
                      <th>Creado</th>
                      {isOwner && <th>Fecha prevista</th>}
                      {isOwner && <th />}
                    </tr>
                  </thead>
                  <tbody>
                    {d?.board.map((c) => (
                      <tr key={c.id}>
                        <td>{CONTENT_KIND[c.kind] ?? c.kind}</td>
                        <td>
                          <strong>{c.title}</strong>
                          {c.review_notes && <div className="muted">{c.review_notes}</div>}
                        </td>
                        <td>
                          <StatusBadge map={CONTENT_STATUS} value={c.status} />
                        </td>
                        <td className="muted">{timeAgo(c.created_at)}</td>
                        {isOwner && (
                          <td>
                            {c.kind === "video" ? (
                              <input
                                type="date"
                                aria-label="Fecha prevista"
                                defaultValue={c.scheduled_for ? madridDay(new Date(c.scheduled_for)) : ""}
                                onChange={(e) => void schedule(c, e.target.value)}
                              />
                            ) : (
                              <span className="muted">—</span>
                            )}
                          </td>
                        )}
                        {isOwner && (
                          <td>
                            <button className="btn small danger" onClick={() => void discard(c)}>
                              Descartar
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
