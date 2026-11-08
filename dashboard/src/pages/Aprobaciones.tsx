import { useEffect, useState } from "react";
import { Badge, Empty, ErrorBox, Loading, Modal, PageHead, StatusBadge } from "../components/ui";
import { useAuth } from "../lib/auth";
import { ACTION_LABELS, AGENT_NAMES, fmtDateTime, fmtEur, PROPOSAL_STATUS, RISK, timeAgo } from "../lib/format";
import { signedMediaUrl, supabase } from "../lib/supabase";
import type { Proposal } from "../lib/types";
import { translateError, unwrap, useData } from "../lib/useData";

type Tab = "pending" | "review" | "history";

export function Aprobaciones() {
  const [tab, setTab] = useState<Tab>("pending");
  const state = useData(async () => {
    let q = supabase.from("proposals").select("*").order("created_at", { ascending: false }).limit(50);
    if (tab === "pending") q = q.eq("status", "pending_approval");
    else if (tab === "review") q = q.eq("status", "pending_review");
    else q = q.not("status", "in", "(pending_approval,pending_review)");
    return unwrap(await q) as Proposal[];
  }, [tab], 30_000);

  return (
    <>
      <PageHead
        title="Bandeja de aprobaciones"
        subtitle="Nada sensible se publica, se cambia ni se gasta sin tu decisión."
      >
        {(["pending", "review", "history"] as Tab[]).map((t) => (
          <button key={t} className={`btn small ${tab === t ? "primary" : ""}`} onClick={() => setTab(t)}>
            {t === "pending" ? "Pendientes" : t === "review" ? "En revisión" : "Historial"}
          </button>
        ))}
      </PageHead>
      <ErrorBox error={state.error} />
      {state.loading && !state.data ? (
        <Loading />
      ) : state.data && state.data.length === 0 ? (
        <div className="card">
          <Empty>
            {tab === "pending"
              ? "No hay nada pendiente. Los agentes te avisarán aquí cuando necesiten tu aprobación."
              : "No hay propuestas en esta vista."}
          </Empty>
        </div>
      ) : (
        <div className="stack">
          {state.data?.map((p) => (
            <ProposalCard key={p.id} p={p} onDone={state.reload} />
          ))}
        </div>
      )}
    </>
  );
}

