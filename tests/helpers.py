import shutil
import tempfile
import unittest
from pathlib import Path

from core.config import SAMPLE_PROJECT
from core.security import Workspace
from tools import copy_project


class SandboxTestCase(unittest.TestCase):
    """Gives every test a fresh sandbox copy of the sample project."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aicoder_test_")
        copy_project(SAMPLE_PROJECT, self.tmp)
        self.ws = Workspace(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def path(self, rel: str) -> Path:
        return Path(self.tmp) / rel
