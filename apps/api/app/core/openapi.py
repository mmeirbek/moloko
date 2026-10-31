"""OpenAPI tweaks so the published schema matches what the API really returns."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.schemas.errors import ErrorResponse

_FASTAPI_ERROR_REF = "#/components/schemas/HTTPValidationError"
_OUR_ERROR_REF = "#/components/schemas/ErrorResponse"


def _replace_refs(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: (_OUR_ERROR_REF if k == "$ref" and v == _FASTAPI_ERROR_REF else _replace_refs(v))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_replace_refs(v) for v in node]
    return node


def install_openapi(app: FastAPI) -> None:
    def build() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components.pop("HTTPValidationError", None)
        components.pop("ValidationError", None)
        error_schema = ErrorResponse.model_json_schema(ref_template="#/components/schemas/{model}")
        components.update(error_schema.pop("$defs", {}))
        components["ErrorResponse"] = error_schema
        patched: dict[str, Any] = _replace_refs(schema)
        app.openapi_schema = patched
        return patched

    app.openapi = build  # type: ignore[method-assign]
