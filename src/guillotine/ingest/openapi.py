from __future__ import annotations

import json
import keyword
import re
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from guillotine.ir import (
    ApiSpec,
    BodyField,
    Operation,
    Parameter,
    ParameterLocation,
    RequestBody,
    Resource,
    SafetyTier,
)

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options"}
RESERVED_RESOURCE_NAMES = {
    "_request",
    "base_url",
    "headers",
    "raw",
    "timeout",
}
RESERVED_RESOURCE_CLASSES = {
    "ApiError",
    "ChoiceError",
    "Client",
    "GuillotineError",
    "HttpTransport",
    "OperationResult",
    "Response",
    "SafetyBlocked",
    "Tier",
}
RESERVED_OPERATION_NAMES = {"raw"}


def load_openapi(path: str | Path, *, package_name: str | None = None) -> ApiSpec:
    """Load an OpenAPI 3 document into Guillotine's Curated Core IR."""
    spec_path = Path(path)
    document = _load_document(spec_path)
    if not isinstance(document, dict):
        raise ValueError(f"{spec_path} did not parse to an OpenAPI object.")

    openapi = str(document.get("openapi", ""))
    if not openapi.startswith("3."):
        raise ValueError(
            f"{spec_path} is not an OpenAPI 3 document. Found openapi={openapi!r}."
        )

    info = document.get("info") or {}
    title = str(info.get("title") or spec_path.stem)
    version = str(info.get("version") or "0.0.0")
    pkg = _identifier(package_name or title, fallback="api")

    servers = [
        str(server.get("url"))
        for server in document.get("servers", [])
        if isinstance(server, dict) and server.get("url")
    ]
    security_schemes = (document.get("components") or {}).get("securitySchemes") or {}

    resource_ops: dict[str, list[Operation]] = defaultdict(list)
    paths = document.get("paths") or {}
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI paths must be an object.")

    for raw_path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        inherited_params = [
            _parameter(_resolve_ref(document, p), document)
            for p in path_item.get("parameters", [])
            if isinstance(_resolve_ref(document, p), dict)
        ]
        for method, operation_obj in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(
                operation_obj, dict
            ):
                continue
            op = _operation(
                document,
                path=str(raw_path),
                method=method.upper(),
                operation=operation_obj,
                inherited_params=[p for p in inherited_params if p is not None],
            )
            resource_ops[op.resource].append(op)

    resources: list[Resource] = []
    resource_name_map = _unique_name_map(
        sorted(resource_ops),
        reserved=RESERVED_RESOURCE_NAMES,
        suffix="resource",
    )
    class_name_map = _unique_class_name_map(sorted(resource_ops))
    for raw_resource_name in sorted(resource_ops):
        resource_name = resource_name_map[raw_resource_name]
        ops = _dedupe_operation_names(
            resource_ops[raw_resource_name],
            resource_name,
        )
        for op in ops:
            op.resource = resource_name
        resources.append(
            Resource(
                name=resource_name,
                class_name=class_name_map[raw_resource_name],
                label=raw_resource_name.replace("_", " "),
                operations=ops,
            )
        )

    if not resources:
        raise ValueError(f"{spec_path} has no OpenAPI operations to generate.")

    return ApiSpec(
        title=title,
        version=version,
        package_name=pkg,
        servers=servers,
        resources=resources,
        security_schemes=dict(security_schemes),
    )


def _load_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # A .json file that isn't valid JSON is usually mislabeled YAML; fall
            # through and let the YAML loader (a JSON superset) handle it.
            pass
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - pyproject installs it
        raise RuntimeError(
            "This spec is not valid JSON and reading YAML needs PyYAML. Install "
            "guillotine with its default dependencies or pass a JSON spec."
        ) from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} is not valid YAML or JSON: {exc}") from exc


