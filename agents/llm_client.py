"""Shared structured-output client for OpenRouter-backed analysis agents."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = PROJECT_ROOT / "logs" / "llm_calls.jsonl"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-3.5-haiku"


def _model_schema(response_model: Type[BaseModel]) -> Dict[str, Any]:
    if hasattr(response_model, "model_json_schema"):
        return response_model.model_json_schema()
    return response_model.schema()


def _validate_model(
    response_model: Type[BaseModel],
    payload: Any,
) -> BaseModel:
    if hasattr(response_model, "model_validate"):
        return response_model.model_validate(payload)
    return response_model.parse_obj(payload)


def _short_error(error: Exception) -> str:
    compact_error = " ".join(str(error).split())
    return compact_error[:800]


def _usage_value(usage: Any, field_name: str) -> int:
    if usage is None:
        return 0
    value = getattr(usage, field_name, 0)
    return int(value or 0)


def _log_attempt(
    run_id: str,
    agent_name: str,
    attempt_number: int,
    model: str,
    usage: Any,
    success: bool,
    error_message: Optional[str],
) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "agent_name": agent_name,
        "attempt_number": attempt_number,
        "model": model,
        "prompt_tokens": _usage_value(usage, "prompt_tokens"),
        "completion_tokens": _usage_value(usage, "completion_tokens"),
        "total_tokens": _usage_value(usage, "total_tokens"),
        "success": success,
        "error_message": error_message,
    }
    with LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record) + "\n")


def call_structured(
    system_prompt: str,
    user_content: str,
    response_model: Type[BaseModel],
    max_attempts: int = 2,
    run_id: str = "unknown",
    agent_name: str = "unknown",
) -> BaseModel:
    """Call OpenRouter until valid JSON matching ``response_model`` is returned."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    base_url = os.getenv("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL)
    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    client = OpenAI(api_key=api_key, base_url=base_url)

    schema_json = json.dumps(_model_schema(response_model), indent=2, sort_keys=True)
    schema_instruction = (
        "Return ONLY valid JSON matching the exact JSON schema below. "
        "Do not include markdown code fences, a preamble, or any text outside "
        "the JSON object.\n\nJSON schema:\n"
        f"{schema_json}"
    )
    system_with_schema = f"{system_prompt}\n\n{schema_instruction}"
    last_error = "No response was produced"

    for attempt_number in range(1, max_attempts + 1):
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_with_schema},
            {"role": "user", "content": user_content},
        ]
        if attempt_number > 1:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response failed validation: "
                        f"{last_error}. Return ONLY corrected JSON matching "
                        "the schema above."
                    ),
                }
            )

        usage: Any = None
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
            )
            usage = getattr(response, "usage", None)
            response_content = response.choices[0].message.content
            if not isinstance(response_content, str):
                raise ValueError("Response content was not a JSON string")
            payload = json.loads(response_content)
            validated = _validate_model(response_model, payload)
        except Exception as exc:
            last_error = _short_error(exc)
            _log_attempt(
                run_id=run_id,
                agent_name=agent_name,
                attempt_number=attempt_number,
                model=model,
                usage=usage,
                success=False,
                error_message=last_error,
            )
            continue

        _log_attempt(
            run_id=run_id,
            agent_name=agent_name,
            attempt_number=attempt_number,
            model=model,
            usage=usage,
            success=True,
            error_message=None,
        )
        return validated

    raise RuntimeError(
        f"Structured LLM call failed for agent_name={agent_name}, "
        f"run_id={run_id} after {max_attempts} attempt(s): {last_error}"
    )
