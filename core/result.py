"""
Общие хелперы для унифицированного формата ответов {status: ok/error}.

Используйте вместо локальных копий _error() / _ok() в каждом модуле.
"""

from __future__ import annotations

from typing import Any


def ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    if data:
        out.update(data)
    return out


def error(message: str) -> dict[str, str]:
    return {"status": "error", "message": message}
