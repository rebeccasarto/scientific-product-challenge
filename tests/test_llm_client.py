"""Tests for structured OpenRouter calls without network access."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Tuple
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from agents import llm_client


class ExampleResponse(BaseModel):
    answer: str
    score: int


def _response(content: str) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )


@pytest.fixture
def mocked_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Tuple[MagicMock, Path]:
    client = MagicMock()
    constructor = MagicMock(return_value=client)
    log_path = tmp_path / "logs" / "llm_calls.jsonl"
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.invalid/v1")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setattr(llm_client, "OpenAI", constructor)
    monkeypatch.setattr(llm_client, "LOG_PATH", log_path)
    return client, log_path


def test_valid_json_succeeds_on_first_attempt(
    mocked_client: Tuple[MagicMock, Path],
) -> None:
    client, log_path = mocked_client
    client.chat.completions.create.return_value = _response(
        '{"answer": "ready", "score": 7}'
    )

    result = llm_client.call_structured(
        "System instructions",
        "Original user content",
        ExampleResponse,
        run_id="run-1",
        agent_name="planner",
    )

    assert result == ExampleResponse(answer="ready", score=7)
    assert client.chat.completions.create.call_count == 1
    log_record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert log_record["success"] is True
    assert log_record["prompt_tokens"] == 10


def test_malformed_json_retries_with_one_fresh_correction(
    mocked_client: Tuple[MagicMock, Path],
) -> None:
    client, _ = mocked_client
    client.chat.completions.create.side_effect = [
        _response("not-json"),
        _response('{"answer": "corrected", "score": 9}'),
    ]

    result = llm_client.call_structured(
        "Original system prompt",
        "Original user content",
        ExampleResponse,
        max_attempts=2,
    )

    assert result.answer == "corrected"
    retry_messages = client.chat.completions.create.call_args_list[1].kwargs[
        "messages"
    ]
    assert retry_messages[0]["content"].startswith("Original system prompt")
    assert retry_messages[1] == {
        "role": "user",
        "content": "Original user content",
    }
    correction_messages: List[str] = [
        message["content"]
        for message in retry_messages
        if message["content"].startswith("Your previous response failed validation")
    ]
    assert len(correction_messages) == 1
    assert "Expecting value" in correction_messages[0]


def test_exhausting_attempts_raises_runtime_error(
    mocked_client: Tuple[MagicMock, Path],
) -> None:
    client, _ = mocked_client
    client.chat.completions.create.side_effect = [
        _response("not-json"),
        _response('{"answer": "missing score"}'),
    ]

    with pytest.raises(RuntimeError) as error:
        llm_client.call_structured(
            "System",
            "User",
            ExampleResponse,
            max_attempts=2,
            run_id="run-failed",
            agent_name="reviewer",
        )

    assert "reviewer" in str(error.value)
    assert "run-failed" in str(error.value)
    assert client.chat.completions.create.call_count == 2


def test_json_schema_instruction_is_embedded(
    mocked_client: Tuple[MagicMock, Path],
) -> None:
    client, _ = mocked_client
    client.chat.completions.create.return_value = _response(
        '{"answer": "schema present", "score": 1}'
    )

    llm_client.call_structured("System", "User", ExampleResponse)

    messages = client.chat.completions.create.call_args.kwargs["messages"]
    system_message = messages[0]["content"]
    assert "Return ONLY valid JSON" in system_message
    assert "JSON schema" in system_message
    assert '"answer"' in system_message
    assert '"score"' in system_message
