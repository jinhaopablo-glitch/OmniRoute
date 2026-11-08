"""Dobles de prueba: API de Claude y servicios externos (sin red)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel


@dataclass
class FakeUsage:
    input_tokens: int = 1000
    output_tokens: int = 500
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    server_tool_use: Any = None


@dataclass
class FakeBlock:
    type: str
    id: str = ""
    name: str = ""
    input: dict | None = None


@dataclass
class FakeResponse:
    stop_reason: str
    parsed_output: Any = None
    content: list = field(default_factory=list)
    usage: FakeUsage = field(default_factory=FakeUsage)


Responder = Callable[[dict[str, Any]], FakeResponse]


class FakeMessages:
    def __init__(self, responder: Responder):
        self.responder = responder
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return self.responder(kwargs)


class FakeAnthropic:
    """Devuelve salidas según el modelo de salida pedido."""

    def __init__(
        self,
        outputs: dict[type[BaseModel], Callable[[dict], BaseModel]] | None = None,
        responder: Responder | None = None,
    ):
        outputs = outputs or {}

        def default(kwargs: dict[str, Any]) -> FakeResponse:
            model = kwargs["output_format"]
            return FakeResponse("end_turn", parsed_output=outputs[model](kwargs))

        self.messages = FakeMessages(responder or default)


class FakeShopify:
    def __init__(self, products: list[dict[str, Any]]):
        self.products = products
        self.updates: list[tuple] = []

    def list_products(self, limit: int = 10, query: str | None = None) -> list[dict[str, Any]]:
        if query and query.startswith("handle:"):
            handle = query.split(":", 1)[1]
            return [p for p in self.products if p["handle"] == handle]
        return self.products[:limit]

    def orders_summary(self, day: date) -> dict[str, Any]:
        return {"orders": 3, "revenue_eur": 89.7, "aov_eur": 29.9, "top_products": []}

    def update_variant_price(self, product_id, variant_id, price):
        self.updates.append(("price", product_id, variant_id, str(price)))
        return {"ok": True}

    def update_product(self, product_id, changes):
        self.updates.append(("product", product_id, changes))
        return {"ok": True}


class FakeInstagram:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    def publish_reel(self, video_url: str, caption: str) -> dict[str, str]:
        self.published.append((video_url, caption))
        return {"media_id": "1789", "url": "https://www.instagram.com/reel/abc/"}

    def daily_insights(self, day):
        return {"reach": 1200, "followers": 340}


def product(pid: str = "gid://shopify/Product/1", handle: str = "arnes-acolchado") -> dict:
    return {
        "id": pid,
        "title": "Arnés acolchado",
        "handle": handle,
        "status": "ACTIVE",
        "descriptionHtml": "<p>Arnés</p>",
        "seo": {"title": "", "description": ""},
        "media": {"nodes": []},
        "variants": {
            "nodes": [
                {
                    "id": "gid://shopify/ProductVariant/1",
                    "title": "M",
                    "price": "24.90",
                    "compareAtPrice": None,
                    "sku": "A1",
                    "inventoryQuantity": 12,
                }
            ]
        },
    }
