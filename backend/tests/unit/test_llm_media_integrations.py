"""Cliente de IA, montaje de vídeo e integraciones HTTP (sin red real)."""

from __future__ import annotations

import json
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from puavi.agents.shopify_agent import clean_html
from puavi.integrations.http import IntegrationError
from puavi.integrations.instagram import InstagramClient
from puavi.integrations.shopify import ShopifyClient
from puavi.integrations.storage import LocalStorage, check_path
from puavi.integrations.tiktok import TikTokClient
from puavi.llm.client import AgentLLM, ClientTool
from puavi.media.video import Scene, build_ass, render_vertical_video, scene_durations
from tests.fakes import FakeAnthropic, FakeBlock, FakeResponse

# --- Cliente de IA -------------------------------------------------------------------


class Out(BaseModel):
    answer: str


class FakeConn:
    """Simula las llamadas SQL que hace AgentLLM."""

    def __init__(self, allowed: bool = True):
        self.allowed = allowed
        self.runs: list[tuple] = []

    def execute(self, sql, params=None):
        conn = self

        class R:
            def fetchone(self):
                if "check_budget" in sql:
                    return {
                        "allowed": conn.allowed,
                        "reason": "límite",
                        "global_daily_spent": 0,
                        "global_monthly_spent": 0,
                        "agent_daily_spent": 0,
                    }
                conn.runs.append(params)
                return {"id": "run-1"}

        return R()


def test_llm_tool_loop_and_cost():
    calls = {"n": 0}

    def responder(kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse(
                "tool_use",
                content=[FakeBlock("tool_use", id="t1", name="buscar", input={"q": "arnés"})],
            )
        if calls["n"] == 2:
            return FakeResponse("pause_turn", content=[])
        return FakeResponse("end_turn", parsed_output=Out(answer="hecho"))

    tool = ClientTool("buscar", "Busca", {"type": "object"}, lambda i: {"ok": i["q"]})
    llm = AgentLLM(client=FakeAnthropic(responder=responder))
    conn = FakeConn()
    res = llm.run(
        conn,
        agent_id="marketing",
        model="claude-opus-5-5",
        effort="low",
        system="s",
        prompt="p",
        output_model=Out,
        tools=[tool],
        web_search=True,
    )
    assert res.output.answer == "hecho"
    assert res.usage.input_tokens == 3000 and res.cost_usd > 0
    # La lista de mensajes es compartida entre llamadas: [user, assistant, tool_results, ...]
    sent = llm.client.messages.calls[1]["messages"][2]["content"][0]
    assert sent["type"] == "tool_result" and json.loads(sent["content"]) == {"ok": "arnés"}
    assert any(t.get("name") == "web_search" for t in llm.client.messages.calls[0]["tools"])
    assert llm.client.messages.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert conn.runs[-1][9] == "ok"


def test_llm_budget_blocked_before_any_call():
    from puavi.core.budget import BudgetExceededError

    llm = AgentLLM(client=FakeAnthropic(responder=lambda k: pytest.fail("no debe llamar")))
    conn = FakeConn(allowed=False)
    with pytest.raises(BudgetExceededError):
        llm.run(
            conn,
            agent_id="marketing",
            model="claude-opus-5-5",
            effort="low",
            system="s",
            prompt="p",
            output_model=Out,
        )
    assert conn.runs[-1][9] == "blocked"


def test_llm_refusal_and_unknown_tool():
    llm = AgentLLM(client=FakeAnthropic(responder=lambda k: FakeResponse("refusal")))
    with pytest.raises(RuntimeError):
        llm.run(
            FakeConn(),
            agent_id="x",
            model="claude-opus-5-5",
            effort="low",
            system="s",
            prompt="p",
            output_model=Out,
        )
    result = AgentLLM._call_tool({}, FakeBlock("tool_use", id="t", name="borrar_todo", input={}))
    assert result["is_error"] is True


# --- Vídeo ----------------------------------------------------------------------------


def test_ass_subtitles_are_escaped():
    ass = build_ass([Scene(2, "Hola {\\b1}mundo")], [2.0])
    assert "{\\b1}" not in ass and "Hola (b1)mundo" in ass


def test_scene_durations_follow_voiceover():
    d = scene_durations([Scene(2, "a"), Scene(2, "b")], 9.5)
    assert sum(d) == pytest.approx(10.0)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sin FFmpeg")
def test_render_vertical_video(tmp_path: Path):
    import subprocess

    img = tmp_path / "foto.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0xC66A3D:s=800x600:d=1",
            "-frames:v",
            "1",
            str(img),
        ],
        check=True,
        capture_output=True,
    )
    out = tmp_path / "v.mp4"
    duration = render_vertical_video([Scene(2, "Arnés PUAVI", img), Scene(2, "¡Pruébalo!")], out)
    assert 3.5 <= duration <= 4.5
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.strip() == "1080,1920"


