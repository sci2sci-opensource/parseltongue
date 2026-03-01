"""Tests for LLM provider — mock the OpenAI client."""

import json
import unittest
from unittest.mock import patch, MagicMock

from llm.provider import LLMProvider, OpenRouterProvider
from llm.tools import EXTRACT_TOOL, DERIVE_TOOL, ANSWER_TOOL


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


class TestOpenRouterProvider(unittest.TestCase):

    @patch('llm.provider.load_dotenv')
    @patch('llm.provider.OpenAI')
    def test_init_with_explicit_key(self, mock_openai_cls, mock_dotenv):
        provider = OpenRouterProvider(api_key="test-key")
        mock_openai_cls.assert_called_once_with(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
        )

    @patch('llm.provider.load_dotenv')
    @patch('llm.provider.OpenAI')
    @patch.dict('os.environ', {'OPENROUTER_API_KEY': 'env-key'})
    def test_init_from_env(self, mock_openai_cls, mock_dotenv):
        provider = OpenRouterProvider()
        mock_openai_cls.assert_called_once_with(
            api_key="env-key",
            base_url="https://openrouter.ai/api/v1",
        )

    @patch('llm.provider.load_dotenv')
    @patch('llm.provider.OpenAI')
    def test_complete_parses_tool_call(self, mock_openai_cls, mock_dotenv):
        # Build mock response chain
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_args = json.dumps({"dsl_output": "(fact x 5)"})
        mock_tool_call = MagicMock()
        mock_tool_call.function.arguments = mock_args

        mock_message = MagicMock()
        mock_message.tool_calls = [mock_tool_call]

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client.chat.completions.create.return_value = mock_response

        provider = OpenRouterProvider(api_key="test-key")
        result = provider.complete(
            messages=[{"role": "user", "content": "test"}],
            tools=[EXTRACT_TOOL],
        )

        self.assertEqual(result, {"dsl_output": "(fact x 5)"})

        # Verify tool_choice="required" was passed
        call_kwargs = mock_client.chat.completions.create.call_args
        self.assertEqual(call_kwargs.kwargs['tool_choice'], 'required')

    @patch('llm.provider.load_dotenv')
    @patch('llm.provider.OpenAI')
    def test_complete_passes_kwargs(self, mock_openai_cls, mock_dotenv):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_args = json.dumps({"markdown": "# Answer"})
        mock_tool_call = MagicMock()
        mock_tool_call.function.arguments = mock_args
        mock_message = MagicMock()
        mock_message.tool_calls = [mock_tool_call]
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        provider = OpenRouterProvider(api_key="test-key")
        provider.complete(
            messages=[],
            tools=[ANSWER_TOOL],
            temperature=0.2,
            max_tokens=500,
        )

        call_kwargs = mock_client.chat.completions.create.call_args
        self.assertEqual(call_kwargs.kwargs['temperature'], 0.2)
        self.assertEqual(call_kwargs.kwargs['max_tokens'], 500)


if __name__ == '__main__':
    unittest.main()
