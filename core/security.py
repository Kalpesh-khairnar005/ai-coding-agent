"""Workspace boundary. Every path the agent touches goes through Workspace.resolve()."""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from core.errors import SecurityError, ToolError

IGNORED_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache",
    ".mypy_cache", ".idea", ".vscode", "dist", "build", ".tox",
}
ALLOWED_EXTENSIONS = {".py", ".pyi", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".der", ".keystore", ".crt")
SENSITIVE_NAMES = {".netrc", ".npmrc", ".pypirc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}
MAX_FILE_BYTES = 200_000


def is_sensitive(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.startswith(".env")
        or lowered in SENSITIVE_NAMES
        or lowered.endswith(SENSITIVE_SUFFIXES)
        or "secret" in lowered
        or "credential" in lowered
    )


class Workspace:
    """A directory the agent is allowed to read and write. Nothing outside it is reachable."""

    def __init__(self, root: str | Path):
        path = Path(root).expanduser()
        if not path.is_dir():
            raise ToolError(f"Invalid project: '{root}' does not exist or is not a directory.")
        self.root = path.resolve()

    def resolve(self, rel_path: str) -> Path:
        """Validate a workspace-relative path and return its absolute, symlink-resolved form."""
        if not isinstance(rel_path, str) or not rel_path.strip():
            raise SecurityError("Path must be a non-empty string.")
        if "\x00" in rel_path:
            raise SecurityError("Path contains a null byte.")
        normalized = rel_path.strip().replace("\\", "/")
        if normalized.startswith("/") or normalized.startswith("~") or re.match(r"^[A-Za-z]:", normalized):
            raise SecurityError(f"Absolute paths are not allowed: '{rel_path}'.")
        parts = PurePosixPath(normalized).parts
        if ".." in parts:
            raise SecurityError(f"Path traversal is not allowed: '{rel_path}'.")

        candidate = self.root.joinpath(*parts).resolve()  # resolves symlinks
        try:
            relative = candidate.relative_to(self.root)
        except ValueError:
            raise SecurityError(f"'{rel_path}' resolves outside the workspace.") from None

        if not relative.parts:
            raise SecurityError("Path must point to a file, not the workspace root.")
        if any(part in IGNORED_DIRS for part in relative.parts):
            raise SecurityError(f"Access to '{rel_path}' is blocked (ignored/system directory).")
        if is_sensitive(candidate.name):
            raise SecurityError(f"Access to '{candidate.name}' is blocked (sensitive file).")
        if candidate.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise SecurityError(f"Unsupported file type '{candidate.suffix or candidate.name}'.")
        return candidate

    def relpath(self, absolute: Path) -> str:
        return absolute.resolve().relative_to(self.root).as_posix()
