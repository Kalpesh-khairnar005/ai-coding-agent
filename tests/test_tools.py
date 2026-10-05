import unittest

from core.errors import PatchError, ToolError
from tests.helpers import SandboxTestCase
from tools import apply_patch, generate_diff, list_files, read_file, run_tests, search_code, write_file


class FileToolTests(SandboxTestCase):
    def test_list_files_finds_sources_and_skips_noise(self):
        self.path("app/__pycache__").mkdir()
        (self.path("app/__pycache__") / "x.py").write_text("x = 1")
        (self.path(".env")).write_text("KEY=1")
        paths = {f["path"] for f in list_files(self.ws)}
        self.assertIn("app/models.py", paths)
        self.assertIn("tests/test_api.py", paths)
        self.assertNotIn(".env", paths)
        self.assertFalse(any("__pycache__" in p for p in paths))

    def test_read_file_and_missing_file(self):
        self.assertIn("class UserCreate", read_file(self.ws, "app/models.py"))
        with self.assertRaises(ToolError):
            read_file(self.ws, "app/nope.py")

    def test_read_file_truncates_large_content(self):
        write_file(self.ws, "big.txt", "x" * 500)
        self.assertIn("[truncated]", read_file(self.ws, "big.txt", max_chars=100))

    def test_search_code(self):
        hits = search_code(self.ws, "ValidationError")
        self.assertTrue(any(h["path"] == "app/models.py" for h in hits))
        self.assertEqual(search_code(self.ws, "zzz_not_present"), [])
        with self.assertRaises(ToolError):
            search_code(self.ws, "  ")


class PatchAndDiffTests(SandboxTestCase):
    def test_apply_patch_and_diff(self):
        originals = {}
        apply_patch(self.ws, "app/models.py", edits=[{"search": "class User:", "replace": "class User:  # stored"}],
                    originals=originals)
        diff, changed = generate_diff(self.ws, originals)
        self.assertEqual(changed, ["app/models.py"])
        self.assertIn("--- a/app/models.py", diff)
        self.assertIn("+class User:  # stored", diff)

    def test_patch_must_match_exactly_once(self):
        with self.assertRaises(PatchError):
            apply_patch(self.ws, "app/models.py", edits=[{"search": "does not exist", "replace": "x"}])
        with self.assertRaises(PatchError):
            apply_patch(self.ws, "app/models.py", edits=[{"search": "self", "replace": "me"}])  # ambiguous

    def test_invalid_python_is_rejected_and_file_untouched(self):
        before = read_file(self.ws, "app/models.py")
        with self.assertRaises(PatchError):
            apply_patch(self.ws, "app/models.py", edits=[{"search": "class User:", "replace": "class User(:"}])
        self.assertEqual(read_file(self.ws, "app/models.py"), before)

    def test_cannot_overwrite_existing_file_wholesale(self):
        with self.assertRaises(PatchError):
            apply_patch(self.ws, "app/models.py", new_content="x = 1\n")

    def test_new_file_is_created_and_shown_as_new(self):
        originals = {}
        apply_patch(self.ws, "tests/test_new.py", new_content="def test_x():\n    assert True\n", originals=originals)
        diff, changed = generate_diff(self.ws, originals)
        self.assertEqual(changed, ["tests/test_new.py"])
        self.assertIn("--- /dev/null", diff)


class UnsafeCodeGuardTests(SandboxTestCase):
    def test_dangerous_code_is_blocked_and_nothing_is_written(self):
        cases = ["import subprocess\n", "import os\nos.system('id')\n", "eval('1+1')\n", "from urllib.request import urlopen\n",
                 "import socket\n", "__import__('os')\n"]
        for code in cases:
            with self.assertRaisesRegex(PatchError, "safety policy", msg=code):
                apply_patch(self.ws, "tests/test_bad.py", new_content=code)
        self.assertFalse(self.path("tests/test_bad.py").exists())

    def test_legitimate_imports_are_allowed(self):
        apply_patch(self.ws, "tests/test_ok.py", new_content="import json, re\nfrom http import HTTPStatus\nfrom urllib.parse import quote\n")
        self.assertTrue(self.path("tests/test_ok.py").exists())


class TestRunnerTests(SandboxTestCase):
    def test_runs_passing_suite(self):
        result = run_tests(self.ws)
        self.assertEqual(result.status, "passed")
        self.assertEqual((result.passed, result.failed), (5, 0))

    def test_reports_failure_honestly(self):
        write_file(self.ws, "tests/test_fail.py",
                   "import unittest\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.assertEqual(1, 2)\n")
        result = run_tests(self.ws)
        self.assertEqual(result.status, "failed")
        self.assertGreaterEqual(result.failed, 1)

    def test_timeout(self):
        write_file(self.ws, "tests/test_slow.py",
                   "import time, unittest\nclass T(unittest.TestCase):\n    def test_slow(self):\n        time.sleep(5)\n")
        self.assertEqual(run_tests(self.ws, timeout=1).status, "timeout")

    def test_secrets_are_not_passed_to_test_process(self):
        import os
        os.environ["LLM_API_KEY"] = "sk-should-not-leak-123456"
        self.addCleanup(os.environ.pop, "LLM_API_KEY", None)
        write_file(self.ws, "tests/test_env.py",
                   "import os, unittest\nclass T(unittest.TestCase):\n    def test_env(self):\n        self.assertNotIn('LLM_API_KEY', os.environ)\n")
        self.assertEqual(run_tests(self.ws).status, "passed")


if __name__ == "__main__":
    unittest.main()
