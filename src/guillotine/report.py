from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from guillotine.ingest import load_openapi
from guillotine.ir import ApiSpec, Operation, SafetyTier


@dataclass(frozen=True)
class SpecReport:
    title: str
    version: str
    package_name: str
    default_server: str
    resources: int
    operations: int
    read_operations: int
    write_operations: int
    delete_operations: int
    cascade_operations: int
    parameters: int
    enum_parameters: int
    request_bodies: int
    paginated_operations: int
    openapi_bytes: int
    estimated_tool_schema_tokens: int
    estimated_dsl_cheatsheet_tokens: int
    estimated_static_reduction: float
    warnings: list[str]

    def as_dict(self) -> dict:
        data = asdict(self)
        data["estimated_static_reduction"] = round(self.estimated_static_reduction, 2)
        return data


def inspect_spec(
    spec_path: str | Path,
    *,
    package_name: str | None = None,
) -> SpecReport:
    path = Path(spec_path)
    spec = load_openapi(path, package_name=package_name)
    operations = [op for resource in spec.resources for op in resource.operations]
    openapi_bytes = path.stat().st_size
    # Apples-to-apples discovery-surface estimate: what a model would load to call
    # this API as classic JSON tool schemas (one function def per operation) versus
    # the generated cheatsheet (one signature + summary line per verb). Both are
    # rough chars/4 proxies, not a tokenizer, and neither captures the runtime
    # distillation/code-mode wins -- those need the benchmark (next-phase work).
    tool_schema_chars = sum(_tool_schema_chars(op) for op in operations)
    cheatsheet_chars = sum(_cheatsheet_chars(op) for op in operations)
    cheatsheet_chars += sum(
        len(resource.name) + len(resource.class_name) for resource in spec.resources
    )
    estimated_tool_schema_tokens = _tokens(tool_schema_chars)
    estimated_dsl_tokens = _tokens(cheatsheet_chars)
    return SpecReport(
        title=spec.title,
        version=spec.version,
        package_name=spec.package_name,
        default_server=spec.default_server,
        resources=len(spec.resources),
        operations=len(operations),
        read_operations=_count_tier(operations, SafetyTier.READ),
        write_operations=_count_tier(operations, SafetyTier.WRITE),
        delete_operations=_count_tier(operations, SafetyTier.DELETE),
        cascade_operations=_count_tier(operations, SafetyTier.CASCADE),
        parameters=sum(len(op.parameters) for op in operations),
        enum_parameters=sum(
            1 for op in operations for param in op.parameters if param.enum
        ),
        request_bodies=sum(1 for op in operations if op.request_body is not None),
        paginated_operations=sum(1 for op in operations if op.pagination),
        openapi_bytes=openapi_bytes,
        estimated_tool_schema_tokens=estimated_tool_schema_tokens,
        estimated_dsl_cheatsheet_tokens=estimated_dsl_tokens,
        estimated_static_reduction=(
            estimated_tool_schema_tokens / estimated_dsl_tokens
            if estimated_dsl_tokens
            else 0.0
        ),
        warnings=_warnings(spec, operations),
    )


def render_report(report: SpecReport, *, fmt: str = "text") -> str:
    if fmt == "json":
        return json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n"
    if fmt == "markdown":
        return _markdown(report)
    if fmt != "text":
        raise ValueError("format must be one of: text, json, markdown")
    return _text(report)


def _text(report: SpecReport) -> str:
    data = report.as_dict()
    lines = [
        f"{report.title} ({report.version})",
        f"package: {report.package_name}",
        f"default server: {report.default_server or '(none)'}",
        "",
        f"resources: {report.resources}",
        f"operations: {report.operations}",
        (
            "safety: "
            f"read={report.read_operations}, write={report.write_operations}, "
            f"delete={report.delete_operations}, cascade={report.cascade_operations}"
        ),
        f"parameters: {report.parameters} ({report.enum_parameters} enum-guarded)",
        f"request bodies: {report.request_bodies}",
        f"paginated operations: {report.paginated_operations}",
        "",
        (
            "discovery-surface estimate (rough chars/4, static only): "
            f"JSON tool schemas ~{report.estimated_tool_schema_tokens:,} tokens -> "
            f"DSL cheatsheet ~{report.estimated_dsl_cheatsheet_tokens:,} tokens "
            f"(~{data['estimated_static_reduction']}x). Excludes runtime "
            "distillation/code-mode wins; not a benchmark."
        ),
    ]
    if report.warnings:
        lines.extend(["", "warnings:"])
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines) + "\n"


