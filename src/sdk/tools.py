"""Tool definitions and registry for LLM function calling."""

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5


@dataclass
class Tool:
    """A callable tool with OpenAI-compatible JSON Schema."""

    name: str
    description: str
    parameters: dict  # JSON Schema for parameters
    handler: Callable  # async or sync callable
    require_confirmation: bool = False

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Manages a collection of tools available to an agent."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_schemas(self) -> list[dict]:
        return [t.to_openai_schema() for t in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self):
        return iter(self._tools.values())


def tool(
    name: str = "",
    description: str = "",
    require_confirmation: bool = False,
) -> Callable:
    """Decorator to create a Tool from a function.

    Infers JSON Schema from type hints and docstring.
    """
    def decorator(fn: Callable) -> Tool:
        sig = inspect.signature(fn)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            param_type = "string"
            if param.annotation is not inspect.Parameter.empty:
                anno = param.annotation
                if anno is int:
                    param_type = "integer"
                elif anno is float:
                    param_type = "number"
                elif anno is bool:
                    param_type = "boolean"
                elif anno is list or str(anno).startswith("list"):
                    param_type = "array"
                elif anno is dict or str(anno).startswith("dict"):
                    param_type = "object"

            properties[param_name] = {"type": param_type}
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        schema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return Tool(
            name=name or fn.__name__,
            description=description or (fn.__doc__ or "").strip().split("\n")[0],
            parameters=schema,
            handler=fn,
            require_confirmation=require_confirmation,
        )

    return decorator


async def execute_tool_calls(
    tool_calls: list[dict],
    registry: ToolRegistry,
) -> list[dict]:
    """Execute tool calls from the LLM response and return results."""
    results = []

    async def run_one(call: dict) -> dict:
        fn_call = call.get("function", call)
        fn_name = fn_call.get("name", "")
        tool = registry.get(fn_name)

        if tool is None:
            return {
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": json.dumps({"error": f"Tool '{fn_name}' not found"}),
            }

        try:
            raw_args = fn_call.get("arguments", "{}")
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = {}

        try:
            if asyncio.iscoroutinefunction(tool.handler):
                result = await tool.handler(**args)
            else:
                result = tool.handler(**args)
            content = json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            logger.exception("Tool '%s' execution failed", fn_name)
            content = json.dumps({"error": str(e)})

        return {
            "role": "tool",
            "tool_call_id": call.get("id", ""),
            "content": content,
        }

    tasks = [run_one(c) for c in tool_calls]
    results = await asyncio.gather(*tasks)
    return list(results)
