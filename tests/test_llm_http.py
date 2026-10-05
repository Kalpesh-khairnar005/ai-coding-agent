"""Drives the REAL OpenAICompatibleClient over HTTP against a local fake /chat/completions server.

No API key or network is needed, yet this exercises the same code path a real provider uses:
auth header, JSON mode, response parsing, and a complete agent run on top of it.
"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from agent.graph import run_agent
from agent.mock_llm import MockLLM
from agent.prompts import STAGES
from core.config import DEMO_TASK, load_settings
from core.llm import OpenAICompatibleClient
from tests.helpers import SandboxTestCase

SEEN: dict = {"auth": [], "response_format": []}


class FakeProvider(BaseHTTPRequestHandler):
    brain = MockLLM()

    def do_POST(self):  # noqa: N802 (http.server API)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN["auth"].append(self.headers.get("Authorization"))
        SEEN["response_format"].append(body.get("response_format"))
        system, payload = body["messages"][0]["content"], json.loads(body["messages"][1]["content"])
        stage = next(name for name, text in STAGES.items() if text in system)
        reply = json.dumps({"choices": [{"message": {"content": json.dumps(self.brain.complete_json(stage, system, payload))}}]})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(reply.encode())

    def log_message(self, *args):  # keep test output quiet
        pass


class RealClientEndToEndTests(SandboxTestCase):
    def test_full_agent_run_through_http_client(self):
        server = HTTPServer(("127.0.0.1", 0), FakeProvider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        client = OpenAICompatibleClient("sk-fake-test-key-123456", "fake-model", f"http://127.0.0.1:{server.server_port}/v1", timeout=10)

        state = run_agent(DEMO_TASK, self.ws, client, load_settings())

        self.assertEqual(state.status, "success", state.errors)
        self.assertEqual(state.test_runs[-1]["passed"], 8)
        self.assertTrue(all(a == "Bearer sk-fake-test-key-123456" for a in SEEN["auth"]))
        self.assertEqual(SEEN["response_format"][0], {"type": "json_object"})
        self.assertGreaterEqual(len(SEEN["auth"]), 8)  # analyze + explore loop + select + plan + changes + summary


if __name__ == "__main__":
    unittest.main()
