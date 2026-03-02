"""Tests for LLM provider request cancellation."""

import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from .. import openrouter
from ..openrouter import OpenRouterProvider


class SlowStreamHandler(BaseHTTPRequestHandler):
    """HTTP handler that streams chunks slowly (simulates slow LLM)."""

    def do_POST(self, *args, **kwargs):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        # Send chunks slowly — 10 chunks, 1 second apart
        for i in range(10):
            time.sleep(1)
            chunk = 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"x"}}]}}]}\n\n'
            self.wfile.write(f"{len(chunk):x}\r\n{chunk}\r\n".encode())
            try:
                self.wfile.flush()
            except BrokenPipeError:
                return

        # Final done chunk
        done = "data: [DONE]\n\n"
        self.wfile.write(f"{len(done):x}\r\n{done}\r\n0\r\n\r\n".encode())
        self.wfile.flush()

    def log_message(self, *args):
        pass


class TestProviderCancel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), SlowStreamHandler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    @patch(f"{openrouter.__name__}.load_dotenv")
    def test_cancel_aborts_inflight_request(self, mock_dotenv):
        """cancel() should abort an in-flight HTTP request within 2 seconds."""
        provider = OpenRouterProvider(
            api_key="test-key",
            base_url=f"http://127.0.0.1:{self.port}/v1",
        )

        result = {"error": None, "elapsed": None}

        def call_complete():
            start = time.time()
            try:
                provider.complete(
                    messages=[{"role": "user", "content": "test"}],
                    tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}],
                )
            except BaseException as e:
                result["error"] = e
            result["elapsed"] = time.time() - start

        t = threading.Thread(target=call_complete)
        t.start()

        # Let the request start and stream begin
        time.sleep(1.5)

        # Cancel should kill it
        provider.cancel()

        t.join(timeout=3)
        self.assertFalse(t.is_alive(), "Thread should be dead after cancel")
        self.assertIsNotNone(result["error"], "Should have raised an error")
        self.assertLess(result["elapsed"], 5.0, "Should abort quickly, not wait for full 10s")

    @patch(f"{openrouter.__name__}.load_dotenv")
    def test_cancel_sets_flag(self, mock_dotenv):
        """cancel() should set the cancelled flag."""
        provider = OpenRouterProvider(
            api_key="test-key",
            base_url=f"http://127.0.0.1:{self.port}/v1",
        )
        self.assertFalse(provider.cancelled)
        provider.cancel()
        self.assertTrue(provider.cancelled)

    @patch(f"{openrouter.__name__}.load_dotenv")
    def test_cancel_is_safe_when_idle(self, mock_dotenv):
        """cancel() should not raise when no request is in flight."""
        provider = OpenRouterProvider(
            api_key="test-key",
            base_url=f"http://127.0.0.1:{self.port}/v1",
        )
        # Should not raise
        provider.cancel()
        provider.cancel()


if __name__ == "__main__":
    unittest.main()