function ProposalCard({ p, onDone }: { p: Proposal; onDone: () => void }) {
  const { isOwner } = useAuth();
  const [confirm, setConfirm] = useState<"approve" | "reject" | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [risk, riskTone] = RISK[p.risk_level] ?? [p.risk_level, "gray"];
  const actionable = isOwner && (p.status === "pending_approval" || p.status === "pending_review");

  async function decide(kind: "approve" | "reject") {
    setBusy(true);
    setError(null);
    const res =
      kind === "approve"
        ? await supabase.rpc("approve_proposal", {
            p_proposal_id: p.id,
            p_expected_hash: p.payload_hash,
            p_note: note || null,
          })
        : await supabase.rpc("reject_proposal", { p_proposal_id: p.id, p_note: note || null });
    setBusy(false);
    if (res.error) {
      setError(translateError(res.error.message));
      return;
    }
    setConfirm(null);
    onDone();
  }

  return (
    <article className="card">
      <div className="row" style={{ marginBottom: 8 }}>
        <Badge tone="terra">{ACTION_LABELS[p.action_type] ?? p.action_type}</Badge>
        <Badge tone={riskTone}>{risk}</Badge>
        <StatusBadge map={PROPOSAL_STATUS} value={p.status} />
        <span className="spacer" />
        <span className="muted">
          {AGENT_NAMES[p.proposed_by_agent] ?? p.proposed_by_agent} · {timeAgo(p.created_at)}
        </span>
      </div>
      <h2>{p.title}</h2>
      {p.summary && <p style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>{p.summary}</p>}
      <PayloadView p={p} />
      {p.supervisor_notes && (
        <p className="muted" style={{ marginTop: 10 }}>
          <strong>Supervisor:</strong> {p.supervisor_notes}
        </p>
      )}
      {p.decision_note && (
        <p className="muted" style={{ marginTop: 6 }}>
          <strong>Tu nota:</strong> {p.decision_note}
        </p>
      )}
      {p.execution_result && (
        <details style={{ marginTop: 10 }}>
          <summary className="muted">Resultado de la ejecución</summary>
          <pre className="payload">{JSON.stringify(p.execution_result, null, 2)}</pre>
        </details>
      )}
      <div className="row" style={{ marginTop: 14 }}>
        <span className="muted">Caduca: {fmtDateTime(p.expires_at)}</span>
        <span className="spacer" />
        {actionable && (
          <div className="actions">
            <button className="btn danger" onClick={() => setConfirm("reject")}>
              Rechazar
            </button>
            {p.status === "pending_approval" && (
              <button className="btn primary" onClick={() => setConfirm("approve")}>
                Aprobar
              </button>
            )}
          </div>
        )}
      </div>
      {confirm && (
        <Modal title={confirm === "approve" ? "¿Aprobar esta acción?" : "¿Rechazar esta propuesta?"} onClose={() => setConfirm(null)}>
          <div className="stack">
            <p>
              <strong>{p.title}</strong>
            </p>
            {confirm === "approve" && (
              <p className="notice">
                Al aprobar, el sistema ejecutará exactamente lo que ves aquí
                {Number(p.estimated_cost_eur) > 0 && <> (coste estimado: {fmtEur(p.estimated_cost_eur)})</>}. Si el contenido
                cambiara, la aprobación dejaría de valer.
              </p>
            )}
            <div className="field">
              <label htmlFor={`note-${p.id}`}>Nota (opcional)</label>
              <textarea id={`note-${p.id}`} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <ErrorBox error={error} />
            <div className="row">
              <span className="spacer" />
              <button className="btn" onClick={() => setConfirm(null)} disabled={busy}>
                Cancelar
              </button>
              <button
                className={`btn ${confirm === "approve" ? "primary" : "danger"}`}
                onClick={() => void decide(confirm)}
                disabled={busy}
              >
                {busy ? "Guardando…" : confirm === "approve" ? "Sí, aprobar" : "Sí, rechazar"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </article>
  );
}

function PayloadView({ p }: { p: Proposal }) {
  const pl = p.payload as Record<string, unknown>;
  const [video, setVideo] = useState<string | null>(null);
  const media = Array.isArray(pl.media_paths) ? (pl.media_paths as string[]) : [];
  useEffect(() => {
    if (p.action_type === "publish_content" && media[0]) void signedMediaUrl(media[0]).then(setVideo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.id]);

  if (p.action_type === "change_price") {
    return (
      <div className="row" style={{ marginTop: 12, gap: 16 }}>
        <div className="stat">
          <div className="label">Precio actual</div>
          <div className="value" style={{ fontSize: "1.3rem" }}>{fmtEur(pl.current_price as string)}</div>
        </div>
        <div aria-hidden="true">→</div>
        <div className="stat">
          <div className="label">Precio nuevo</div>
          <div className="value" style={{ fontSize: "1.3rem", color: "var(--terra-text)" }}>{fmtEur(pl.new_price as string)}</div>
        </div>
      </div>
    );
  }
  if (p.action_type === "publish_content") {
    return (
      <div className="grid k2" style={{ marginTop: 12 }}>
        <div className="video-card">
          {video ? <video src={video} controls playsInline preload="metadata" /> : <div className="muted">Cargando vídeo…</div>}
        </div>
        <div className="stack">
          <div>
            <div className="muted">Red social</div>
            <strong style={{ textTransform: "capitalize" }}>{String(pl.platform)}</strong>
          </div>
          <div>
            <div className="muted">Pie de foto</div>
            <p style={{ whiteSpace: "pre-wrap" }}>{String(pl.caption ?? "")}</p>
          </div>
        </div>
      </div>
    );
  }
  if (p.action_type === "modify_product") {
    const changes = (pl.changes ?? {}) as Record<string, string>;
    return (
      <div className="stack" style={{ marginTop: 12 }}>
        {Object.entries(changes).map(([k, v]) => (
          <div key={k}>
            <div className="muted">{FIELD_LABELS[k] ?? k}</div>
            {k === "description_html" ? <pre className="payload">{v}</pre> : <strong>{String(v)}</strong>}
          </div>
        ))}
      </div>
    );
  }
  return (
    <details style={{ marginTop: 10 }} open>
      <summary className="muted">Detalles</summary>
      <pre className="payload">{JSON.stringify(pl, null, 2)}</pre>
    </details>
  );
}

const FIELD_LABELS: Record<string, string> = {
  title: "Título nuevo",
  description_html: "Descripción nueva (HTML)",
  seo_title: "Título SEO",
  seo_description: "Descripción SEO",
  tags: "Etiquetas",
};
