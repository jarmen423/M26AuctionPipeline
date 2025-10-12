from __future__ import annotations

import json
from pathlib import Path

import pytest

from companion_collect.adapters.request_template import RequestTemplate


@pytest.fixture()
def template_file(tmp_path: Path) -> Path:
    content = {
        "method": "GET",
        "url": "https://example.com/{page}",
        "headers": {"Authorization": "Bearer {token}"},
        "params": {"count": "{count}"},
        "json": {"foo": "{foo}"},
    }
    path = tmp_path / "template.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def test_template_renders_context(template_file: Path) -> None:
    template = RequestTemplate.from_path(template_file)
    rendered = template.render(context={"page": 2, "token": "abc", "count": 25, "foo": "bar"})

    assert rendered.method == "GET"
    assert rendered.url == "https://example.com/2"
    assert rendered.headers == {"Authorization": "Bearer abc"}
    assert rendered.params == {"count": "25"}
    assert rendered.json_body == {"foo": "bar"}
