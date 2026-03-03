"""Tests for LLM provider — mock the OpenAI client."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from .. import openrouter
from ..openrouter import OpenRouterProvider
from ..provider import LLMProvider
from ..tools import ANSWER_TOOL, EXTRACT_TOOL


class TestLLMProviderInterface(unittest.TestCase):
    def test_cannot_instantiate_abstract(self):
        with self.assertRaises(TypeError):
            LLMProvider()

    def test_concrete_subclass_works(self):
        class Dummy(LLMProvider):
            def complete(self, messages, tools, **kwargs):
                return {"dsl_output": "test"}

        d = Dummy()
        self.assertEqual(d.complete([], []), {"dsl_output": "test"})


def _make_stream_chunks(tool_args_json: str):
    """Build a list of mock streaming chunks that yield tool call arguments."""
    chunk = MagicMock()
    delta = MagicMock()
    tc = MagicMock()
    tc.function.arguments = tool_args_json
    delta.tool_calls = [tc]
    delta.reasoning = None
    delta.reasoning_content = None
    chunk.choices = [MagicMock(delta=delta)]
    return [chunk]


class _AsyncStreamIterator:
    """Mock async iterator + close() for streaming responses."""

    def __init__(self, chunks):
        self._chunks = chunks
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk

    async def close(self):
        pass


class TestOpenRouterProvider(unittest.TestCase):
    @patch(f"{openrouter.__name__}.load_dotenv")
    @patch(f"{openrouter.__name__}.AsyncOpenAI")
    def test_init_with_explicit_key(self, mock_openai_cls, mock_dotenv):
        provider = OpenRouterProvider(api_key="test-key")
        mock_openai_cls.assert_called_once_with(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
        )

    @patch(f"{openrouter.__name__}.load_dotenv")
    @patch(f"{openrouter.__name__}.AsyncOpenAI")
    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "env-key"})
    def test_init_from_env(self, mock_openai_cls, mock_dotenv):
        provider = OpenRouterProvider()
        mock_openai_cls.assert_called_once_with(
            api_key="env-key",
            base_url="https://openrouter.ai/api/v1",
        )

    @patch(f"{openrouter.__name__}.load_dotenv")
    @patch(f"{openrouter.__name__}.AsyncOpenAI")
    def test_complete_parses_tool_call(self, mock_openai_cls, mock_dotenv):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        tool_args = json.dumps({"dsl_output": "(fact x 5)"})
        stream = _AsyncStreamIterator(_make_stream_chunks(tool_args))
        mock_client.chat.completions.create = AsyncMock(return_value=stream)

        provider = OpenRouterProvider(api_key="test-key")
        result = provider.complete(
            messages=[{"role": "user", "content": "test"}],
            tools=[EXTRACT_TOOL],
        )

        self.assertEqual(result, {"dsl_output": "(fact x 5)"})

        call_kwargs = mock_client.chat.completions.create.call_args
        self.assertEqual(call_kwargs.kwargs["tool_choice"], "required")

    @patch(f"{openrouter.__name__}.load_dotenv")
    @patch(f"{openrouter.__name__}.AsyncOpenAI")
    def test_complete_passes_kwargs(self, mock_openai_cls, mock_dotenv):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        tool_args = json.dumps({"markdown": "# Answer"})
        stream = _AsyncStreamIterator(_make_stream_chunks(tool_args))
        mock_client.chat.completions.create = AsyncMock(return_value=stream)

        provider = OpenRouterProvider(api_key="test-key")
        provider.complete(
            messages=[],
            tools=[ANSWER_TOOL],
            temperature=0.2,
            max_tokens=500,
        )

        call_kwargs = mock_client.chat.completions.create.call_args
        self.assertEqual(call_kwargs.kwargs["temperature"], 0.2)
        self.assertEqual(call_kwargs.kwargs["max_tokens"], 500)


if __name__ == "__main__":
    unittest.main()
