from __future__ import annotations

import hashlib
import re

# Heuristics: test infrastructure / syntax failures (not valid Red).
RUNNER_FAILURE_PATTERNS = [
    r"SyntaxError",
    r"IndentationError",
    r"ModuleNotFoundError:\s+No module named 'pytest'",
    r"command not found",
    r"No such file or directory",
    r"ERROR: file or directory not found",
    r"ImportError while importing test module",
    r"pytest:\s+error:",
]


def is_runner_or_syntax_failure(log_tail: str) -> bool:
    for pat in RUNNER_FAILURE_PATTERNS:
        if re.search(pat, log_tail, re.IGNORECASE):
            return True
    return False


def normalize_error_tail(text: str) -> str:
    text = text[-3000:]
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*", "<TS>", text)
    text = re.sub(r"\bpids?\s*=\s*\d+", "pid=<N>", text, flags=re.I)
    text = re.sub(r"\bpid\s+\d+", "pid <N>", text, flags=re.I)
    text = re.sub(r"\b0x[0-9a-fA-F]+", "0xADDR", text)
    text = re.sub(r"/tmp/[^\s]+", "/tmp/<TMP>", text)
    return text


def error_hash(text: str) -> str:
    return hashlib.md5(normalize_error_tail(text).encode("utf-8")).hexdigest()
