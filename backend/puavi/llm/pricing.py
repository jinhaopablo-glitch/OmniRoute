"""Precios de la API de Claude para calcular el coste de cada ejecución.

USD por millón de tokens. Revisar periódicamente en la web oficial de precios
de Anthropic; actualizar aquí si cambian.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

MTOK = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write_5m: Decimal  # escritura de caché con TTL de 5 minutos (1,25x entrada)


def _p(inp: str, out: str, cache_read: str) -> ModelPrice:
    i = Decimal(inp)
    return ModelPrice(i, Decimal(out), Decimal(cache_read), i * Decimal("1.25"))


PRICES: dict[str, ModelPrice] = {
    "claude-opus-5-5": _p("4.00", "20.00", "0.20"),
    "claude-sonnet-5-5": _p("2.00", "10.00", "0.20"),
    "claude-haiku-5-5": _p("0.10", "0.50", "0.01"),
}

WEB_SEARCH_USD_PER_1000 = Decimal("10.00")
BATCH_DISCOUNT = Decimal("0.50")


class UnknownModelError(KeyError):
    pass


def run_cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    web_searches: int = 0,
    batch: bool = False,
) -> Decimal:
    """Coste de una llamada. ``input_tokens`` excluye los tokens leídos/escritos en caché."""
    try:
        price = PRICES[model]
    except KeyError as exc:
        raise UnknownModelError(f"Modelo sin precio configurado: {model}") from exc
    for value in (input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, web_searches):
        if value < 0:
            raise ValueError("Los contadores no pueden ser negativos")
    tokens_cost = (
        Decimal(input_tokens) * price.input
        + Decimal(output_tokens) * price.output
        + Decimal(cache_read_tokens) * price.cache_read
        + Decimal(cache_write_tokens) * price.cache_write_5m
    ) / MTOK
    if batch:
        tokens_cost *= BATCH_DISCOUNT
    search_cost = Decimal(web_searches) * WEB_SEARCH_USD_PER_1000 / Decimal(1000)
    return (tokens_cost + search_cost).quantize(Decimal("0.000001"))
