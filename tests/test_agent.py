import unittest
from unittest import mock

import requests

from agent.graph import run_agent
from agent.mock_llm import MockLLM
from core.config import DEMO_TASK, Settings, load_settings
from core.errors import LLMError
from core.llm import OpenAICompatibleClient, parse_json_object
from tests.helpers import SandboxTestCase


class DemoWorkflowTests(SandboxTestCase):
    def test_demo_task_end_to_end(self):
        state = run_agent(DEMO_TASK, self.ws, MockLLM(), load_settings())
        self.assertEqual(state.status, "success", state.errors)
        self.assertEqual(state.test_status, "passed")
        self.assertEqual(state.files_changed, ["app/models.py", "tests/test_api.py"])
        self.assertIn("+        if self.age < 0:", state.diff)
        paths = [r["path"] for r in state.relevant_files]
        self.assertIn("app/models.py", paths)
        self.assertIn("tests/test_api.py", paths)
        self.assertTrue(all(r["reason"] for r in state.relevant_files))
        self.assertGreaterEqual(len(state.plan), 3)
        self.assertEqual(state.test_runs[-1]["passed"], 8)  # 5 original + 3 new tests, really executed
        self.assertTrue(all(s["status"] == "done" for s in state.stages))

    def test_files_really_modified_on_disk(self):
        run_agent(DEMO_TASK, self.ws, MockLLM(), load_settings())
        self.assertIn("self.age < 0", self.path("app/models.py").read_text())

    def test_empty_task_is_rejected_without_crashing(self):
        state = run_agent("   ", self.ws, MockLLM(), load_settings())
        self.assertEqual(state.status, "error")

    def test_unsupported_task_reports_no_changes_not_success(self):
        state = run_agent("Add pagination to the list endpoint", self.ws, MockLLM(), load_settings())
        self.assertEqual(state.status, "no_changes")
        self.assertEqual(state.files_changed, [])
        self.assertEqual(state.test_runs, [])


class InputValidationDemoTests(SandboxTestCase):
    """The assignment brief's own example prompt must work in offline mode too."""

    def test_brief_example_prompt(self):
        state = run_agent("Add input validation to this API and write a test for it.", self.ws, MockLLM(), load_settings())
        self.assertEqual(state.status, "success", state.errors)
        self.assertEqual(state.files_changed, ["app/models.py", "tests/test_api.py"])
        self.assertEqual(state.test_runs[-1]["passed"], 7)  # 5 original + 2 new
        self.assertIn("test_create_user_rejects_overlong_name", state.summary["tests_added"])


class ScriptedLLM(MockLLM):
    """Wraps the mock but replaces the 'changes' stage, to simulate model behaviour."""

    name = "scripted-test"

    def __init__(self, changes_fn):
        self.changes_fn = changes_fn

    def _changes(self, p):
        return self.changes_fn(p)


