"""Shared assertions for HTTP request/response contract validation."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def assert_model(data: Any, model: type[T]) -> T:
    """Validate a dict/object matches a Pydantic model (types + constraints)."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise AssertionError(f"Response does not match {model.__name__}: {exc}") from exc


def assert_model_list(data: Any, model: type[T]) -> list[T]:
    """Validate a JSON list where every item matches the model."""
    assert isinstance(data, list), f"Expected list, got {type(data)!r}"
    return [assert_model(item, model) for item in data]


def assert_json_response(response_json: Any, model: type[T]) -> T:
    """Alias for endpoint tests operating on already-parsed JSON."""
    return assert_model(response_json, model)


def assert_json_response_list(response_json: Any, model: type[T]) -> list[T]:
    return assert_model_list(response_json, model)


def assert_http_call_json(
    session_mock: Any,
    *,
    method: str = "post",
    call_index: int = -1,
    expected: dict[str, Any] | None = None,
    contains: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract and optionally assert fields on an HTTP mock's json= payload."""
    call = getattr(session_mock, method).call_args_list[call_index]
    payload = call.kwargs.get("json")
    assert payload is not None, f"Expected json= on {method} call {call_index}"
    assert isinstance(payload, dict), f"Expected dict json payload, got {type(payload)!r}"
    if expected is not None:
        for key, value in expected.items():
            assert payload.get(key) == value, f"{key}: expected {value!r}, got {payload.get(key)!r}"
    if contains is not None:
        for key, fragment in contains.items():
            assert key in payload, f"Missing key {key!r} in request payload"
            if isinstance(fragment, dict):
                assert isinstance(payload[key], dict), f"{key} should be dict"
                for sub_key, sub_value in fragment.items():
                    assert payload[key].get(sub_key) == sub_value, (
                        f"{key}.{sub_key}: expected {sub_value!r}, got {payload[key].get(sub_key)!r}"
                    )
            else:
                assert payload[key] == fragment, f"{key}: expected {fragment!r}, got {payload[key]!r}"
    return payload
