"""Importa todos los agentes para que registren sus tipos de trabajo."""

from puavi.agents import (  # noqa: F401
    analitico,
    creativo,
    investigacion,
    marketing,
    principal,
    shopify_agent,
    supervisor,
)
from puavi.agents.base import REGISTRY

__all__ = ["REGISTRY"]
