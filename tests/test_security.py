import os
import unittest

from core.errors import SecurityError, ToolError
from core.logging import RedactingFilter
from core.security import Workspace
from tests.helpers import SandboxTestCase
from tools import read_file, write_file


class WorkspaceSecurityTests(SandboxTestCase):
    def test_rejects_parent_traversal(self):
        for bad in ("../secret.py", "app/../../x.py", "..\\x.py"):
            with self.assertRaises(SecurityError, msg=bad):
                self.ws.resolve(bad)

    def test_rejects_absolute_paths(self):
        for bad in ("/etc/passwd", "C:\\Windows\\system.ini", "~/x.py"):
            with self.assertRaises(SecurityError, msg=bad):
                self.ws.resolve(bad)

    def test_rejects_sensitive_files(self):
        for bad in (".env", ".env.local", "server.pem", "id_rsa", "credentials.json", "app/secrets.py"):
            with self.assertRaises(SecurityError, msg=bad):
                self.ws.resolve(bad)

    def test_rejects_ignored_dirs_and_unsupported_types(self):
        with self.assertRaises(SecurityError):
            self.ws.resolve(".git/config.txt")
        with self.assertRaises(SecurityError):
            self.ws.resolve("app/tool.exe")

    def test_rejects_symlink_escape(self):
        outside = os.path.join(os.path.dirname(self.tmp), "outside_target.txt")
        with open(outside, "w") as fh:
            fh.write("top secret")
        self.addCleanup(os.remove, outside)
        os.symlink(outside, self.path("app/link.txt"))
        with self.assertRaises(SecurityError):
            read_file(self.ws, "app/link.txt")

    def test_write_outside_workspace_is_blocked(self):
        with self.assertRaises(SecurityError):
            write_file(self.ws, "../evil.py", "print('x')")
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.tmp), "evil.py")))

    def test_valid_path_is_allowed(self):
        self.assertTrue(str(self.ws.resolve("app/models.py")).endswith("models.py"))

    def test_invalid_workspace_root(self):
        with self.assertRaises(ToolError):
            Workspace("/definitely/not/a/real/dir")


class LogRedactionTests(unittest.TestCase):
    def test_api_keys_are_masked(self):
        import logging
        record = logging.LogRecord("x", logging.INFO, "", 0, "key=sk-abcdef123456789 Bearer abc.def", (), None)
        RedactingFilter().filter(record)
        self.assertNotIn("sk-abcdef", record.msg)
        self.assertNotIn("abc.def", record.msg)


if __name__ == "__main__":
    unittest.main()