def _operation(
    document: dict[str, Any],
    *,
    path: str,
    method: str,
    operation: dict[str, Any],
    inherited_params: list[Parameter],
) -> Operation:
    tags = operation.get("tags") if isinstance(operation.get("tags"), list) else []
    resource = _identifier(tags[0] if tags else _resource_segment(path), fallback="api")
    raw_operation_id = str(
        operation.get("operationId") or _synth_operation_id(method, path)
    )
    operation_id = _identifier(
        raw_operation_id, fallback=f"{method.lower()}_{resource}"
    )
    name = _verb_name(operation_id, resource, method, path)
    summary = _clean_space(str(operation.get("summary") or ""))
    description = _clean_space(str(operation.get("description") or ""))

    seen = {(p.location.value, p.wire_name): p for p in inherited_params}
    for raw_param in operation.get("parameters", []):
        resolved = _resolve_ref(document, raw_param)
        if not isinstance(resolved, dict):
            continue
        param = _parameter(resolved, document)
        if param is not None:
            seen[(param.location.value, param.wire_name)] = param
    body = None
    raw_body = operation.get("requestBody")
    if raw_body:
        resolved_body = _resolve_ref(document, raw_body)
        if isinstance(resolved_body, dict):
            body = _request_body(resolved_body, document)
    safety_tier = _safety_tier(
        method,
        path,
        operation_id,
        summary,
        description,
        override=_safety_override(operation.get("x-guillotine-safety-tier")),
    )
    params = _dedupe_parameter_names(
        _sort_parameters(path, list(seen.values())),
        has_body=body is not None,
        safety_tier=safety_tier,
    )
    list_key, scalar_result = _result_shape(operation, document)

    return Operation(
        name=name,
        operation_id=operation_id,
        method=method,
        path=path,
        resource=resource,
        summary=summary,
        description=description,
        parameters=params,
        request_body=body,
        safety_tier=safety_tier,
        list_key=list_key,
        scalar_result=scalar_result,
    )


def _parameter(raw: dict[str, Any], document: dict[str, Any]) -> Parameter | None:
    wire_name = raw.get("name")
    raw_location = raw.get("in")
    if not wire_name or raw_location not in {loc.value for loc in ParameterLocation}:
        return None

    schema = _resolve_schema_ref(document, raw.get("schema"))
    required = bool(raw.get("required")) or raw_location == "path"
    default = schema.get("default")
    enum = _enum_values(document, schema)
    return Parameter(
        name=_identifier(str(wire_name), fallback="value"),
        wire_name=str(wire_name),
        location=ParameterLocation(raw_location),
        annotation=_annotation(schema),
        required=required,
        default=default,
        enum=enum,
        description=_clean_space(str(raw.get("description") or "")),
    )


def _enum_values(document: dict[str, Any], schema: dict[str, Any]) -> tuple[Any, ...]:
    """Enum choices for a parameter, including multi-value (array-of-enum) filters.

    Common OpenAPI shape: `{type: array, items: {enum: [...]}}` (or items `$ref`).
    The enum lives on the items, not the array, so a naive `schema['enum']` misses
    it and the guard never fires.
    """
    if schema.get("enum"):
        return tuple(schema["enum"])
    if schema.get("type") == "array":
        items = _resolve_schema_ref(document, schema.get("items"))
        if isinstance(items, dict) and items.get("enum"):
            return tuple(items["enum"])
    return ()


_MAX_BODY_FIELDS = 40
_COLLECTION_KEYS = ("items", "data", "results", "records", "values", "features")


def _request_body(raw: dict[str, Any], document: dict[str, Any]) -> RequestBody:
    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    content_type = "application/json"
    media: Any = None
    if content:
        content_type = (
            "application/json"
            if "application/json" in content
            else next(iter(content.keys()))
        )
        media = content.get(content_type)
    fields: tuple[BodyField, ...] = ()
    if isinstance(media, dict):
        schema = _resolve_schema_ref(document, media.get("schema"))
        fields = _body_fields(document, schema)
    return RequestBody(
        required=bool(raw.get("required")),
        content_type=content_type,
        description=_clean_space(str(raw.get("description") or "")),
        fields=fields,
    )


def _body_fields(
    document: dict[str, Any], schema: dict[str, Any]
) -> tuple[BodyField, ...]:
    """Top-level JSON body fields, so writes are discoverable from help/docstrings."""
    props = schema.get("properties")
    if not isinstance(props, dict):
        return ()
    required = set(schema.get("required") or [])
    fields = []
    for name, raw_prop in list(props.items())[:_MAX_BODY_FIELDS]:
        prop = _resolve_schema_ref(document, raw_prop)
        fields.append(
            BodyField(
                name=str(name),
                annotation=_annotation(prop),
                required=name in required,
                enum=_enum_values(document, prop),
                description=_clean_space(str(prop.get("description") or "")),
            )
        )
    return tuple(fields)