# --- Integraciones --------------------------------------------------------------------


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_shopify_graphql_and_price_update():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        body = json.loads(req.content)
        if "productVariantsBulkUpdate" in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "productVariantsBulkUpdate": {
                            "productVariants": [{"id": "v1", "price": "9.90"}],
                            "userErrors": [],
                        }
                    }
                },
            )
        return httpx.Response(200, json={"errors": [{"message": "Access denied"}]})

    shop = ShopifyClient("puavi.myshopify.com", "shpat_secreto", http=_client(handler))
    assert shop.update_variant_price("p1", "v1", Decimal("9.90"))["variants"][0]["price"] == "9.90"
    assert seen[0].headers["X-Shopify-Access-Token"] == "shpat_secreto"
    with pytest.raises(IntegrationError) as exc:
        shop.list_products()
    assert "shpat_secreto" not in str(exc.value)


def test_shopify_rejects_non_shopify_domain():
    with pytest.raises(ValueError):
        ShopifyClient("evil.example.com", "x")


def test_instagram_publish_flow():
    def handler(req: httpx.Request):
        path = req.url.path
        if path.endswith("/media") and req.method == "POST":
            return httpx.Response(200, json={"id": "c1"})
        if path.endswith("/c1"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "m1"})
        if path.endswith("/m1"):
            return httpx.Response(200, json={"permalink": "https://instagram.com/reel/x"})
        return httpx.Response(404)

    ig = InstagramClient("tok", "17841", http=_client(handler), poll_seconds=0)
    assert ig.publish_reel("https://x/v.mp4", "Hola") == {
        "media_id": "m1",
        "url": "https://instagram.com/reel/x",
    }


def test_instagram_processing_error():
    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"id": "c1"})
        return httpx.Response(200, json={"status_code": "ERROR"})

    ig = InstagramClient("tok", "1", http=_client(handler), poll_seconds=0)
    with pytest.raises(IntegrationError):
        ig.publish_reel("https://x/v.mp4", "Hola")


def test_tiktok_inbox_upload(tmp_path: Path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 1000)
    puts = []

    def handler(req: httpx.Request):
        if req.url.path.endswith("/inbox/video/init/"):
            assert json.loads(req.content)["source_info"]["video_size"] == 1000
            return httpx.Response(
                200,
                json={
                    "data": {"upload_url": "https://up.tiktok/x", "publish_id": "p1"},
                    "error": {"code": "ok"},
                },
            )
        puts.append(req.headers["Content-Range"])
        return httpx.Response(201)

    tt = TikTokClient("tok", http=_client(handler))
    assert tt.upload_video(video) == {"publish_id": "p1", "mode": "inbox"}
    assert puts == ["bytes 0-999/1000"]


def test_http_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        return (
            httpx.Response(503)
            if state["n"] < 3
            else httpx.Response(200, json={"data": {"products": {"nodes": []}}})
        )

    shop = ShopifyClient("puavi.myshopify.com", "t", http=_client(handler))
    assert shop.list_products() == [] and state["n"] == 3


def test_storage_path_validation(tmp_path: Path):
    for bad in ("../etc/passwd", "/abs", "a b.mp4", "x/../../y"):
        with pytest.raises(ValueError):
            check_path(bad)
    st = LocalStorage(tmp_path)
    st.upload("videos/2026-01-01/a.mp4", b"abc", "video/mp4")
    assert st.download("videos/2026-01-01/a.mp4") == b"abc"


def test_clean_html_strips_unsafe_tags():
    html = (
        '<p onclick="x">Hola</p><script>alert(1)</script><img src=x onerror=y><strong>ok</strong>'
    )
    assert clean_html(html) == "Hola</p>alert(1)<strong>ok</strong>"


def test_orders_summary_aggregates(monkeypatch):
    def handler(req):
        return httpx.Response(
            200,
            json={
                "data": {
                    "orders": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "1",
                                "cancelledAt": None,
                                "currentTotalPriceSet": {
                                    "shopMoney": {"amount": "30.00", "currencyCode": "EUR"}
                                },
                                "lineItems": {"nodes": [{"title": "Arnés", "quantity": 1}]},
                            },
                            {
                                "id": "2",
                                "cancelledAt": "2026-01-01",
                                "currentTotalPriceSet": {
                                    "shopMoney": {"amount": "99.00", "currencyCode": "EUR"}
                                },
                                "lineItems": {"nodes": []},
                            },
                        ],
                    }
                }
            },
        )

    shop = ShopifyClient("puavi.myshopify.com", "t", http=_client(handler))
    s = shop.orders_summary(date(2026, 1, 1))
    assert s["orders"] == 1 and s["cancelled"] == 1 and s["revenue_eur"] == 30.0
