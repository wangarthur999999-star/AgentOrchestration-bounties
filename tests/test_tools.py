"""Tests for Tool Calling system."""

import pytest

from src.sdk.tools import MAX_TOOL_ITERATIONS, Tool, ToolRegistry, execute_tool_calls, tool


class TestTool:
    def test_to_openai_schema(self):
        t = Tool(
            name="search",
            description="Search the web",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=lambda query: f"results for {query}",
        )
        schema = t.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "search"
        assert "parameters" in schema["function"]


class TestToolDecorator:
    def test_basic_function(self):
        @tool(name="add", description="Add two numbers")
        def add(a: int, b: int) -> int:
            return a + b

        assert add.name == "add"
        assert add.description == "Add two numbers"
        assert add.parameters["type"] == "object"
        assert "a" in add.parameters["properties"]
        assert "b" in add.parameters["properties"]
        assert add.handler(3, 4) == 7

    def test_description_from_docstring(self):
        @tool(name="greet")
        def greet(name: str) -> str:
            """Return a greeting for the given name."""
            return f"Hello, {name}!"

        assert greet.description == "Return a greeting for the given name."

    def test_required_parameters(self):
        @tool(name="divide")
        def divide(a: float, b: float, precision: int = 2) -> float:
            return round(a / b, precision)

        required = divide.parameters.get("required", [])
        assert "a" in required
        assert "b" in required
        assert "precision" not in required


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        t = Tool("echo", "Echo input", {"type": "object", "properties": {}}, lambda x: x)
        reg.register(t)
        assert reg.get("echo") is t
        assert "echo" in reg
        assert len(reg) == 1

    def test_unregister(self):
        reg = ToolRegistry()
        t = Tool("echo", "Echo", {"type": "object", "properties": {}}, lambda x: x)
        reg.register(t)
        reg.unregister("echo")
        assert reg.get("echo") is None
        assert len(reg) == 0

    def test_list_schemas(self):
        reg = ToolRegistry()
        reg.register(Tool("t1", "desc1", {"type": "object", "properties": {}}, lambda: 1))
        reg.register(Tool("t2", "desc2", {"type": "object", "properties": {}}, lambda: 2))
        schemas = reg.list_schemas()
        assert len(schemas) == 2
        names = [s["function"]["name"] for s in schemas]
        assert "t1" in names
        assert "t2" in names

    def test_iteration(self):
        reg = ToolRegistry()
        reg.register(Tool("a", "desc", {"type": "object", "properties": {}}, lambda: 1))
        reg.register(Tool("b", "desc", {"type": "object", "properties": {}}, lambda: 2))
        names = [t.name for t in reg]
        assert sorted(names) == ["a", "b"]


class TestExecuteToolCalls:
    @pytest.mark.asyncio
    async def test_execute_sync_handler(self):
        reg = ToolRegistry()
        reg.register(Tool(
            name="calc",
            description="Calculate",
            parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
            handler=lambda x: x * 2,
        ))
        calls = [{"id": "call_1", "function": {"name": "calc", "arguments": '{"x": 21}'}}]
        results = await execute_tool_calls(calls, reg)
        assert len(results) == 1
        assert results[0]["role"] == "tool"
        assert "42" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_tool_not_found(self):
        reg = ToolRegistry()
        calls = [{"id": "c1", "function": {"name": "nonexistent", "arguments": "{}"}}]
        results = await execute_tool_calls(calls, reg)
        assert "not found" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        reg = ToolRegistry()
        results_store = []

        def make_handler(prefix):
            def handler():
                results_store.append(prefix)
                return prefix
            return handler

        reg.register(Tool("a", "A", {"type": "object", "properties": {}}, make_handler("a")))
        reg.register(Tool("b", "B", {"type": "object", "properties": {}}, make_handler("b")))

        calls = [
            {"id": "c1", "function": {"name": "a", "arguments": "{}"}},
            {"id": "c2", "function": {"name": "b", "arguments": "{}"}},
        ]
        results = await execute_tool_calls(calls, reg)
        assert len(results) == 2
        # Both should have executed
        assert sorted(results_store) == ["a", "b"]

    @pytest.mark.asyncio
    async def test_tool_exception_captured(self):
        reg = ToolRegistry()
        def failing_handler():
            raise ValueError("boom")
        reg.register(Tool(
            name="fail",
            description="Always fails",
            parameters={"type": "object", "properties": {}},
            handler=failing_handler,
        ))
        calls = [{"id": "c1", "function": {"name": "fail", "arguments": "{}"}}]
        results = await execute_tool_calls(calls, reg)
        assert "error" in results[0]["content"]
