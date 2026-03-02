"""OpenRouter provider — OpenAI-compatible LLM via OpenRouter."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

from .provider import LLMProvider

log = logging.getLogger("parseltongue.llm")


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

    def __init__(
        self,
        model: str = "anthropic/claude-sonnet-4.6",
        api_key: str | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
        reasoning: bool | int | None = None,
    ):
        load_dotenv()
        self._api_key = api_key or os.environ["OPENROUTER_API_KEY"]
        self._model = model
        self._base_url = base_url
        self._async_client = AsyncOpenAI(api_key=self._api_key, base_url=base_url)
        self._reasoning = reasoning
        self._cancelled = False
        self._running_loop: asyncio.AbstractEventLoop | None = None
        self._running_task: asyncio.Task | None = None

    def _reasoning_config(self) -> dict | None:
        """Build the reasoning extra_body config."""
        if self._reasoning is None or self._reasoning is False:
            return None
        if self._reasoning is True:
            return {"reasoning": {"max_tokens": 10000}}
        if isinstance(self._reasoning, int):
            return {"reasoning": {"max_tokens": self._reasoning}}
        return None

    def _build_create_kwargs(self, messages, tools, **kwargs) -> dict:
        """Build the kwargs dict for chat.completions.create."""
        extra_body = kwargs.pop("extra_body", {})
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
            create_kwargs["extra_body"] = extra_body
        return create_kwargs

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Cancel in-flight request by cancelling the running asyncio task."""
        self._cancelled = True
        loop = self._running_loop
        task = self._running_task
        if loop is not None and task is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)

    def complete(self, messages: list[dict], tools: list[dict], **kwargs) -> dict:
        try:
            return asyncio.run(self.async_complete(messages, tools, **kwargs))
        except asyncio.CancelledError:
            raise InterruptedError("Request cancelled")

    async def async_complete(self, messages: list[dict], tools: list[dict], **kwargs) -> dict:
        """Async streaming completion — cancellable via cancel()."""
        self._cancelled = False
        self._running_loop = asyncio.get_running_loop()
        self._running_task = asyncio.current_task()

        create_kwargs = self._build_create_kwargs(messages, tools, **kwargs)
        create_kwargs["stream"] = True

        log.debug(
            "Request params (no messages): %s",
            {k: v for k, v in create_kwargs.items() if k not in ("messages", "stream")},
        )

        try:
            stream = await self._async_client.chat.completions.create(**create_kwargs)

            tool_args = ""
            reasoning_parts: list[str] = []

            try:
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.tool_calls:
                        tc = delta.tool_calls[0]
                        if tc.function and tc.function.arguments:
                            tool_args += tc.function.arguments
                    r = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
                    if r:
                        reasoning_parts.append(r)
            finally:
                await stream.close()

            if reasoning_parts:
                log.debug("Reasoning:\n%s", "".join(reasoning_parts))

            return json.loads(tool_args)
        finally:
            self._running_loop = None
            self._running_task = None
