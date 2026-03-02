"""
LLM Provider — pluggable abstract interface for tool-calling completion.

All passes use tool calling. The provider sends messages + tool definitions,
forces a tool call via tool_choice="required", and returns the parsed
tool call arguments as a dict.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract interface for LLM tool-calling completion."""

    @abstractmethod
    def complete(self, messages: list[dict], tools: list[dict], **kwargs) -> dict:
        """Send messages with tool definitions, return tool call arguments.

        The LLM is forced to call exactly one tool (tool_choice="required").

        Args:
            messages: list of {"role": ..., "content": ...} dicts
            tools: list of OpenAI-format tool definitions
            **kwargs: provider-specific options (temperature, max_tokens, etc.)

        Returns:
            Parsed arguments dict from the tool call
            (e.g. {"dsl_output": "..."} or {"markdown": "..."}).
        """
        ...

    async def async_complete(self, messages: list[dict], tools: list[dict], **kwargs) -> dict:
        """Async version of complete(). Default: runs sync in a thread."""
        import asyncio

        return await asyncio.to_thread(self.complete, messages, tools, **kwargs)

    def cancel(self) -> None:
        """Cancel any in-flight request. Override in subclasses."""
