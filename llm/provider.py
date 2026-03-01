"""
LLM Provider — pluggable interface, default OpenRouter via openai SDK.

All passes use tool calling. The provider sends messages + tool definitions,
forces a tool call via tool_choice="required", and returns the parsed
tool call arguments as a dict.

Supports extended thinking (reasoning) for models that allow it.
"""

from __future__ import annotations
import json
import logging
import os
from abc import ABC, abstractmethod

from openai import OpenAI
from dotenv import load_dotenv

log = logging.getLogger('parseltongue.llm')


class LLMProvider(ABC):
    """Abstract interface for LLM tool-calling completion."""

    @abstractmethod
    def complete(self, messages: list[dict], tools: list[dict],
                 **kwargs) -> dict:
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


class OpenRouterProvider(LLMProvider):
    """OpenAI-compatible provider via OpenRouter.

    Reads OPENROUTER_API_KEY from environment or .env file.

    Args:
        model: OpenRouter model ID (default: anthropic/claude-sonnet-4.6)
        api_key: explicit API key (falls back to OPENROUTER_API_KEY env var)
        base_url: OpenRouter API base URL
        reasoning: enable extended thinking. Pass True for adaptive thinking,
            or an int for a specific reasoning token budget.
            None (default) disables reasoning.
    """

    def __init__(self, model: str = "anthropic/claude-sonnet-4.6",
                 api_key: str | None = None,
                 base_url: str = "https://openrouter.ai/api/v1",
                 reasoning: bool | int | None = None):
        load_dotenv()
        self._api_key = api_key or os.environ["OPENROUTER_API_KEY"]
        self._model = model
        self._client = OpenAI(api_key=self._api_key, base_url=base_url)
        self._reasoning = reasoning

    def _reasoning_config(self) -> dict | None:
        """Build the reasoning extra_body config."""
        if self._reasoning is None or self._reasoning is False:
            return None
        if self._reasoning is True:
            return {"reasoning": {"max_tokens": 10000}}
        if isinstance(self._reasoning, int):
            return {"reasoning": {"max_tokens": self._reasoning}}
        return None

    def complete(self, messages: list[dict], tools: list[dict],
                 **kwargs) -> dict:
        extra_body = kwargs.pop('extra_body', {})
        reasoning_cfg = self._reasoning_config()
        if reasoning_cfg:
            extra_body.update(reasoning_cfg)

        create_kwargs = dict(
            model=self._model,
            messages=messages,
            tools=tools,
            tool_choice="required",
            **kwargs,
        )
        if extra_body:
            create_kwargs['extra_body'] = extra_body

        log.debug("Request params (no messages): %s",
                  {k: v for k, v in create_kwargs.items()
                   if k not in ('messages',)})

        response = self._client.chat.completions.create(**create_kwargs)

        msg = response.choices[0].message

        # Log reasoning if present
        reasoning_content = getattr(msg, 'reasoning', None) or getattr(msg, 'reasoning_content', None)
        if reasoning_content:
            log.debug("Reasoning:\n%s", reasoning_content)

        tool_call = msg.tool_calls[0]
        return json.loads(tool_call.function.arguments)
