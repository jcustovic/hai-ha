"""The pinned copy of the container's chat contract is complete and matches the client."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

CONTRACT = Path(__file__).resolve().parents[1] / "contract" / "chat-api"


def test_the_pinned_files_are_there_and_are_valid_schemas() -> None:
    names = sorted(p.name for p in CONTRACT.iterdir())
    assert names == ["README.md", "chat_request.schema.json", "chat_response.schema.json"]
    for name in names[1:]:
        jsonschema.Draft202012Validator.check_schema(json.loads((CONTRACT / name).read_text()))


def test_the_request_the_client_builds_uses_only_fields_the_contract_defines() -> None:
    schema = json.loads((CONTRACT / "chat_request.schema.json").read_text())
    assert {"session_id", "text", "language", "source"} <= set(schema["properties"])
    assert "ha" in schema["properties"]["source"]["enum"]
