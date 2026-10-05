"""search_code: case-insensitive substring search across workspace files."""
from __future__ import annotations

from core.errors import ToolError
from core.logging import get_logger
from core.security import Workspace
from tools.filesystem import list_files, read_file

log = get_logger("tools.search")


def search_code(ws: Workspace, query: str, max_results: int = 40) -> list[dict]:
    """Return [{'path', 'line', 'text'}] for lines containing the query."""
    if not isinstance(query, str) or not query.strip():
        raise ToolError("Search query must be a non-empty string.")
    needle = query.strip().lower()
    hits: list[dict] = []
    for entry in list_files(ws):
        try:
            text = read_file(ws, entry["path"], max_chars=200_000)
        except ToolError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                hits.append({"path": entry["path"], "line": number, "text": line.strip()[:200]})
                if len(hits) >= max_results:
                    return hits
    log.info("search_code %r -> %d hits", query, len(hits))
    return hits
