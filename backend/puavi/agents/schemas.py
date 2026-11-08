"""Esquemas de salida de los agentes (structured outputs + validación)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["instagram", "tiktok", "both"]


class Trend(BaseModel):
    title: str
    description: str
    platform: Platform
    relevance: int = Field(ge=0, le=100)
    evidence_urls: list[str]


class ContentIdea(BaseModel):
    title: str
    platform: Platform
    format: Literal["reel", "carrusel", "historia", "tiktok"]
    hook: str
    why: str
    product_hint: str = ""


class TrendsOutput(BaseModel):
    trends: list[Trend]
    ideas: list[ContentIdea]
    injection_warnings: list[str]


class ResearchProduct(BaseModel):
    name: str
    category: str
    pet: Literal["perro", "gato", "ambos"]
    supplier: str
    supplier_url: str
    unit_cost_eur: float | None
    suggested_price_eur: float | None
    competitor_price_eur: float | None
    score: int = Field(ge=0, le=100)
    rationale: str
    sources: list[str]


class CompetitorFinding(BaseModel):
    name: str
    website: str
    summary: str
    promotions: list[str]
    notable_prices: list[str]
    sources: list[str]


class ResearchOutput(BaseModel):
    products: list[ResearchProduct]
    competitors: list[CompetitorFinding]
    injection_warnings: list[str]


class Scene(BaseModel):
    seconds: float = Field(ge=1, le=15)
    visual: str
    voiceover: str
    on_screen_text: str


class Script(BaseModel):
    idea_id: str
    title: str
    platform: Platform
    hook: str
    scenes: list[Scene]
    caption: str
    hashtags: list[str]
    product_handle: str = ""


class ScriptsOutput(BaseModel):
    scripts: list[Script]


class ReviewItem(BaseModel):
    item_id: str
    verdict: Literal["ok", "rejected"]
    issues: list[str]
    notes: str


class ReviewOutput(BaseModel):
    reviews: list[ReviewItem]


class ProductFinding(BaseModel):
    product_id: str
    score: int = Field(ge=0, le=100)
    issues: list[str]
    new_title: str = ""
    new_description_html: str = ""
    new_seo_title: str = ""
    new_seo_description: str = ""
    price_suggestion_eur: float | None = None
    price_variant_id: str = ""
    price_reason: str = ""
    manual_tasks: list[str]


class ShopifyAuditOutput(BaseModel):
    findings: list[ProductFinding]


class Priority(BaseModel):
    title: str
    description: str
    priority: int = Field(ge=1, le=4)


class DailyReportOutput(BaseModel):
    title: str
    summary_md: str
    priorities: list[Priority]