def _markdown(report: SpecReport) -> str:
    data = report.as_dict()
    lines = [
        f"# {report.title} Guillotine Inspect",
        "",
        f"- Package: `{report.package_name}`",
        f"- Version: `{report.version}`",
        f"- Default server: `{report.default_server or '(none)'}`",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Resources | {report.resources} |",
        f"| Operations | {report.operations} |",
        f"| Read operations | {report.read_operations} |",
        f"| Write operations | {report.write_operations} |",
        f"| Delete operations | {report.delete_operations} |",
        f"| Cascade operations | {report.cascade_operations} |",
        f"| Parameters | {report.parameters} |",
        f"| Enum-guarded parameters | {report.enum_parameters} |",
        f"| Request bodies | {report.request_bodies} |",
        f"| Paginated operations | {report.paginated_operations} |",
        f"| Est. JSON tool-schema tokens | {report.estimated_tool_schema_tokens:,} |",
        f"| Est. DSL cheatsheet tokens | {report.estimated_dsl_cheatsheet_tokens:,} |",
        f"| Est. discovery-surface ratio | ~{data['estimated_static_reduction']}x |",
    ]
    if report.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines) + "\n"


def _count_tier(operations: list[Operation], tier: SafetyTier) -> int:
    return sum(1 for op in operations if op.safety_tier is tier)


def _tokens(chars: int) -> int:
    return max(1, round(chars / 4))


_JSON_TYPES = {
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
}


def _tool_schema_chars(op: Operation) -> int:
    """Chars of an equivalent JSON tool/function definition for one operation.

    Approximates the classic agent baseline: registering each operation as a JSON
    tool schema (name + description + parameter schema) in the model's context.
    """
    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    for param in op.parameters:
        prop: dict[str, Any] = {"type": _JSON_TYPES.get(param.annotation, "string")}
        if param.description:
            prop["description"] = param.description
        if param.enum:
            prop["enum"] = list(param.enum)
        properties[param.name] = prop
        if param.required:
            required.append(param.name)
    if op.request_body is not None:
        properties["body"] = {"type": "object"}
        if op.request_body.required:
            required.append("body")
    schema = {
        "name": op.operation_id,
        "description": op.summary or op.description or "",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
    return len(json.dumps(schema))


def _cheatsheet_chars(op: Operation) -> int:
    """Chars of the generated cheatsheet entry for one verb (signature + summary).

    Mirrors what `cheatsheet()` actually emits so the estimate does not undercount
    the real discovery surface.
    """
    params = [param.name for param in op.parameters]
    if op.request_body is not None:
        params.append("body")
    signature = f"  {op.resource}.{op.name}({', '.join(params)})"
    summary = f"      {op.summary or f'{op.method} {op.path}'}"
    return len(signature) + len(summary) + 1


def _warnings(spec: ApiSpec, operations: list[Operation]) -> list[str]:
    warnings: list[str] = []
    if not spec.default_server:
        warnings.append(
            "No OpenAPI server URL found; generated clients need base_url=."
        )
    missing_summaries = sum(1 for op in operations if not op.summary)
    if missing_summaries:
        warnings.append(
            f"{missing_summaries} operation(s) have no summary; generated cheatsheet lines will be weaker."
        )
    if not any(param.enum for op in operations for param in op.parameters):
        warnings.append(
            "No enum parameters found; generated choice guards will be sparse."
        )
    body_count = sum(1 for op in operations if op.request_body is not None)
    if body_count:
        warnings.append(
            f"{body_count} operation(s) accept generic body=dict; typed body models are a future emitter pass."
        )
    return warnings
