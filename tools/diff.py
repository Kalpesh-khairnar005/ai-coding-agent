"""generate_diff: unified diff between recorded originals and the current workspace."""
from __future__ import annotations

import difflib

from core.errors import ToolError
from core.security import Workspace
from tools.filesystem import read_file


def generate_diff(ws: Workspace, originals: dict) -> tuple[str, list[str]]:
    """Return (unified_diff, changed_files). `originals` maps path -> old text (None for new files)."""
    chunks: list[str] = []
    changed: list[str] = []
    for path in sorted(originals):
        old = originals[path]
        try:
            new = read_file(ws, path, max_chars=10**9)
        except ToolError:
            continue
        if old == new:
            continue
        changed.append(path)
        diff = difflib.unified_diff(
            (old or "").splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile="/dev/null" if old is None else f"a/{path}",
            tofile=f"b/{path}",
        )
        chunks.append("".join(line if line.endswith("\n") else line + "\n" for line in diff))
    return "".join(chunks), changed
