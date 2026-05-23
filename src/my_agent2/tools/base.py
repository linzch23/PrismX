from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
    }


def _cast(value: Any, schema: dict[str, Any]) -> Any:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), None)

    if value is None:
        return None
    if schema_type == "integer" and isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return value
    if schema_type == "number" and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    if schema_type == "boolean" and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    if schema_type == "array" and isinstance(value, list):
        return [_cast(item, schema.get("items", {})) for item in value]
    if schema_type == "object" and isinstance(value, dict):
        props = schema.get("properties", {})
        return {key: _cast(item, props[key]) if key in props else item for key, item in value.items()}
    return value


def _validate(value: Any, schema: dict[str, Any], path: str = "value") -> None:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        if value is None and "null" in schema_type:
            return
        schema_type = next((item for item in schema_type if item != "null"), None)

    if value is None:
        if schema_type is not None:
            raise ValueError(f"{path} must not be null")
        return

    expected = TYPE_MAP.get(schema_type)
    if expected and not isinstance(value, expected):
        raise ValueError(f"{path} expected {schema_type}, got {type(value).__name__}")

    if schema_type == "string":
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path} must be one of {schema['enum']}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ValueError(f"{path} length must be >= {schema['minLength']}")
    elif schema_type == "array":
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            _validate(item, item_schema, f"{path}[{index}]")
    elif schema_type == "object":
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path} missing required field {key!r}")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                _validate(item, props[key], f"{path}.{key}")


class Tool(ABC):
    read_only = False
    exclusive = False

    @property
    def concurrency_safe(self) -> bool:
        return self.read_only and not self.exclusive

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        raise NotImplementedError

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return _cast(params, self.parameters)

    def validate_params(self, params: dict[str, Any]) -> None:
        _validate(params, self.parameters)

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        raise NotImplementedError
