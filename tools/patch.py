"""apply_patch: exact search/replace edits, validated before anything is written."""
from __future__ import annotations

import ast

from core.errors import PatchError
from core.logging import get_logger
from core.security import Workspace
from tools.filesystem import read_file, write_file

log = get_logger("tools.patch")

# Generated code is executed by run_tests, so reject constructs that reach outside the project.
FORBIDDEN_MODULES = {
    "subprocess", "socket", "ctypes", "multiprocessing", "pty", "shutil", "requests", "httpx", "aiohttp",
    "urllib.request", "http.client", "http.server", "ftplib", "smtplib", "telnetlib",
}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}
FORBIDDEN_ATTR_CALLS = {"system", "popen", "spawn", "execv", "execve", "fork", "rmtree", "kill"}


def find_unsafe_code(tree: ast.AST) -> str | None:
    """Return a description of the first dangerous construct, or None if the code looks safe."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            names = []
        for name in names:
            if any(name == m or name.startswith(m + ".") for m in FORBIDDEN_MODULES):
                return f"import of '{name}' (line {node.lineno})"
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                return f"call to {func.id}() (line {node.lineno})"
            if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_ATTR_CALLS:
                return f"call to .{func.attr}() (line {node.lineno})"
    return None


def plan_patch(original: str | None, edits: list[dict] | None, new_content: str | None, path: str) -> str:
    """Compute the patched text without touching disk. Raises PatchError if invalid."""
    if new_content is not None:
        if original is not None:
            raise PatchError(f"'{path}' already exists; use targeted edits instead of rewriting the whole file.")
        text = new_content
    else:
        if original is None:
            raise PatchError(f"'{path}' does not exist; provide new_content to create it.")
        if not edits or not isinstance(edits, list):
            raise PatchError(f"No edits supplied for '{path}'.")
        text = original
        for index, edit in enumerate(edits, start=1):
            search, replace = edit.get("search"), edit.get("replace")
            if not isinstance(search, str) or not search or not isinstance(replace, str):
                raise PatchError(f"Edit {index} for '{path}' needs non-empty 'search' and a 'replace' string.")
            matches = text.count(search)
            if matches != 1:
                raise PatchError(
                    f"Edit {index} for '{path}': the search text matched {matches} times (must match exactly once)."
                )
            text = text.replace(search, replace, 1)
    if path.endswith(".py"):
        try:
            tree = ast.parse(text, path)
        except SyntaxError as exc:
            raise PatchError(f"Patch for '{path}' produces invalid Python (line {exc.lineno}: {exc.msg}).") from None
        unsafe = find_unsafe_code(tree)
        if unsafe:
            raise PatchError(f"Patch for '{path}' rejected by the safety policy: {unsafe}.")
    return text


def apply_patch(
    ws: Workspace,
    path: str,
    edits: list[dict] | None = None,
    new_content: str | None = None,
    originals: dict | None = None,
) -> None:
    """Validate then write a patch. Records the pre-change content in `originals` (None = new file)."""
    target = ws.resolve(path)
    original: str | None = None
    if target.is_file():
        original = read_file(ws, path, max_chars=10**9)
    patched = plan_patch(original, edits, new_content, path)
    if originals is not None and path not in originals:
        originals[path] = original
    write_file(ws, path, patched)
    log.info("apply_patch %s (%d edits, new_file=%s)", path, len(edits or []), original is None)