def _result_shape(
    operation: dict[str, Any], document: dict[str, Any]
) -> tuple[str | None, bool]:
    """Best-effort (list_key, scalar_result) for the operation's success response.

    Driven by the spec so distillation does not have to guess by key name. Returns
    (None, False) when the schema is a bare array or too vague to classify, letting
    the runtime fall back to its generic heuristic.
    """
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None, False
    resp: Any = None
    for code in ("200", "201", "default"):
        if code in responses:
            resp = responses[code]
            break
    if resp is None:
        for code, candidate in responses.items():
            if str(code).startswith("2"):
                resp = candidate
                break
    resp = _resolve_ref(document, resp)
    if not isinstance(resp, dict) or not isinstance(resp.get("content"), dict):
        return None, False
    media = _pick_json_media(resp["content"])
    if not isinstance(media, dict):
        return None, False
    schema = _resolve_schema_ref(document, media.get("schema"))
    if schema.get("type") == "array":
        return None, False  # bare list; the runtime handles a top-level list
    props = schema.get("properties")
    if isinstance(props, dict) and props:
        for key in _COLLECTION_KEYS:
            if _resolve_schema_ref(document, props.get(key)).get("type") == "array":
                return key, False
        return None, True  # well-described object, no collection wrapper -> single
    return None, False  # vague schema -> let the runtime heuristic decide


def _pick_json_media(content: dict[str, Any]) -> Any:
    if "application/json" in content:
        return content["application/json"]
    for content_type, media in content.items():
        if "json" in content_type.lower():
            return media
    return next(iter(content.values()), None)


def _resolve_ref(document: dict[str, Any], value: Any) -> Any:
    # Follow chained $refs (a ref whose target is itself a ref) until we reach a
    # concrete node; on a cycle or an unresolvable hop, silently return what we have.
    seen: set[str] = set()
    while isinstance(value, dict) and "$ref" in value:
        ref = str(value["$ref"])
        if not ref.startswith("#/") or ref in seen:
            return value
        seen.add(ref)
        node: Any = document
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or part not in node:
                return value
            node = node[part]
        value = node
    return value


def _resolve_schema_ref(document: dict[str, Any], schema: Any) -> dict[str, Any]:
    resolved = _resolve_ref(document, schema)
    return resolved if isinstance(resolved, dict) else {}


def _annotation(schema: dict[str, Any]) -> str:
    schema_type = schema.get("type")
    if schema_type == "integer":
        return "int"
    if schema_type == "number":
        return "float"
    if schema_type == "boolean":
        return "bool"
    if schema_type == "array":
        return "list"
    if schema_type == "object":
        return "dict"
    return "str"


def _sort_parameters(path: str, params: list[Parameter]) -> list[Parameter]:
    path_names = re.findall(r"{([^}]+)}", path)
    path_order = {name: i for i, name in enumerate(path_names)}
    return sorted(
        params,
        key=lambda p: (
            0 if p.location is ParameterLocation.PATH else 1,
            path_order.get(p.wire_name, 999),
            p.location.value,
            p.name,
        ),
    )


def _dedupe_operation_names(ops: list[Operation], resource: str) -> list[Operation]:
    used: dict[str, int] = {}
    for op in sorted(ops, key=lambda item: (item.path, item.method)):
        base = op.name
        if base in RESERVED_OPERATION_NAMES:
            base = f"{base}_operation"
        count = used.get(base, 0)
        used[base] = count + 1
        if count:
            op.name = f"{base}_{count + 1}"
        else:
            op.name = base
    return sorted(ops, key=lambda item: item.name)


def _dedupe_parameter_names(
    params: list[Parameter],
    *,
    has_body: bool,
    safety_tier: SafetyTier,
) -> list[Parameter]:
    reserved = {"self"}
    if has_body:
        reserved.add("body")
    if safety_tier >= SafetyTier.DELETE:
        reserved.update({"yes", "confirm_name"})

    used: dict[str, int] = {}
    out: list[Parameter] = []
    for param in params:
        base = param.name
        if base in reserved:
            base = f"{base}_param"
        count = used.get(base, 0)
        used[base] = count + 1
        name = base if count == 0 else f"{base}_{count + 1}"
        out.append(param if name == param.name else replace(param, name=name))
    return out


