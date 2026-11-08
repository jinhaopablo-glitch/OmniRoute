"""Shopify Admin GraphQL API (oficial).

Se usan dos apps personalizadas distintas:
* lectura (agentes): read_products, read_orders, read_inventory.
* escritura (solo ejecutor): write_products.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx

from puavi.integrations.http import IntegrationError, new_client, request

DEFAULT_API_VERSION = "2026-10"


@dataclass
class ShopifyClient:
    store_domain: str  # tienda.myshopify.com
    token: str
    api_version: str = DEFAULT_API_VERSION
    http: httpx.Client | None = None

    def __post_init__(self) -> None:
        if not self.store_domain.endswith(".myshopify.com"):
            raise ValueError("SHOPIFY_STORE_DOMAIN debe ser <tienda>.myshopify.com")
        self.http = self.http or new_client()

    @property
    def url(self) -> str:
        return f"https://{self.store_domain}/admin/api/{self.api_version}/graphql.json"

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = request(
            self.http,
            "Shopify",
            "POST",
            self.url,
            json={"query": query, "variables": variables or {}},
            headers={"X-Shopify-Access-Token": self.token, "Content-Type": "application/json"},
        )
        body = resp.json()
        if body.get("errors"):
            raise IntegrationError("Shopify", str(body["errors"])[:500])
        return body["data"]

    # --- Lectura -----------------------------------------------------------------

    def list_products(self, limit: int = 10, query: str | None = None) -> list[dict[str, Any]]:
        q = """
        query($n: Int!, $q: String) {
          products(first: $n, query: $q, sortKey: UPDATED_AT) {
            nodes {
              id title handle status descriptionHtml productType tags vendor
              totalInventory onlineStoreUrl
              seo { title description }
              featuredMedia { preview { image { url altText } } }
              media(first: 5) { nodes { preview { image { url altText } } } }
              variants(first: 10) { nodes { id title price compareAtPrice sku inventoryQuantity } }
            }
          }
        }"""
        data = self.graphql(q, {"n": max(1, min(limit, 50)), "q": query})
        return data["products"]["nodes"]

    def orders_summary(self, day: date) -> dict[str, Any]:
        q = """
        query($q: String!, $after: String) {
          orders(first: 100, query: $q, after: $after) {
            pageInfo { hasNextPage endCursor }
            nodes {
              id cancelledAt
              currentTotalPriceSet { shopMoney { amount currencyCode } }
              lineItems(first: 50) { nodes { title quantity } }
            }
          }
        }"""
        search = (
            f"created_at:>={day.isoformat()} created_at:<{(day + timedelta(days=1)).isoformat()}"
        )
        orders: list[dict[str, Any]] = []
        after = None
        for _ in range(20):  # máximo 2.000 pedidos/día
            data = self.graphql(q, {"q": search, "after": after})["orders"]
            orders.extend(data["nodes"])
            if not data["pageInfo"]["hasNextPage"]:
                break
            after = data["pageInfo"]["endCursor"]
        valid = [o for o in orders if not o["cancelledAt"]]
        revenue = sum(Decimal(o["currentTotalPriceSet"]["shopMoney"]["amount"]) for o in valid)
        units: dict[str, int] = {}
        for o in valid:
            for li in o["lineItems"]["nodes"]:
                units[li["title"]] = units.get(li["title"], 0) + int(li["quantity"])
        top = sorted(units.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {
            "orders": len(valid),
            "cancelled": len(orders) - len(valid),
            "revenue_eur": float(revenue),
            "aov_eur": float(revenue / len(valid)) if valid else 0.0,
            "top_products": [{"title": t, "units": u} for t, u in top],
        }

    # --- Escritura (solo ejecutor) ------------------------------------------------

    def update_variant_price(self, product_id: str, variant_id: str, price: Decimal) -> dict:
        q = """
        mutation($pid: ID!, $variants: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $pid, variants: $variants) {
            productVariants { id price }
            userErrors { field message }
          }
        }"""
        data = self.graphql(
            q, {"pid": product_id, "variants": [{"id": variant_id, "price": str(price)}]}
        )["productVariantsBulkUpdate"]
        if data["userErrors"]:
            raise IntegrationError("Shopify", str(data["userErrors"])[:500])
        return {"variants": data["productVariants"]}

    def update_product(self, product_id: str, changes: dict[str, Any]) -> dict:
        product: dict[str, Any] = {"id": product_id}
        if "title" in changes:
            product["title"] = changes["title"]
        if "description_html" in changes:
            product["descriptionHtml"] = changes["description_html"]
        if "tags" in changes:
            product["tags"] = list(changes["tags"])
        seo = {}
        if "seo_title" in changes:
            seo["title"] = changes["seo_title"]
        if "seo_description" in changes:
            seo["description"] = changes["seo_description"]
        if seo:
            product["seo"] = seo
        q = """
        mutation($product: ProductUpdateInput!) {
          productUpdate(product: $product) {
            product { id title updatedAt }
            userErrors { field message }
          }
        }"""
        data = self.graphql(q, {"product": product})["productUpdate"]
        if data["userErrors"]:
            raise IntegrationError("Shopify", str(data["userErrors"])[:500])
        return {"product": data["product"]}
