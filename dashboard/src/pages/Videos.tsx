import { useEffect, useState } from "react";
import { Empty, ErrorBox, Loading, PageHead, StatusBadge } from "../components/ui";
import { CONTENT_STATUS, fmtDate } from "../lib/format";
import { signedMediaUrl, supabase } from "../lib/supabase";
import type { ContentItem } from "../lib/types";
import { unwrap, useData } from "../lib/useData";

export function Videos() {
  const state = useData(async () => {
    return unwrap(
      await supabase
        .from("content_items")
        .select("*")
        .eq("kind", "video")
        .neq("status", "discarded")
        .order("created_at", { ascending: false })
        .limit(24),
    ) as ContentItem[];
  });

  return (
    <>
      <PageHead title="Vídeos generados" subtitle="Borradores verticales listos para revisar." />
      <ErrorBox error={state.error} />
      {state.loading && !state.data ? (
        <Loading />
      ) : state.data && state.data.length === 0 ? (
        <div className="card">
          <Empty>Todavía no hay vídeos. El Agente Creativo los genera a partir de los guiones aprobados por el supervisor.</Empty>
        </div>
      ) : (
        <div className="grid k3">
          {state.data?.map((v) => (
            <VideoCard key={v.id} v={v} />
          ))}
        </div>
      )}
    </>
  );
}

function VideoCard({ v }: { v: ContentItem }) {
  const [url, setUrl] = useState<string | null>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (visible && v.media_paths[0]) void signedMediaUrl(v.media_paths[0]).then(setUrl);
  }, [visible, v.media_paths]);
  const body = v.body as { caption?: string; duration_s?: number };
  return (
    <div className="card video-card stack">
      {url ? (
        <video src={url} controls playsInline preload="metadata" />
      ) : (
        <button className="btn" style={{ aspectRatio: "9 / 16", width: "100%" }} onClick={() => setVisible(true)}>
          ▶ Cargar vídeo
        </button>
      )}
      <div className="row">
        <strong>{v.title}</strong>
        <span className="spacer" />
        <StatusBadge map={CONTENT_STATUS} value={v.status} />
      </div>
      <div className="muted">
        {fmtDate(v.created_at)} · {body.duration_s ? `${Math.round(body.duration_s)} s` : ""} ·{" "}
        {v.platform === "both" ? "Instagram y TikTok" : v.platform}
      </div>
      {body.caption && <p style={{ whiteSpace: "pre-wrap", fontSize: "0.9rem" }}>{body.caption}</p>}
      {v.published_url && (
        <a href={v.published_url} target="_blank" rel="noreferrer noopener">
          Ver publicación
        </a>
      )}
    </div>
  );
}