def _identifier(value: str, *, fallback: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_").lower()
    value = re.sub(r"_+", "_", value)
    if not value:
        value = fallback
    if value[0].isdigit():
        value = f"{fallback}_{value}"
    if keyword.iskeyword(value):
        value = f"{value}_"
    return value


def _class_name(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_")) or "Api"


def _unique_name_map(
    names: list[str],
    *,
    reserved: set[str],
    suffix: str,
) -> dict[str, str]:
    used: dict[str, int] = {}
    out: dict[str, str] = {}
    for original in names:
        base = original
        if base in reserved:
            base = f"{base}_{suffix}"
        count = used.get(base, 0)
        used[base] = count + 1
        out[original] = base if count == 0 else f"{base}_{count + 1}"
    return out


def _unique_class_name_map(resource_names: list[str]) -> dict[str, str]:
    used: dict[str, int] = {}
    out: dict[str, str] = {}
    for resource_name in resource_names:
        base = _class_name(resource_name)
        if base in RESERVED_RESOURCE_CLASSES:
            base = f"{base}Resource"
        count = used.get(base, 0)
        used[base] = count + 1
        out[resource_name] = base if count == 0 else f"{base}{count + 1}"
    return out


# Path segments that name an API version or transport prefix rather than a
# resource. When a spec carries no tags we skip these so a versioned API like
# Stripe (every path under `/v1/...`) groups by `customers`, `charges`, ... instead
# of collapsing every operation into a single `v1` namespace.
_VERSION_SEGMENT = re.compile(r"^(v\d+|\d{4}-\d{2}-\d{2}|api|rest|services?)$", re.I)


def _resource_segment(path: str) -> str:
    segments = [part for part in path.split("/") if part and not part.startswith("{")]
    for segment in segments:
        if not _VERSION_SEGMENT.match(segment):
            return segment
    return segments[0] if segments else "api"


def _synth_operation_id(method: str, path: str) -> str:
    bits = [method.lower()]
    for part in path.strip("/").split("/"):
        if not part:
            continue
        if part.startswith("{") and part.endswith("}"):
            bits.append("by")
            bits.append(part[1:-1])
        else:
            bits.append(part)
    return "_".join(bits)


def _verb_name(operation_id: str, resource: str, method: str, path: str) -> str:
    name = operation_id
    resource_singular = resource[:-1] if resource.endswith("s") else resource
    for prefix in (resource, resource_singular):
        if name == prefix:
            name = method.lower()
        elif name.startswith(prefix + "_"):
            name = name[len(prefix) + 1 :]
    for suffix in (resource, resource_singular):
        if name.endswith("_" + suffix):
            name = name[: -len(suffix) - 1]
    if not name:
        name = method.lower()
    return _identifier(name, fallback=method.lower())


# Whole-word signals that an operation cascades (deletes dependents too).
_CASCADE_TERMS = frozenset(
    {"cascade", "cascading", "recursive", "recursively", "purge"}
)

# Whole-word signals that a non-DELETE-method operation is still destructive. The
# bias is deliberately conservative: a false positive only adds a `yes=True`
# speed-bump, while a false negative removes the guard from an irreversible call.
# This is a heuristic, not a guarantee — override per operation in the spec with
# `x-guillotine-safety-tier: read|write|delete|cascade`.
_DESTRUCTIVE_TERMS = frozenset(
    {
        "archive",
        "ban",
        "cancel",
        "clear",
        "close",
        "deactivate",
        "delete",
        "deprovision",
        "destroy",
        "disable",
        "dismiss",
        "drop",
        "erase",
        "expire",
        "expunge",
        "flush",
        "force",
        "leave",
        "lock",
        "purge",
        "remove",
        "reset",
        "revoke",
        "shred",
        "suspend",
        "terminate",
        "transfer",
        "truncate",
        "unarchive",
        "unblock",
        "unfollow",
        "unlock",
        "unpublish",
        "void",
        "wipe",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _safety_override(value: Any) -> SafetyTier | None:
    """Read an explicit `x-guillotine-safety-tier` operation extension, if present."""
    if not isinstance(value, str):
        return None
    try:
        return SafetyTier[value.strip().upper()]
    except KeyError:
        return None


def _safety_tier(
    method: str,
    path: str,
    operation_id: str,
    summary: str,
    description: str,
    *,
    override: SafetyTier | None = None,
) -> SafetyTier:
    if override is not None:
        return override
    if method in {"GET", "HEAD", "OPTIONS"}:
        return SafetyTier.READ
    # Match whole tokens, not substrings, so `clearance` no longer reads as `clear`
    # and `closet` no longer reads as `close`.
    tokens = set(
        _TOKEN_RE.findall(" ".join((path, operation_id, summary, description)).lower())
    )
    if tokens & _CASCADE_TERMS:
        return SafetyTier.CASCADE
    if method == "DELETE" or tokens & _DESTRUCTIVE_TERMS:
        return SafetyTier.DELETE
    return SafetyTier.WRITE


def _clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
