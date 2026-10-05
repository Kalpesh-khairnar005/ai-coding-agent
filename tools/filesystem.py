"""File tools: list_files, read_file, write_file, plus a safe project copier."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.errors import SecurityError, ToolError
from core.logging import get_logger
from core.security import ALLOWED_EXTENSIONS, IGNORED_DIRS, MAX_FILE_BYTES, Workspace, is_sensitive

log = get_logger("tools.fs")


def list_files(ws: Workspace, max_files: int = 300) -> list[dict]:
    """Recursively list readable source files as [{'path', 'size'}], skipping noise and secrets."""
    found: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(ws.root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            if (
                full.is_symlink()
                or full.suffix.lower() not in ALLOWED_EXTENSIONS
                or is_sensitive(name)
            ):
                continue
            size = full.stat().st_size
            if size > MAX_FILE_BYTES:
                continue
            found.append({"path": ws.relpath(full), "size": size})
            if len(found) >= max_files:
                return found
    return found


def read_file(ws: Workspace, path: str, max_chars: int = 20_000) -> str:
    target = ws.resolve(path)
    if not target.is_file():
        raise ToolError(f"File not found: '{path}'.")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"'{path}' is not a UTF-8 text file.") from None
    except PermissionError:
        raise ToolError(f"Permission denied reading '{path}'.") from None
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [truncated]"
    log.debug("read_file %s (%d chars)", path, len(text))
    return text


def write_file(ws: Workspace, path: str, content: str) -> None:
    target = ws.resolve(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except PermissionError:
        raise ToolError(f"Permission denied writing '{path}'.") from None
    log.info("write_file %s (%d chars)", path, len(content))


def copy_project(src: str | Path, dst: str | Path, max_files: int = 500, max_bytes: int = 5_000_000) -> int:
    """Copy source files from src into an isolated sandbox directory. The original is never modified."""
    source = Path(src).expanduser()
    if not source.is_dir():
        raise ToolError(f"Invalid project: '{src}' does not exist or is not a directory.")
    source = source.resolve()
    count = total = 0
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in filenames:
            full = Path(dirpath) / name
            if full.is_symlink() or full.suffix.lower() not in ALLOWED_EXTENSIONS or is_sensitive(name):
                continue
            size = full.stat().st_size
            count, total = count + 1, total + size
            if count > max_files or total > max_bytes:
                raise ToolError("Project is too large for the sandbox (limit: 500 files / 5 MB).")
            target = Path(dst) / full.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(full, target)
    if count == 0:
        raise SecurityError("No supported source files found in the project.")
    return count
