"""
Adapter: Google Discovery Document -> the minimal OpenAPI-3 shape
transpile_endpoints() already consumes.

Why an adapter instead of a second transpiler: Discovery Documents
describe the same kind of thing OpenAPI does (method, path, params,
request/response schema) in a different shape (`resources`/`methods`
instead of `paths`; `$ref` values are bare schema-id strings like
"Draft" instead of local JSON pointers like "#/components/schemas/
Draft" — confirmed against _resolve_ref(), which only understands the
latter). Translating into the shape transpile_endpoints() already
reads means every downstream piece — patch application, resource_hint/
collision handling, metadata.fields generation, node overrides — gets
reused unchanged instead of duplicated for a second format.

Grounded against a real fetch of Gmail's discovery document
(github.com/googleapis/google-api-python-client, discovery_cache/
documents/gmail.v1.json) rather than the field guide alone:
  - resources nest arbitrarily deep (gmail's own "users" resource has
    nested "resources": {"drafts": {...}, "history": {...}, ...}), so
    the walk below must recurse, not assume one flat level.
  - a resource can have BOTH "methods" and nested "resources" on it at
    once (gmail's "users" does exactly this: its own methods like
    getProfile/watch/stop sit alongside a "resources" key).
  - method "id" (e.g. "gmail.users.drafts.create") is Discovery's
    operationId equivalent — passed through as-is; NOT used for
    schema_name identity, same reasoning _identity_for_operation's own
    docstring already gives for skipping operationId there.
  - "path" is relative (no leading slash, e.g. "gmail/v1/users/{userId}
    /drafts") — normalized to a leading "/" to match OpenAPI's
    convention, since _identity_for_operation and the rest of
    transpile_endpoints assume that.
  - parameters carry "location" (path/query), not OpenAPI's "in" key —
    translated 1:1 (Discovery has no "header"/"cookie" locations to
    worry about).
  - request/response bodies are {"$ref": "<bare schema id>"} against a
    top-level "schemas" dict — rewritten to OpenAPI's
    "#/components/schemas/<id>" pointer form and the schemas dict
    copied into spec["components"]["schemas"], so _deref()/_resolve_ref()
    resolve them with zero changes to converter.py itself.
"""
from __future__ import annotations

from typing import Any, Dict


def discovery_doc_to_openapi_shape(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert one Google Discovery Document (already fetched/parsed JSON)
    into the OpenAPI-3-shaped dict transpile_endpoints() expects:
    {"paths": {path: {method: {operationId, parameters, requestBody}}},
     "components": {"schemas": {...}}}.

    Returns an empty "paths" dict (not an exception) for a malformed or
    unexpected document — same "don't guess wrong, let the caller's
    existing empty-paths handling take over" behavior transpile_endpoints
    already has for a spec with no paths at all.
    """
    schemas = doc.get("schemas", {}) or {}
    root_url = (doc.get("rootUrl", "") or "").rstrip("/")
    service_path = (doc.get("servicePath", "") or "").strip("/")
    # base_url must NOT have a trailing slash — transpile_endpoints does
    # f"{base_url}{path}" (converter.py line ~1640) and every path here
    # already starts with "/", so a trailing slash here means a "//" bug
    # in every generated url (caught by actually running this against
    # transpile_endpoints — the first version of this adapter had it).
    base_url = f"{root_url}/{service_path}" if service_path else root_url
    paths: Dict[str, Any] = {}

    def _rewrite_refs_deep(node: Any) -> Any:
        """Discovery's {"$ref": "Draft"} -> OpenAPI's
        {"$ref": "#/components/schemas/Draft"}, applied recursively
        through the WHOLE structure — not just the outermost node.
        Needed because _deref_schema_tree() (converter.py) resolves
        $refs nested inside 'properties' too (e.g. Draft.message ->
        Message), so a schema's own nested refs need rewriting up
        front, not just the top-level request/response ref."""
        if isinstance(node, dict):
            out = {k: _rewrite_refs_deep(v) for k, v in node.items()}
            if "$ref" in out and not str(out["$ref"]).startswith("#/"):
                out["$ref"] = f"#/components/schemas/{out['$ref']}"
            return out
        if isinstance(node, list):
            return [_rewrite_refs_deep(v) for v in node]
        return node

    schemas = _rewrite_refs_deep(schemas)

    def _param_to_openapi(name: str, p: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": name,
            "in": p.get("location", "query"),
            "required": bool(p.get("required", False)),
            "description": p.get("description", ""),
            "schema": {
                "type": p.get("type", "string"),
                **({"default": p["default"]} if "default" in p else {}),
            },
        }

    def _walk(resources: Dict[str, Any]) -> None:
        for _res_name, res in (resources or {}).items():
            for _method_name, op in (res.get("methods", {}) or {}).items():
                raw_path = op.get("path") or op.get("flatPath") or ""
                path = "/" + raw_path.lstrip("/")
                http_method = (op.get("httpMethod") or "GET").lower()

                parameters = [
                    _param_to_openapi(pname, p)
                    for pname, p in (op.get("parameters", {}) or {}).items()
                ]

                operation: Dict[str, Any] = {
                    "operationId": op.get("id"),
                    "summary": (op.get("description") or "")[:120],
                    "description": op.get("description", ""),
                    "parameters": parameters,
                }

                request_ref = op.get("request")
                if request_ref:
                    operation["requestBody"] = {
                        "content": {
                            "application/json": {"schema": _rewrite_refs_deep(request_ref)}
                        }
                    }

                paths.setdefault(path, {})[http_method] = operation

            if res.get("resources"):
                _walk(res["resources"])

    _walk(doc.get("resources", {}))

    return {
        "openapi": "3.0.0",
        "info": {
            "title": doc.get("canonicalName") or doc.get("name", ""),
            "description": doc.get("description", ""),
        },
        "servers": [{"url": base_url}],
        "paths": paths,
        "components": {"schemas": schemas},
    }