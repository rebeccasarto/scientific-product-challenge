"""Shared structured-output client for OpenRouter-backed analysis agents."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, cast

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = PROJECT_ROOT / "logs" / "llm_calls.jsonl"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"


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


def _client_and_model() -> Tuple[Any, str]:
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    base_url = os.getenv("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL)
    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    return OpenAI(api_key=openrouter_api_key, base_url=base_url), model


def _call_with_retries(
    system_prompt: str,
    user_content: str,
    response_parser: Callable[[str], Any],
    correction_builder: Callable[[str], str],
    failure_kind: str,
    max_attempts: int,
    run_id: str,
    agent_name: str,
) -> Any:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    client, model = _client_and_model()
    last_error = "No response was produced"
    for attempt_number in range(1, max_attempts + 1):
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        if attempt_number > 1:
            messages.append(
                {"role": "user", "content": correction_builder(last_error)}
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
                raise ValueError("Response content was not a string")
            parsed_response = response_parser(response_content)
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
        return parsed_response

    raise RuntimeError(
        f"{failure_kind} LLM call failed for agent_name={agent_name}, "
        f"run_id={run_id} after {max_attempts} attempt(s): {last_error}"
    )


def call_structured(
    system_prompt: str,
    user_content: str,
    response_model: Type[BaseModel],
    max_attempts: int = 2,
    run_id: str = "unknown",
    agent_name: str = "unknown",
) -> BaseModel:
    """Call OpenRouter until valid JSON matching ``response_model`` is returned."""
    schema_json = json.dumps(_model_schema(response_model), indent=2, sort_keys=True)
    schema_instruction = (
        "Return ONLY valid JSON matching the exact JSON schema below. "
        "Do not include markdown code fences, a preamble, or any text outside "
        "the JSON object.\n\nJSON schema:\n"
        f"{schema_json}"
    )
    system_with_schema = f"{system_prompt}\n\n{schema_instruction}"

    def parse_structured(response_content: str) -> BaseModel:
        stripped = response_content.strip()
        if stripped.startswith("```"):
            lines = stripped.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()
        payload = json.loads(stripped)
        return _validate_model(response_model, payload)

    def structured_correction(error_message: str) -> str:
        return (
            "Your previous response failed validation: "
            f"{error_message}. Return ONLY corrected JSON matching the schema above."
        )

    return cast(
        BaseModel,
        _call_with_retries(
            system_prompt=system_with_schema,
            user_content=user_content,
            response_parser=parse_structured,
            correction_builder=structured_correction,
            failure_kind="Structured",
            max_attempts=max_attempts,
            run_id=run_id,
            agent_name=agent_name,
        ),
    )


def call_text(
    system_prompt: str,
    user_content: str,
    max_attempts: int = 2,
    run_id: str = "unknown",
    agent_name: str = "unknown",
) -> str:
    """Call OpenRouter until a non-empty, plausibly complete text response is returned."""

    def parse_text(response_content: str) -> str:
        if len(response_content.strip()) < 20:
            raise ValueError("Text response was empty or shorter than 20 characters")
        return response_content

    def text_correction(error_message: str) -> str:
        return (
            "Your previous response was invalid: "
            f"{error_message}. Return a complete plain-text response."
        )

    return cast(
        str,
        _call_with_retries(
            system_prompt=system_prompt,
            user_content=user_content,
            response_parser=parse_text,
            correction_builder=text_correction,
            failure_kind="Text",
            max_attempts=max_attempts,
            run_id=run_id,
            agent_name=agent_name,
        ),
    )
