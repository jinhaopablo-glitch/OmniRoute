"""Ejecución de agentes sobre la API de Claude (SDK oficial ``anthropic``).

Cada llamada:
  1. Comprueba el presupuesto (y el interruptor de emergencia) ANTES de gastar.
  2. Usa la guía de marca + rol como prompt de sistema cacheado.
  3. Devuelve una salida validada con un esquema Pydantic (structured outputs).
  4. Registra tokens, búsquedas y coste en ``agent_runs``.

Las herramientas de cliente que se pasan aquí son SOLO de lectura. Ninguna
herramienta de un agente puede ejecutar acciones sensibles.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from puavi.core.budget import require_budget
from puavi.llm.pricing import run_cost_usd

log = logging.getLogger("puavi.llm")

T = TypeVar("T", bound=BaseModel)
ToolHandler = Callable[[dict[str, Any]], Any]

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


class AgentRunError(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0

    def add(self, u: Any) -> None:
        self.input_tokens += getattr(u, "input_tokens", 0) or 0
        self.output_tokens += getattr(u, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
        stu = getattr(u, "server_tool_use", None)
        self.web_searches += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0


@dataclass
class RunResult(Generic[T]):
    output: T
    usage: Usage
    cost_usd: float
    run_id: str


@dataclass
class ClientTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class AgentLLM:
    """Envoltorio fino sobre ``anthropic.Anthropic``. ``client`` se inyecta (tests)."""

    client: Any
    max_iterations: int = 8
    max_tokens: int = 16000
    extra_tools: list[dict[str, Any]] = field(default_factory=list)

    def run(
        self,
        conn: psycopg.Connection,
        *,
        agent_id: str,
        model: str,
        effort: str,
        system: str,
        prompt: str,
        output_model: type[T],
        tools: list[ClientTool] | None = None,
        web_search: bool = False,
        max_searches: int = 5,
        job_id: str | None = None,
        summary: str = "",
    ) -> RunResult[T]:
        tools = tools or []
        handlers = {t.name: t.handler for t in tools}
        tool_defs: list[dict[str, Any]] = [t.definition() for t in tools]
        if web_search:
            tool_defs.append({**WEB_SEARCH_TOOL, "max_uses": max_searches})
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        usage = Usage()
        status, error, output = "error", None, None
        try:
            for _ in range(self.max_iterations):
                require_budget(conn, agent_id)
                kwargs: dict[str, Any] = {
                    "model": model,
                    "max_tokens": self.max_tokens,
                    "system": [
                        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                    ],
                    "messages": messages,
                    "thinking": {"type": "adaptive"},
                    "output_config": {"effort": effort},
                    "output_format": output_model,
                }
                if tool_defs:
                    kwargs["tools"] = tool_defs
                resp = self.client.messages.parse(**kwargs)
                usage.add(resp.usage)
                if resp.stop_reason == "refusal":
                    raise AgentRunError("El modelo rechazó la petición")
                if resp.stop_reason == "max_tokens":
                    raise AgentRunError("Respuesta truncada (max_tokens)")
                if resp.stop_reason == "pause_turn":
                    messages.append({"role": "assistant", "content": resp.content})
                    continue
                if resp.stop_reason == "tool_use":
                    messages.append({"role": "assistant", "content": resp.content})
                    results = []
                    for block in resp.content:
                        if getattr(block, "type", None) != "tool_use":
                            continue
                        results.append(self._call_tool(handlers, block))
                    messages.append({"role": "user", "content": results})
                    continue
                parsed = getattr(resp, "parsed_output", None)
                if parsed is None:
                    raise AgentRunError("La respuesta no cumple el esquema esperado")
                output = parsed
                status = "ok"
                break
            else:
                raise AgentRunError("Demasiadas iteraciones de herramientas")
        except Exception as exc:
            error = exc
            status = "blocked" if type(exc).__name__ == "BudgetExceededError" else "error"
            raise
        finally:
            cost = run_cost_usd(
                model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                web_searches=usage.web_searches,
            )
            row = conn.execute(
                "select public.record_agent_run(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " as id",
                (
                    agent_id,
                    job_id,
                    model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_read_tokens,
                    usage.cache_write_tokens,
                    usage.web_searches,
                    cost,
                    status,
                    summary
                    if status == "ok"
                    else f"{summary} · {type(error).__name__}: {error}"[:500],
                    Jsonb(output.model_dump(mode="json")) if output is not None else None,
                ),
            ).fetchone()
            run_id = str(row["id"])
        return RunResult(output=output, usage=usage, cost_usd=float(cost), run_id=run_id)

    @staticmethod
    def _call_tool(handlers: dict[str, ToolHandler], block: Any) -> dict[str, Any]:
        handler = handlers.get(block.name)
        if handler is None:
            return {
                "type": "tool_result",
                "tool_use_id": block.id,
                "is_error": True,
                "content": f"Herramienta desconocida: {block.name}",
            }
        try:
            result = handler(dict(block.input or {}))
        except Exception as exc:  # noqa: BLE001 - el error se devuelve al modelo
            log.warning("Herramienta %s falló: %s", block.name, exc)
            return {
                "type": "tool_result",
                "tool_use_id": block.id,
                "is_error": True,
                "content": f"Error: {type(exc).__name__}",
            }
        content = (
            result
            if isinstance(result, str)
            else json.dumps(result, ensure_ascii=False, default=str)
        )
        return {"type": "tool_result", "tool_use_id": block.id, "content": content[:60_000]}
