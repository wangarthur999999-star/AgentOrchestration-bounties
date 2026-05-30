"""LLMAgent — concrete BaseAgent backed by DeepSeek API with tool calling."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Optional

from openai import AsyncOpenAI

from src.sdk.agent import BaseAgent
from src.sdk.tools import MAX_TOOL_ITERATIONS, ToolRegistry, execute_tool_calls

if TYPE_CHECKING:
    from src.orchestrator.protocol import AgentMessage, MessageType

logger = logging.getLogger(__name__)


class LLMAgent(BaseAgent):
    """Concrete agent powered by an LLM backend.

    Different agent behaviors are achieved through different system prompts,
    not different subclasses. Use in both single-agent and team modes.

    Tool calling: pass `tools` (ToolRegistry) to enable function calling.
    The agent loops until the LLM returns content without tool_calls.
    """

    def __init__(
        self,
        agent_id: str,
        name: str,
        system_prompt: str,
        api_key: str = "",
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        config: Optional[dict] = None,
        tools: Optional[ToolRegistry] = None,
    ):
        super().__init__(agent_id, name, config)
        self.system_prompt = system_prompt
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._client: Optional[AsyncOpenAI] = None
        self._conversation_history: list[dict] = []
        self.outbox: list = []
        self._tool_registry = tools
        self._tool_choice: str = "auto"

    @property
    def tools(self) -> Optional[ToolRegistry]:
        return self._tool_registry

    @tools.setter
    def tools(self, registry: ToolRegistry) -> None:
        self._tool_registry = registry

    async def setup(self) -> None:
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        self._conversation_history = [
            {"role": "system", "content": self.system_prompt}
        ]

    async def handle_task(self, task: dict) -> dict:
        """Process a single-agent task. Returns the LLM response as a dict."""
        prompt = task.get("prompt", task.get("message", str(task)))
        messages = self._conversation_history + [{"role": "user", "content": prompt}]
        raw = await self._call_llm(messages)
        return {"agent": self.name, "agent_id": self.agent_id, "output": raw}

    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """Process an incoming message in team mode. Returns a response message."""
        from src.orchestrator.protocol import AgentMessage, MessageType

        role_map = {
            MessageType.TASK: "user",
            MessageType.QUERY: "user",
            MessageType.RESPONSE: "assistant",
            MessageType.VOTE: "assistant",
            MessageType.BROADCAST: "user",
            MessageType.ERROR: "user",
        }
        role = role_map.get(message.type, "user")
        content = json.dumps(message.payload, ensure_ascii=False)
        self._conversation_history.append({"role": role, "content": content})

        raw = await self._call_llm(self._conversation_history)

        self._conversation_history.append({"role": "assistant", "content": raw})

        response = AgentMessage(
            type=MessageType.RESPONSE,
            from_agent=self.agent_id,
            to_agent=message.from_agent,
            team_id=message.team_id,
            payload={"content": raw, "agent": self.name},
            reply_to=message.id,
        )
        self.outbox.append(response)
        return response

    async def cleanup(self) -> None:
        self._conversation_history.clear()

    async def _call_llm(self, messages: list[dict]) -> str:
        """Call the LLM. If tools are registered, handles the tool-calling loop."""
        if self._tool_registry and len(self._tool_registry) > 0:
            return await self._call_llm_with_tools(messages)
        return await self._call_llm_raw(messages)

    async def _call_llm_raw(self, messages: list[dict]) -> str:
        """Single LLM call without tool support."""
        max_tokens = self.config.get("max_tokens", 2048)
        temperature = self.config.get("temperature", 0.3)

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    async def _call_llm_with_tools(self, messages: list[dict]) -> str:
        """LLM call with tool-calling loop. Executes tools and feeds results back."""
        max_tokens = self.config.get("max_tokens", 2048)
        temperature = self.config.get("temperature", 0.3)
        working_messages = list(messages)

        for _ in range(MAX_TOOL_ITERATIONS):
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=working_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                tools=self._tool_registry.list_schemas(),
                tool_choice=self._tool_choice,
            )

            choice = response.choices[0]
            msg = choice.message

            if msg.content and not msg.tool_calls:
                return msg.content

            if msg.tool_calls:
                tool_calls_data = [
                    {
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]

                working_messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": tool_calls_data,
                })

                results = await execute_tool_calls(tool_calls_data, self._tool_registry)
                working_messages.extend(results)

            elif msg.content:
                return msg.content

        return response.choices[0].message.content or ""

    def reset_conversation(self) -> None:
        """Clear conversation history but keep the system prompt."""
        self._conversation_history = [
            {"role": "system", "content": self.system_prompt}
        ]
