"""Logging with secret redaction. Secrets are never written to logs."""
from __future__ import annotations

import logging
import os
import re
import sys

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[=:]\s*\S+"),
]
_secrets: set[str] = set()


def register_secret(value: str) -> None:
    """Make sure an exact secret value is masked if it ever reaches a log line."""
    if value and len(value) >= 6:
        _secrets.add(value)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in _secrets:
            message = message.replace(secret, "***")
        for pattern in _PATTERNS:
            message = pattern.sub("***", message)
        record.msg, record.args = message, ()
        return True


def get_logger(name: str = "agent") -> logging.Logger:
    root = logging.getLogger("aicoder")
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(RedactingFilter())
        root.addHandler(handler)
        root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
        root.propagate = False
    return root.getChild(name)
