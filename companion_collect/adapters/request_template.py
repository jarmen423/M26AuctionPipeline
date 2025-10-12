"""Request templating helpers for Companion App HTTP calls."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


def _apply_context(value: Any, context: Mapping[str, Any]) -> Any:
    """Recursively apply string formatting using the provided context."""

    if isinstance(value, str):
        return value.format(**context)

    if isinstance(value, Mapping):
        return {key: _apply_context(val, context) for key, val in value.items()}

    if isinstance(value, list):
        return [_apply_context(item, context) for item in value]

    return value


@dataclass(slots=True)
class RequestDefinition:
    """Concrete HTTP request parts for `httpx.AsyncClient.request`."""

    method: str
    url: str
    headers: dict[str, str]
    params: dict[str, Any] | None
    json_body: Any | None
    data: Any | None


@dataclass(slots=True)
class RequestTemplate:
    """Load and render Companion App request definitions from disk."""

    method: str
    url: str
    headers: dict[str, str]
    params: dict[str, Any] | None
    json_body: Any | None
    data: Any | None

    @classmethod
    def from_path(cls, path: str | Path) -> "RequestTemplate":
        template_path = Path(path)
        content = json.loads(template_path.read_text(encoding="utf-8"))
        return cls(
            method=content.get("method", "POST"),
            url=content["url"],
            headers=content.get("headers", {}),
            params=content.get("params"),
            json_body=content.get("json"),
            data=content.get("data"),
        )

    def render(self, *, context: Mapping[str, Any] | None = None) -> RequestDefinition:
        context = context or {}

        return RequestDefinition(
            method=self.method,
            url=_apply_context(self.url, context),
            headers={k: _apply_context(v, context) for k, v in self.headers.items()},
            params=_apply_context(self.params, context) if self.params else None,
            json_body=_apply_context(self.json_body, context) if self.json_body else None,
            data=_apply_context(self.data, context) if self.data else None,
        )
