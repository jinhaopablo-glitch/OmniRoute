"""Registro de manejadores de acciones aprobadas.

En la Fase 0 no hay integraciones reales: cada tipo de acción se registra
en su fase (Shopify en F3, publicación en F5, anuncios en F6). Una acción sin
manejador falla de forma segura y queda registrada; nunca se ejecuta "a medias".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from puavi.core.proposals import ActionType


@dataclass(frozen=True)
class ExecutionContext:
    proposal_id: str
    idempotency_key: str  # se envía a la API externa cuando lo soporta
    attempt: int


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    details: dict[str, Any] = field(default_factory=dict)


class ActionHandler(Protocol):
    def __call__(self, payload: dict[str, Any], ctx: ExecutionContext) -> ExecutionResult: ...


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[ActionType, ActionHandler] = {}

    def register(self, action: ActionType, handler: ActionHandler) -> None:
        if action in self._handlers:
            raise ValueError(f"Ya hay un manejador para {action}")
        self._handlers[action] = handler

    def get(self, action: ActionType) -> ActionHandler | None:
        return self._handlers.get(action)

    def __contains__(self, action: object) -> bool:
        return action in self._handlers
