import { useState, type FormEvent } from "react";
import { Empty, ErrorBox, Loading, PageHead } from "../components/ui";
import { useAuth } from "../lib/auth";
import { fmtDate, fmtEur } from "../lib/format";
import { supabase } from "../lib/supabase";
import { translateError, unwrap, useData } from "../lib/useData";

interface Product {
  id: string;
  name: string;
  category: string;
  pet: string;
  supplier: string;
  supplier_url: string | null;
  unit_cost_eur: string | null;
  suggested_price_eur: string | null;
  competitor_price_eur: string | null;
  estimated_margin_pct: string | null;
  score: number | null;
  rationale: string;
  sources: string[];
  status: string;
  created_at: string;
}

interface Snapshot {
  id: string;
  summary: string;
  data: { promotions?: string[]; prices?: string[] };
  taken_on: string;
  competitors: { name: string; website: string | null } | null;
}

export function Investigacion() {
  const { isOwner } = useAuth();
  const [filter, setFilter] = useState("new");
  const [name, setName] = useState("");
  const [site, setSite] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const state = useData(async () => {
    let q = supabase.from("research_products").select("*").order("score", { ascending: false }).limit(60);
    if (filter !== "all") q = q.eq("status", filter);
    const [products, snaps] = await Promise.all([
      q,
      supabase
        .from("competitor_snapshots")
        .select("id, summary, data, taken_on, competitors(name, website)")
        .order("created_at", { ascending: false })
        .limit(12),
    ]);
    return { products: unwrap(products) as Product[], snaps: unwrap(snaps) as unknown as Snapshot[] };
  }, [filter]);

  async function setStatus(p: Product, status: string) {
    await supabase.from("research_products").update({ status }).eq("id", p.id);
    state.reload();
  }

  async function addCompetitor(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    const { error } = await supabase.from("competitors").insert({ name, website: site || null });
    if (error) setErr(translateError(error.message));
    else {
      setName("");
      setSite("");
    }
  }

  const d = state.data;
  return (
    <>
      <PageHead title="Investigación de productos" subtitle="Ideas de producto, proveedores, márgenes y competencia.">
        <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filtrar" style={{ width: "auto" }}>
          <option value="new">Nuevos</option>
          <option value="shortlisted">Preseleccionados</option>
          <option value="discarded">Descartados</option>
          <option value="all">Todos</option>
        </select>
      </PageHead>
      <ErrorBox error={state.error} />
      {state.loading && !d ? (
        <Loading />
      ) : (
        <>
          <div className="card">
            {d && d.products.length === 0 ? (
              <Empty>No hay productos en esta vista.</Empty>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Producto</th>
                      <th>Puntuación</th>
                      <th>Coste</th>
                      <th>PVP sugerido</th>
                      <th>Competencia</th>
                      <th>Margen est.</th>
                      {isOwner && <th />}
                    </tr>
                  </thead>
                  <tbody>
                    {d?.products.map((p) => (
                      <tr key={p.id}>
                        <td style={{ minWidth: 220 }}>
                          <strong>{p.name}</strong>
                          <div className="muted">
                            {p.pet} · {p.category} · {p.supplier_url ? (
                              <a href={p.supplier_url} target="_blank" rel="noreferrer noopener">
                                {p.supplier || "proveedor"}
                              </a>
                            ) : (
                              p.supplier
                            )}
                          </div>
                          <div className="muted">{p.rationale}</div>
                        </td>
                        <td>{p.score ?? "—"}</td>
                        <td>{fmtEur(p.unit_cost_eur)}</td>
                        <td>{fmtEur(p.suggested_price_eur)}</td>
                        <td>{fmtEur(p.competitor_price_eur)}</td>
                        <td>{p.estimated_margin_pct ? `${Number(p.estimated_margin_pct).toFixed(0)} %` : "—"}</td>
                        {isOwner && (
                          <td>
                            <div className="row">
                              {p.status !== "shortlisted" && (
                                <button className="btn small" onClick={() => void setStatus(p, "shortlisted")}>
                                  Preseleccionar
                                </button>
                              )}
                              {p.status !== "discarded" && (
                                <button className="btn small danger" onClick={() => void setStatus(p, "discarded")}>
                                  Descartar
                                </button>
                              )}
                            </div>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="muted" style={{ marginTop: 10 }}>
              Margen estimado sobre el precio sin IVA. Las cifras son estimaciones de fuentes públicas: compruébalas antes de decidir.
            </p>
          </div>

          <div className="grid k2 section">
            <div className="card">
              <h2 style={{ marginBottom: 10 }}>Competencia</h2>
              {d && d.snaps.length === 0 ? (
                <Empty>Sin análisis de competencia todavía.</Empty>
              ) : (
                d?.snaps.map((s) => (
                  <div key={s.id} className="list-item">
                    <div className="row">
                      <strong>{s.competitors?.name}</strong>
                      <span className="spacer" />
                      <span className="muted">{fmtDate(s.taken_on)}</span>
                    </div>
                    <p style={{ marginTop: 4 }}>{s.summary}</p>
                    {s.data.promotions && s.data.promotions.length > 0 && (
                      <p className="muted">Promociones: {s.data.promotions.join(" · ")}</p>
                    )}
                  </div>
                ))
              )}
            </div>
            {isOwner && (
              <form className="card stack" onSubmit={addCompetitor}>
                <h2>Añadir competidor de referencia</h2>
                <p className="muted">El Agente de Investigación lo vigilará a partir del próximo análisis.</p>
                <div className="field">
                  <label htmlFor="cname">Nombre</label>
                  <input id="cname" required minLength={2} value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="csite">Web</label>
                  <input id="csite" type="url" placeholder="https://" value={site} onChange={(e) => setSite(e.target.value)} />
                </div>
                <ErrorBox error={err} />
                <button className="btn primary" type="submit">
                  Añadir
                </button>
              </form>
            )}
          </div>
        </>
      )}
    </>
  );
}