class FailurePathTests(SandboxTestCase):
    def test_bad_patch_is_rejected_and_never_claims_success(self):
        llm = ScriptedLLM(lambda p: {"changes": [{"file": "app/models.py", "description": "bad",
                                                 "edits": [{"search": "NOT THERE", "replace": "x"}]}]})
        state = run_agent(DEMO_TASK, self.ws, llm, load_settings())
        self.assertEqual(state.status, "no_changes")
        self.assertEqual(state.changes[0]["status"], "rejected")

    def test_rejected_patch_is_retried_with_feedback_and_recovers(self):
        seen_errors = []

        def changes(p):
            seen_errors.append(p["previous_patch_errors"])
            if p["attempt"] == 0:
                return {"changes": [{"file": "app/models.py", "description": "misquoted",
                                     "edits": [{"search": "THIS TEXT IS NOT IN THE FILE", "replace": "x"}]}]}
            return {"changes": [{"file": "app/models.py", "description": "fixed quote",
                                 "edits": [{"search": "class User:", "replace": "class User:  # stored"}]}]}

        state = run_agent(DEMO_TASK, self.ws, ScriptedLLM(changes), load_settings())
        self.assertEqual(state.status, "success", state.errors)
        self.assertEqual(state.repair_attempts, 1)
        self.assertEqual(seen_errors[0], [])
        self.assertIn("matched 0 times", seen_errors[1][0]["error"])  # the model is told WHY it failed
        self.assertEqual([c["status"] for c in state.changes], ["rejected", "applied"])

    def test_unsafe_generated_code_is_rejected_by_policy(self):
        evil = "import subprocess, unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        subprocess.run(['id'])\n"
        llm = ScriptedLLM(lambda p: {"changes": [{"file": "tests/test_evil.py", "description": "x", "new_content": evil}]})
        state = run_agent(DEMO_TASK, self.ws, llm, load_settings())
        self.assertEqual(state.status, "no_changes")
        self.assertIn("safety policy", state.changes[0]["error"])
        self.assertFalse(self.path("tests/test_evil.py").exists())

    def test_path_traversal_by_llm_is_rejected(self):
        llm = ScriptedLLM(lambda p: {"changes": [{"file": "../evil.py", "description": "x", "new_content": "x = 1\n"}]})
        state = run_agent(DEMO_TASK, self.ws, llm, load_settings())
        self.assertEqual(state.changes[0]["status"], "rejected")
        self.assertIn("traversal", state.changes[0]["error"])

    def test_repair_loop_is_bounded_and_failure_is_reported(self):
        breaking = {"changes": [{"file": "app/models.py", "description": "break it",
                                 "edits": [{"search": "self.name.strip()", "replace": "not self.name.strip()"}]}]}
        calls = {"n": 0}

        def changes(p):
            calls["n"] += 1
            if p["attempt"] == 0:
                return breaking
            # repair attempts: keep making a different (still failing) tweak that always applies cleanly
            n = p["attempt"]
            before = 'must not be empty")' if n == 1 else f'must not be empty {n - 1}")'
            return {"changes": [{"file": "app/models.py", "description": f"retry {n}",
                                 "edits": [{"search": before, "replace": f'must not be empty {n}")'}]}]}

        state = run_agent(DEMO_TASK, self.ws, ScriptedLLM(changes), load_settings())
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.test_status, "failed")
        self.assertEqual(state.repair_attempts, 3)
        self.assertEqual(calls["n"], 4)  # 1 initial + 3 repairs, then stop
        self.assertIn("FAILED", state.summary["validation"])

    def test_repair_loop_can_recover(self):
        def changes(p):
            if p["attempt"] == 0:
                return {"changes": [{"file": "app/models.py", "description": "break",
                                     "edits": [{"search": "self.name.strip()", "replace": "not self.name.strip()"}]}]}
            return {"changes": [{"file": "app/models.py", "description": "fix",
                                 "edits": [{"search": "not self.name.strip()", "replace": "self.name.strip()"}]}]}

        state = run_agent(DEMO_TASK, self.ws, ScriptedLLM(changes), load_settings())
        self.assertEqual(state.status, "success")
        self.assertEqual(state.repair_attempts, 1)

    def test_llm_failure_is_captured(self):
        class Broken(MockLLM):
            def _analyze(self, p):
                raise LLMError("boom")

        state = run_agent(DEMO_TASK, self.ws, Broken(), load_settings())
        self.assertEqual(state.status, "error")
        self.assertIn("boom", state.errors[0])

    def test_malformed_llm_response_is_captured(self):
        class Malformed(MockLLM):
            def _plan(self, p):
                return {"nothing": True}

        state = run_agent(DEMO_TASK, self.ws, Malformed(), load_settings())
        self.assertEqual(state.status, "error")
        self.assertIn("missing required", state.errors[0])


class LLMClientTests(unittest.TestCase):
    def test_missing_key(self):
        with self.assertRaises(LLMError):
            OpenAICompatibleClient("", "m", "http://x")

    def test_parse_json_tolerates_fences(self):
        self.assertEqual(parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})
        with self.assertRaises(ValueError):
            parse_json_object("no json here")

    def _resp(self, status, payload=None, text=""):
        r = mock.Mock(status_code=status, text=text)
        r.json.return_value = payload
        return r

    def test_successful_call_and_malformed_retry(self):
        client = OpenAICompatibleClient("sk-test-key-123456", "m", "http://x")
        good = self._resp(200, {"choices": [{"message": {"content": '{"ok": true}'}}]})
        bad = self._resp(200, {"choices": [{"message": {"content": "garbage"}}]})
        with mock.patch("requests.post", side_effect=[bad, good]):
            self.assertEqual(client.complete_json("analyze", "sys", {}), {"ok": True})
        with mock.patch("requests.post", side_effect=[bad, bad]):
            with self.assertRaises(LLMError):
                client.complete_json("analyze", "sys", {})

    def test_auth_and_network_errors(self):
        client = OpenAICompatibleClient("sk-test-key-123456", "m", "http://x")
        with mock.patch("requests.post", return_value=self._resp(401)):
            with self.assertRaisesRegex(LLMError, "authentication"):
                client.complete_json("analyze", "sys", {})
        with mock.patch("requests.post", side_effect=requests.Timeout()):
            with self.assertRaisesRegex(LLMError, "timed out"):
                client.complete_json("analyze", "sys", {})

    def test_settings_default_without_key(self):
        self.assertFalse(Settings().has_api_key)


if __name__ == "__main__":
    unittest.main()
