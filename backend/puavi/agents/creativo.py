"""Agente Creativo: guiones, subtítulos, voz en off y borradores de vídeo."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from puavi.agents.base import AgentContext, job, system_prompt
from puavi.agents.schemas import ScriptsOutput
from puavi.core.proposals import ActionType, submit_proposal
from puavi.integrations.http import new_client
from puavi.media.video import Scene, render_vertical_video

log = logging.getLogger("puavi.agents.creativo")

ROLE = """Agente Creativo. Conviertes ideas en guiones de vídeo vertical (15-45 segundos) para
Reels y TikTok: gancho en los 2 primeros segundos, escenas cortas, voz en off natural y cercana,
texto en pantalla breve (máx. 8 palabras por escena), pie de foto con llamada a la acción suave y
3-6 hashtags. Tono PUAVI: divertido, cercano y profesional."""

IMAGE_HOSTS = {"cdn.shopify.com"}  # solo se descargan imágenes de la CDN oficial de Shopify
MAX_IMAGE_BYTES = 8 * 1024 * 1024


@job("creativo", "content.scripts")
def content_scripts(ctx: AgentContext) -> dict[str, Any]:
    ideas = ctx.conn.execute(
        "select i.id, i.title, i.platform, i.body from public.content_items i"
        " where i.kind = 'idea' and i.status = 'draft'"
        " and not exists (select 1 from public.content_items s where s.parent_id = i.id)"
        " order by i.created_at desc limit 3"
    ).fetchall()
    if not ideas:
        return {"scripts": 0, "reason": "sin ideas nuevas"}
    products = []
    if ctx.services.shopify:
        products = [
            {"handle": p["handle"], "title": p["title"]}
            for p in ctx.services.shopify.list_products(limit=25, query="status:active")
        ]
    model, effort = ctx.agent_config("creativo")
    prompt = (
        "Escribe un guion por cada idea. Usa el campo idea_id exacto. Si encaja un producto del "
        "catálogo, indica su handle en product_handle (solo de esta lista):\n"
        f"Catálogo: {json.dumps(products, ensure_ascii=False)}\n"
        f"Ideas: {json.dumps(ideas, ensure_ascii=False, default=str)}"
    )
    result = ctx.llm.run(
        ctx.conn,
        agent_id="creativo",
        model=model,
        effort=effort,
        system=system_prompt(ROLE),
        prompt=prompt,
        output_model=ScriptsOutput,
        job_id=ctx.job_id,
        summary=f"Guiones para {len(ideas)} ideas",
    )
    valid_ids = {str(i["id"]) for i in ideas}
    handles = {p["handle"] for p in products}
    saved = 0
    for s in result.output.scripts:
        if s.idea_id not in valid_ids:
            continue
        body = s.model_dump()
        if body["product_handle"] not in handles:
            body["product_handle"] = ""
        ctx.conn.execute(
            "select public.agent_save_content('creativo', 'script', %s, %s, %s, %s, '{}', null, %s,"
            " 'in_review')",
            (
                s.platform,
                s.title[:200],
                json.dumps(body, ensure_ascii=False),
                s.idea_id,
                ctx.job_id,
            ),
        )
        ctx.conn.execute(
            "select public.agent_update_content('creativo', %s, 'ready', null, 'Guion creado')",
            (s.idea_id,),
        )
        saved += 1
    return {"scripts": saved}


def _download_images(ctx: AgentContext, handle: str, dest: Path) -> list[Path]:
    if not (handle and ctx.services.shopify):
        return []
    products = ctx.services.shopify.list_products(limit=1, query=f"handle:{handle}")
    if not products:
        return []
    urls = [
        m["preview"]["image"]["url"]
        for m in products[0]["media"]["nodes"]
        if m.get("preview") and m["preview"].get("image")
    ]
    paths: list[Path] = []
    with new_client(timeout=30) as http:
        for i, url in enumerate(urls[:5]):
            if urlparse(url).hostname not in IMAGE_HOSTS:
                continue
            resp = http.get(url)
            if resp.status_code != 200 or len(resp.content) > MAX_IMAGE_BYTES:
                continue
            if not resp.headers.get("content-type", "").startswith("image/"):
                continue
            p = dest / f"img{i}.jpg"
            p.write_bytes(resp.content)
            paths.append(p)
    return paths


@job("creativo", "video.render")
def video_render(ctx: AgentContext) -> dict[str, Any]:
    if ctx.services.storage is None:
        raise RuntimeError("Almacenamiento no configurado: no se pueden guardar vídeos")
    scripts = ctx.conn.execute(
        "select s.id, s.title, s.platform, s.body from public.content_items s"
        " where s.kind = 'script' and s.status = 'ready'"
        " and not exists (select 1 from public.content_items v where v.parent_id = s.id"
        "                 and v.kind = 'video')"
        " order by s.created_at limit 2"
    ).fetchall()
    rendered = []
    for s in scripts:
        body = s["body"]
        with tempfile.TemporaryDirectory(prefix="puavi-render-") as tmp_dir:
            tmp = Path(tmp_dir)
            images = _download_images(ctx, body.get("product_handle", ""), tmp)
            scenes = [
                Scene(
                    seconds=float(sc["seconds"]),
                    text=sc["on_screen_text"],
                    image=images[i % len(images)] if images else None,
                )
                for i, sc in enumerate(body["scenes"])
            ]
            voice = None
            if ctx.services.tts:
                text = " ".join(sc["voiceover"] for sc in body["scenes"] if sc["voiceover"])
                if text.strip():
                    voice = tmp / "voz.mp3"
                    voice.write_bytes(ctx.services.tts.tts(text))
            out = tmp / "video.mp4"
            duration = render_vertical_video(scenes, out, voiceover=voice)
            path = f"videos/{ctx.today}/{s['id']}.mp4"
            ctx.services.storage.upload(path, out.read_bytes(), "video/mp4")
        caption = (
            body["caption"].strip()
            + "\n\n"
            + " ".join(h if h.startswith("#") else f"#{h}" for h in body.get("hashtags", []))
        )
        video_id = ctx.conn.execute(
            "select public.agent_save_content('creativo', 'video', %s, %s, %s, %s, %s, null, %s,"
            " 'in_review') as id",
            (
                s["platform"],
                s["title"],
                json.dumps(
                    {
                        "duration_s": round(duration, 1),
                        "caption": caption,
                        "voiceover": voice is not None,
                        "product_images": len(images),
                    },
                    ensure_ascii=False,
                ),
                s["id"],
                [path],
                ctx.job_id,
            ),
        ).fetchone()["id"]
        platforms = ["instagram", "tiktok"] if s["platform"] == "both" else [s["platform"]]
        for platform in platforms:
            submit_proposal(
                ctx.conn,
                agent_id="creativo",
                action=ActionType.PUBLISH_CONTENT,
                title=f"Publicar en {platform}: {s['title']}"[:200],
                summary=f"Vídeo de {duration:.0f} s. Pie de foto:\n{caption}"[:4000],
                payload={
                    "platform": platform,
                    "content_item_id": str(video_id),
                    "caption": caption[:2200],
                    "media_paths": [path],
                },
                idempotency_key=f"publish:{video_id}:{platform}",
            )
        rendered.append(str(video_id))
    return {"videos": rendered}
