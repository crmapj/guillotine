from __future__ import annotations

import shutil
from pathlib import Path
from textwrap import indent

from guillotine.ir import (
    ApiSpec,
    BodyField,
    Operation,
    Parameter,
    Resource,
    SafetyTier,
)


def emit_python(spec: ApiSpec, output_dir: Path) -> Path:
    package_dir = output_dir / spec.package_name
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)

    (package_dir / "_runtime.py").write_text(_runtime_source(), encoding="utf-8")
    (package_dir / "_client.py").write_text(_client_source(spec), encoding="utf-8")
    (package_dir / "__init__.py").write_text(_init_source(spec), encoding="utf-8")
    return package_dir


def _client_source(spec: ApiSpec) -> str:
    chunks = [
        '"""Generated Guillotine DSL client. Do not edit by hand."""',
        "from __future__ import annotations",
        "",
        "import os",
        "",
        "from ._runtime import HttpTransport, OperationResult, Tier, _body_choice, _choice",
        "",
        f"DEFAULT_BASE_URL = {spec.default_server!r}",
        f"ENV_PREFIX = {spec.package_name.upper()!r}",
        f"AUTH_SCHEME = {_auth_config(spec)!r}",
        "",
    ]
    for resource in spec.resources:
        chunks.append(_resource_class(resource))
        chunks.append("")
    chunks.append(_choice_metadata(spec))
    chunks.append("")
    chunks.append(_client_class(spec))
    return "\n".join(chunks).rstrip() + "\n"


def _resource_class(resource: Resource) -> str:
    lines = [
        f"class {resource.class_name}:",
        f'    """{resource.label.title()} operations."""',
        "",
        "    def __init__(self, client: Client):",
        "        self._client = client",
        "        self.raw = client.raw",
        "",
    ]
    for op in resource.operations:
        lines.extend(_operation_method(op))
        lines.append("")
    return "\n".join(lines).rstrip()


def _operation_method(op: Operation) -> list[str]:
    sig = _signature(op)
    doc = _docstring(op)
    lines = [
        f"    def {op.name}({sig}) -> OperationResult:",
        indent(doc, "        "),
    ]
    for param in op.parameters:
        if param.enum:
            lines.append(
                "        "
                + f"_choice({param.name!r}, {param.name}, {tuple(param.enum)!r})"
            )
    if op.request_body:
        for body_field in op.request_body.fields:
            if body_field.enum:
                lines.append(
                    "        "
                    + f"_body_choice(body, {body_field.name!r}, {tuple(body_field.enum)!r})"
                )
    path_params = {
        p.wire_name: p.name for p in op.parameters if p.location.value == "path"
    }
    query_params = {
        p.wire_name: p.name for p in op.parameters if p.location.value == "query"
    }
    header_params = {
        p.wire_name: p.name for p in op.parameters if p.location.value == "header"
    }
    lines.extend(
        [
            "        return OperationResult(",
            "            self._client,",
            f"            method={op.method!r},",
            f"            path_template={op.path!r},",
            f"            operation_id={op.operation_id!r},",
            f"            summary={op.summary!r},",
            f"            safety_tier=Tier.{op.safety_tier.name},",
            f"            path_params={_dict_literal(path_params)},",
            f"            query={_dict_literal(query_params)},",
            f"            headers={_dict_literal(header_params)},",
            f"            body={'body' if op.request_body else 'None'},",
            f"            content_type={op.request_body.content_type!r},"
            if op.request_body
            else "            content_type='application/json',",
            f"            pagination={_pagination_literal(op)},",
            f"            list_key={op.list_key!r},",
            f"            scalar_result={op.scalar_result!r},",
        ]
    )
    if op.safety_tier >= SafetyTier.DELETE:
        lines.extend(
            [
                f"            confirm_target={_confirm_target_expr(op)},",
                "            yes=yes,",
                "            confirm_name=confirm_name,",
            ]
        )
    lines.append("        )")
    return lines


def _signature(op: Operation) -> str:
    parts = ["self"]
    path_params = [p for p in op.parameters if p.location.value == "path"]
    for param in path_params:
        parts.append(_param_sig(param, required=True))

    keyword_parts: list[str] = []
    for param in op.parameters:
        if param.location.value == "path":
            continue
        keyword_parts.append(_param_sig(param, required=param.required))

    if op.request_body:
        if op.request_body.required:
            keyword_parts.append("body: dict")
        else:
            keyword_parts.append("body: dict | None = None")

    if op.safety_tier >= SafetyTier.DELETE:
        keyword_parts.append("yes: bool = False")
        keyword_parts.append("confirm_name: str | None = None")

    if keyword_parts:
        parts.append("*")
        parts.extend(keyword_parts)
    return ", ".join(parts)


def _param_sig(param: Parameter, *, required: bool) -> str:
    annotation = param.annotation
    if required:
        return f"{param.name}: {annotation}"
    # Only inline immutable scalar defaults. A list/dict default would be a shared
    # mutable default arg (and an exotic value may not round-trip through repr as
    # valid source), so fall back to None and let the caller pass the value.
    if param.default is None or isinstance(param.default, (str, int, float, bool)):
        default = repr(param.default)
    else:
        default = "None"
    return f"{param.name}: {annotation} | None = {default}"


def _body_field_lines(fields: tuple[BodyField, ...]) -> list[str]:
    lines = []
    for field in fields[:24]:
        kind = "required" if field.required else "optional"
        choices = f" [choices: {', '.join(map(str, field.enum))}]" if field.enum else ""
        lines.append(f"- {field.name} ({field.annotation}, {kind}){choices}")
    if len(fields) > 24:
        lines.append(f"- ... and {len(fields) - 24} more field(s)")
    return lines


def _docstring(op: Operation) -> str:
    title = op.summary or f"{op.method} {op.path}"
    details = [title, "", f"HTTP {op.method} {op.path}."]
    if op.description:
        details.extend(["", op.description])
    choices = [
        f"{p.name}: {', '.join(map(str, p.enum))}" for p in op.parameters if p.enum
    ]
    if choices:
        details.extend(["", "Validated choices: " + "; ".join(choices) + "."])
    if op.request_body and op.request_body.fields:
        details.extend(["", "Body fields (pass as body={...}):"])
        details.extend(_body_field_lines(op.request_body.fields))
    if op.safety_tier >= SafetyTier.DELETE:
        details.extend(
            [
                "",
                "Destructive operation: pass yes=True to make intent explicit. "
                "CASCADE-tier operations also require confirm_name=.",
            ]
        )
    body = "\n".join(details)
    # A normal string literal still becomes the function docstring when it is the
    # first statement, and repr() makes arbitrary OpenAPI prose syntax-safe.
    return repr(body)


def _dict_literal(mapping: dict[str, str]) -> str:
    if not mapping:
        return "{}"
    items = ", ".join(f"{key!r}: {value}" for key, value in mapping.items())
    return "{" + items + "}"


def _pagination_literal(op: Operation) -> str:
    # Shared with `inspect` via the IR so the emitted config and the reported
    # pagination coverage cannot disagree.
    return repr(op.pagination)


def _confirm_target_expr(op: Operation) -> str:
    if not op.path_parameters:
        return "None"
    return op.path_parameters[-1].name


def _auth_config(spec: ApiSpec) -> dict[str, str]:
    for raw in spec.security_schemes.values():
        if not isinstance(raw, dict):
            continue
        scheme_type = str(raw.get("type") or "").lower()
        if scheme_type == "apikey":
            location = str(raw.get("in") or "")
            name = str(raw.get("name") or "")
            if location in {"header", "query", "cookie"} and name:
                return {"type": "apiKey", "in": location, "name": name}
        if scheme_type == "http":
            scheme = str(raw.get("scheme") or "").lower()
            if scheme in {"bearer", "basic"}:
                return {"type": "http", "scheme": scheme}
    return {"type": "http", "scheme": "bearer"}


def _client_class(spec: ApiSpec) -> str:
    env_prefix = spec.package_name.upper()
    lines = [
        "class Client:",
        f'    """{spec.title} DSL root. Namespaces hang off this object."""',
        "",
        "    def __init__(",
        "        self,",
        "        *,",
        "        base_url: str | None = None,",
        "        token: str | None = None,",
        "        headers: dict[str, str] | None = None,",
        "        transport=None,",
        "        timeout: float = 30.0,",
        "    ):",
        "        self.base_url = (",
        "            base_url",
        f"            or os.environ.get({env_prefix + '_BASE_URL'!r})",
        "            or os.environ.get('API_BASE_URL')",
        "            or DEFAULT_BASE_URL",
        "        )",
        "        token = token or os.environ.get(ENV_PREFIX + '_TOKEN') or os.environ.get('API_TOKEN')",
        "        merged_headers = dict(headers or {})",
        "        self._auth_query = {}",
        "        if token:",
        "            auth_type = AUTH_SCHEME.get('type')",
        "            if auth_type == 'apiKey':",
        "                name = AUTH_SCHEME.get('name')",
        "                location = AUTH_SCHEME.get('in')",
        "                if location == 'header' and name:",
        "                    merged_headers.setdefault(name, token)",
        "                elif location == 'query' and name:",
        "                    self._auth_query[name] = token",
        "                elif location == 'cookie' and name:",
        "                    cookie = f'{name}={token}'",
        "                    merged_headers['Cookie'] = '; '.join(part for part in (merged_headers.get('Cookie'), cookie) if part)",
        "            else:",
        "                scheme = AUTH_SCHEME.get('scheme', 'bearer')",
        "                if scheme == 'basic':",
        "                    merged_headers.setdefault('Authorization', f'Basic {token}')",
        "                elif scheme == 'bearer':",
        "                    merged_headers.setdefault('Authorization', f'Bearer {token}')",
        "                else:",
        "                    merged_headers.setdefault('Authorization', token)",
        "        self.headers = merged_headers",
        "        self.timeout = timeout",
        "        self.raw = transport or HttpTransport()",
        "",
        "    def _request(self, *, method, path, query, headers, body, content_type):",
        "        merged_headers = dict(self.headers)",
        "        merged_headers.update({k: v for k, v in headers.items() if v is not None})",
        "        merged_query = dict(self._auth_query)",
        "        merged_query.update({k: v for k, v in query.items() if v is not None})",
        "        return self.raw.request(",
        "            method=method,",
        "            base_url=self.base_url,",
        "            path=path,",
        "            query=merged_query,",
        "            headers=merged_headers,",
        "            body=body,",
        "            content_type=content_type,",
        "            timeout=self.timeout,",
        "        )",
        "",
    ]
    for resource in spec.resources:
        lines.extend(
            [
                "    @property",
                f"    def {resource.name}(self) -> {resource.class_name}:",
                f"        return {resource.class_name}(self)",
                "",
            ]
        )
    lines.extend(
        [
            "    def __repr__(self):",
            f"        return f'<{spec.package_name}.Client {{self.base_url or \"unconfigured\"}}>'",
            "",
            "def connect(",
            "    *,",
            "    base_url: str | None = None,",
            "    token: str | None = None,",
            "    headers: dict[str, str] | None = None,",
            "    transport=None,",
            "    timeout: float = 30.0,",
            ") -> Client:",
            f'    """Connect to {spec.title}. Args > env > OpenAPI server default."""',
            "    return Client(",
            "        base_url=base_url,",
            "        token=token,",
            "        headers=headers,",
            "        transport=transport,",
            "        timeout=timeout,",
            "    )",
        ]
    )
    return "\n".join(lines)


def _choice_metadata(spec: ApiSpec) -> str:
    lines = ["# Structured help metadata. Generated from OpenAPI schemas."]
    for resource in spec.resources:
        for op in resource.operations:
            choices = {
                param.name: list(param.enum) for param in op.parameters if param.enum
            }
            if choices:
                lines.append(
                    f"{resource.class_name}.{op.name}.__guillotine_choices__ = {choices!r}"
                )
            if op.request_body and op.request_body.fields:
                body_meta = [
                    {
                        "name": field.name,
                        "type": field.annotation,
                        "required": field.required,
                        "enum": list(field.enum),
                    }
                    for field in op.request_body.fields
                ]
                lines.append(
                    f"{resource.class_name}.{op.name}.__guillotine_body__ = {body_meta!r}"
                )
    if len(lines) == 1:
        lines.append("# No enum choices or typed bodies found.")
    return "\n".join(lines)


def _init_source(spec: ApiSpec) -> str:
    groups = [
        (f"{r.label} - c.{r.name}", r.class_name, f"c.{r.name}.")
        for r in spec.resources
    ]
    verb_index: dict[str, str] = {}
    for r in spec.resources:
        for op in r.operations:
            verb_index.setdefault(op.name, f"{r.class_name}.{op.name}")
            verb_index[f"{r.name}.{op.name}"] = f"{r.class_name}.{op.name}"

    exports = [
        "ApiError",
        "ChoiceError",
        "Client",
        "GuillotineError",
        "OperationResult",
        "Response",
        "SafetyBlocked",
        "Tier",
        "cheatsheet",
        "connect",
        "help",
        "help_json",
    ] + [r.class_name for r in spec.resources]

    lines = [
        f'"""Generated {spec.title} DSL. Do not edit by hand."""',
        "from __future__ import annotations",
        "",
        "import inspect",
        "",
        "from ._runtime import (",
        "    ApiError,",
        "    ChoiceError,",
        "    GuillotineError,",
        "    OperationResult,",
        "    Response,",
        "    SafetyBlocked,",
        "    Tier,",
        ")",
        "from ._client import (",
        "    Client,",
        "    connect,",
    ]
    for r in spec.resources:
        lines.append(f"    {r.class_name},")
    lines.extend(
        [
            ")",
            "",
            f"__version__ = {spec.version!r}",
            f"__api_title__ = {spec.title!r}",
            f"__all__ = {exports!r}",
            "",
            "_CHEATSHEET_GROUPS = [",
        ]
    )
    for label, cls, prefix in groups:
        lines.append(f"    ({label!r}, {cls}, {prefix!r}),")
    lines.extend(
        [
            "]",
            "",
            "_VERB_INDEX = {",
        ]
    )
    for name, ref in sorted(verb_index.items()):
        lines.append(f"    {name!r}: {ref},")
    lines.extend(
        [
            "}",
            "",
            "",
            "def _sig(fn) -> str:",
            "    try:",
            "        return str(inspect.signature(fn))",
            "    except (TypeError, ValueError):",
            "        return '(...)'",
            "",
            "",
            "def _doc1(fn) -> str:",
            "    doc = inspect.getdoc(fn) or ''",
            "    return doc.splitlines()[0] if doc else ''",
            "",
            "",
            "def cheatsheet(section: str | None = None, grep: str | None = None) -> str:",
            f'    """Generated, scopeable reference for the {spec.title} DSL."""',
            "    groups = []",
            "    groups.append(('entry', [",
            "        f'  connect{_sig(connect)}\\n      {_doc1(connect)}',",
            "        f'  cheatsheet{_sig(cheatsheet)}\\n      {_doc1(cheatsheet)}',",
            "        f'  help{_sig(help)}\\n      {_doc1(help)}',",
            "        f'  help_json{_sig(help_json)}\\n      {_doc1(help_json)}',",
            "    ]))",
            "    for label, cls, prefix in _CHEATSHEET_GROUPS:",
            "        lines = []",
            "        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):",
            "            if name.startswith('_'):",
            "                continue",
            "            lines.append(f'  {prefix}{name}{_sig(member)}\\n      {_doc1(member)}')",
            "        groups.append((label, lines))",
            "",
            "    sec = section.lower() if section else None",
            "    term = grep.lower() if grep else None",
            "    selected = []",
            "    for label, lines in groups:",
            "        if sec and sec not in label.lower():",
            "            continue",
            "        if term:",
            "            lines = [line for line in lines if term in line.lower()]",
            "            if not lines:",
            "                continue",
            "        selected.append((label, lines))",
            "",
            "    scope = ', '.join(",
            "        part for part in (",
            "            f'section={section!r}' if section else None,",
            "            f'grep={grep!r}' if grep else None,",
            "        ) if part",
            "    )",
            "    if not selected:",
            "        names = ', '.join(label.split(' ', 1)[0] for label, _ in groups)",
            f"        return '# {spec.package_name} cheatsheet - nothing matched (' + scope + ').\\n# Sections: ' + names",
            "",
            f"    out = ['# {spec.package_name} DSL cheatsheet (generated from live signatures)']",
            "    if scope:",
            "        out.append(f'# filtered: {scope}')",
            "    out.append('# Connect first: c = connect(base_url=..., token=...)')",
            "    for label, lines in selected:",
            "        out.append(f'\\n## {label}')",
            "        out.extend(lines)",
            "    return '\\n'.join(out)",
            "",
            "",
            "def _resolve_verb(verb):",
            "    if isinstance(verb, str):",
            "        if verb in _VERB_INDEX:",
            "            return _VERB_INDEX[verb]",
            "        known = ', '.join(sorted(_VERB_INDEX)[:60])",
            "        raise GuillotineError(f'No verb {verb!r}. Try one of: {known}.')",
            "    return getattr(verb, '__func__', verb)",
            "",
            "",
            "def help(obj=None):",
            '    """Print the cheatsheet or Python help for one generated verb."""',
            "    import builtins",
            "",
            "    if obj is None:",
            "        print(cheatsheet())",
            "        return",
            "    builtins.help(_resolve_verb(obj))",
            "",
            "",
            "def help_json(verb) -> dict:",
            '    """Structured help for a generated verb, including enum choices."""',
            "    fn = _resolve_verb(verb)",
            "    sig = inspect.signature(fn)",
            "    params = []",
            "    for name, param in sig.parameters.items():",
            "        if name == 'self':",
            "            continue",
            "        default = None if param.default is inspect.Parameter.empty else param.default",
            "        annotation = None if param.annotation is inspect.Parameter.empty else str(param.annotation)",
            "        params.append({",
            "            'name': name,",
            "            'kind': param.kind.name,",
            "            'required': param.default is inspect.Parameter.empty,",
            "            'default': default,",
            "            'annotation': annotation,",
            "        })",
            "    choices = getattr(fn, '__guillotine_choices__', {})",
            "    return {",
            "        'name': fn.__name__,",
            "        'signature': str(sig),",
            "        'doc': inspect.getdoc(fn) or '',",
            "        'params': params,",
            "        'choices': choices,",
            "        'body': getattr(fn, '__guillotine_body__', []),",
            "    }",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _runtime_source() -> str:
    return r'''"""Runtime helpers for a generated Guillotine DSL."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from enum import IntEnum
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


class GuillotineError(Exception):
    """Base error. Messages are written to be repairable by an agent."""


class ChoiceError(GuillotineError, ValueError):
    """A generated enum guard rejected a value before an API call."""


class SafetyBlocked(GuillotineError):
    """A destructive operation needs explicit confirmation."""


class ApiError(GuillotineError):
    """The remote API returned a non-2xx response."""

    def __init__(self, *, status: int, method: str, path: str, body: str):
        self.status = status
        self.method = method
        self.path = path
        self.body = body
        snippet = body[:800] if body else "(empty response body)"
        super().__init__(
            f"{method} {path} returned HTTP {status}: {snippet}. "
            "Check the generated verb arguments, auth/base_url, or drop to c.raw for the raw transport."
        )


class Tier(IntEnum):
    READ = 0
    WRITE = 1
    DELETE = 2
    CASCADE = 3


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    data: Any
    text: str


def _dangerous_mode() -> bool:
    return os.environ.get("GUILLOTINE_DANGEROUS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _guard(
    *,
    tier: Tier,
    action: str,
    subject: str,
    yes: bool,
    confirm_name: str | None,
    confirm_target: Any | None,
):
    if tier < Tier.DELETE or _dangerous_mode():
        return
    if tier >= Tier.CASCADE:
        expected = None if confirm_target is None else str(confirm_target)
        if not yes:
            raise SafetyBlocked(
                f"Refused: {action} {subject} is CASCADE-tier. To proceed pass yes=True "
                "and confirm_name='<target>'. Or set GUILLOTINE_DANGEROUS=1 in a trusted context."
            )
        if expected is not None and confirm_name != expected:
            raise SafetyBlocked(
                f"Refused: {action} {subject} is CASCADE-tier. Pass confirm_name={expected!r} "
                "so the target is explicit."
            )
        if expected is None and not confirm_name:
            raise SafetyBlocked(
                f"Refused: {action} {subject} is CASCADE-tier. Pass confirm_name='<target>' "
                "so the target is explicit."
            )
        return
    if not yes:
        raise SafetyBlocked(
            f"Refused: {action} {subject} is destructive. To proceed pass yes=True. "
            "Or set GUILLOTINE_DANGEROUS=1 in a trusted context."
        )


def _choice(name: str, value: Any, valid: tuple[Any, ...]) -> None:
    if value is None:
        return
    # Multi-value query params arrive as a list/tuple; validate each element so an
    # array-of-enum filter (e.g. severity=["Severe", "Extreme"]) is guarded too.
    candidates = value if isinstance(value, (list, tuple, set)) else (value,)
    for item in candidates:
        if item not in valid:
            raise ChoiceError(
                f"Unknown {name}={item!r}. Use one of {valid}. "
                "Fix the argument before calling the API."
            )


def _body_choice(body: Any, field: str, valid: tuple[Any, ...]) -> None:
    """Validate an enum field inside a request body before the API call."""
    if not isinstance(body, dict):
        return
    value = body.get(field)
    if value is None:
        return
    candidates = value if isinstance(value, (list, tuple, set)) else (value,)
    for item in candidates:
        if item not in valid:
            raise ChoiceError(
                f"Unknown body[{field!r}]={item!r}. Use one of {valid}. "
                "Fix the body before calling the API."
            )


class HttpTransport:
    """Small stdlib HTTP transport. Tests can pass a fake transport with request()."""

    def request(
        self,
        *,
        method: str,
        base_url: str,
        path: str,
        query: dict[str, Any],
        headers: dict[str, str],
        body: Any,
        content_type: str,
        timeout: float,
    ) -> Response:
        if not base_url:
            raise GuillotineError(
                "No base_url configured. Pass connect(base_url=...) or set <PACKAGE>_BASE_URL/API_BASE_URL."
            )
        url = base_url.rstrip("/") + path
        if query:
            url += "?" + urlencode(query, doseq=True)
        scheme = urlsplit(url).scheme.lower()
        if scheme not in ("http", "https"):
            raise GuillotineError(
                f"Refusing to open a non-HTTP URL ({url!r}). base_url must be "
                "http(s); file://, ftp:// and other schemes are blocked."
            )
        payload = None
        final_headers = dict(headers)
        if body is not None:
            ctype = content_type or "application/json"
            if isinstance(body, bytes):
                payload = body
                final_headers.setdefault("Content-Type", ctype)
            elif ctype.startswith("multipart/form-data"):
                raise GuillotineError(
                    "multipart/form-data bodies are not generated yet. Build the "
                    "multipart payload yourself and send it through c.raw."
                )
            elif ctype == "application/x-www-form-urlencoded":
                payload = urlencode(body, doseq=True).encode("utf-8")
                final_headers.setdefault("Content-Type", ctype)
            elif ctype == "application/json":
                payload = json.dumps(body).encode("utf-8")
                final_headers.setdefault("Content-Type", "application/json")
            elif isinstance(body, (dict, list)):
                # Unknown content type but structured body: JSON-encode it rather
                # than putting a Python repr of a dict on the wire.
                payload = json.dumps(body).encode("utf-8")
                final_headers.setdefault("Content-Type", ctype)
            else:
                payload = str(body).encode("utf-8")
                final_headers.setdefault("Content-Type", ctype)
        req = Request(url, data=payload, headers=final_headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-chosen API endpoint
                text = resp.read().decode("utf-8", errors="replace")
                data = _parse_json(text)
                return Response(resp.status, dict(resp.headers.items()), data, text)
        except HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            data = _parse_json(text)
            headers = dict(exc.headers.items()) if exc.headers else {}
            return Response(exc.code, headers, data, text)
        except Exception as exc:  # noqa: BLE001
            # urllib HTTPError also carries a response body, but keeping this compact
            # avoids leaking library-specific tracebacks to agent code.
            raise GuillotineError(
                f"{method} {url} failed before a usable response was returned: {exc}. "
                "Check base_url/auth/network, then retry."
            ) from exc


class OperationResult:
    """Lazy operation handle. Use .run(), .head(n), .one(), .json(), or .text()."""

    def __init__(
        self,
        client,
        *,
        method: str,
        path_template: str,
        operation_id: str,
        summary: str,
        safety_tier: Tier,
        path_params: dict[str, Any],
        query: dict[str, Any],
        headers: dict[str, Any],
        body: Any,
        content_type: str,
        pagination: dict[str, str] | None = None,
        confirm_target: Any | None = None,
        yes: bool = False,
        confirm_name: str | None = None,
        list_key: str | None = None,
        scalar_result: bool = False,
    ):
        self._client = client
        self.method = method
        self.path_template = path_template
        self.operation_id = operation_id
        self.summary = summary
        self.safety_tier = safety_tier
        self.path_params = path_params
        self.query = query
        self.headers = headers
        self.body = body
        self.content_type = content_type
        self.pagination = pagination or {}
        self.confirm_target = confirm_target
        self.yes = yes
        self.confirm_name = confirm_name
        self.list_key = list_key
        self.scalar_result = scalar_result
        self.response: Response | None = None

    def _rows(self, data) -> list:
        return _items(data, list_key=self.list_key, scalar_result=self.scalar_result)

    @property
    def path(self) -> str:
        path = self.path_template
        for name, value in self.path_params.items():
            if value is None:
                raise GuillotineError(
                    f"Missing path parameter {name!r} for {self.method} {self.path_template}."
                )
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        return path

    def _execute(self, query: dict[str, Any]) -> Response:
        _guard(
            tier=self.safety_tier,
            action=self.method,
            subject=self.path_template,
            yes=self.yes,
            confirm_name=self.confirm_name,
            confirm_target=self.confirm_target,
        )
        resp = self._client._request(
            method=self.method,
            path=self.path,
            query=query,
            headers=self.headers,
            body=self.body,
            content_type=self.content_type,
        )
        if resp.status >= 400:
            raise ApiError(
                status=resp.status,
                method=self.method,
                path=self.path,
                body=resp.text,
            )
        return resp

    def run(self) -> "OperationResult":
        """Execute the API call and return this result handle."""
        self.response = self._execute(dict(self.query))
        return self

    @property
    def data(self):
        if self.response is None:
            self.run()
        assert self.response is not None
        return self.response.data

    def json(self):
        """Return the full parsed JSON payload. Prefer .head() for context control."""
        return self.data

    def text(self) -> str:
        """Return the raw response text."""
        if self.response is None:
            self.run()
        assert self.response is not None
        return self.response.text

    def head(self, n: int = 10) -> list[dict]:
        """Return at most n distilled rows as plain dicts.

        If the payload holds more than n rows, the dropped count is echoed to
        stderr so a caller can tell data was withheld rather than absent.
        """
        items = self._rows(self.data)
        rows = [_distill_item(item) for item in items[:n]]
        total = len(items)
        if total > len(rows):
            print(
                f"{self.operation_id}: {len(rows)} of {total} row(s) shown "
                f"(call .head({total}) or .all() for the rest)",
                file=sys.stderr,
            )
        else:
            print(f"{self.operation_id}: {len(rows)} row(s) returned", file=sys.stderr)
        return rows

    def all(self, *, max_pages: int = 10, per_page: int | None = None) -> list[dict]:
        """Return distilled rows across generated pagination, bounded by max_pages.

        Supports common OpenAPI query shapes: page/per_page, page/limit, and
        offset/limit. If this operation has no recognized pagination params, this
        returns the current page's distilled rows instead of guessing.
        """
        if max_pages < 1:
            raise GuillotineError("all(max_pages=...) needs max_pages >= 1.")
        page_key = self.pagination.get("page")
        size_key = self.pagination.get("per_page")
        offset_key = self.pagination.get("offset")
        limit_key = self.pagination.get("limit")
        if not page_key and not offset_key:
            rows = [_distill_item(item) for item in self._rows(self.data)]
            print(
                f"{self.operation_id}: {len(rows)} row(s) returned (no generated pagination)",
                file=sys.stderr,
            )
            return rows

        query = dict(self.query)
        if per_page is not None:
            if size_key:
                query[size_key] = per_page
            elif limit_key:
                query[limit_key] = per_page

        page = _positive_int(query.get(page_key), default=1) if page_key else None
        offset = _positive_int(query.get(offset_key), default=0) if offset_key else None
        expected_size = _positive_int(
            query.get(size_key) if size_key else query.get(limit_key),
            default=per_page or 0,
        )

        rows = []
        pages_read = 0
        for _ in range(max_pages):
            if page_key and page is not None:
                query[page_key] = page
            if offset_key and offset is not None:
                query[offset_key] = offset
            resp = self._execute(dict(query))
            if self.response is None:
                self.response = resp
            items = self._rows(resp.data)
            pages_read += 1
            rows.extend(_distill_item(item) for item in items)
            if not items:
                break
            # When the spec gave us no page size to expect, infer it from the first
            # page's count so a short final page still stops the walk (no over-fetch),
            # and we never under-fetch on a wrong guess.
            if expected_size <= 0:
                expected_size = len(items)
            if len(items) < expected_size:
                break
            if page_key and page is not None:
                page += 1
            if offset_key and offset is not None:
                offset += expected_size or len(items)
        print(
            f"{self.operation_id}: {len(rows)} row(s) returned across {pages_read} page(s)",
            file=sys.stderr,
        )
        return rows

    def one(self) -> dict:
        """Return one distilled object, raising if the payload is empty."""
        rows = self.head(1)
        if not rows:
            raise GuillotineError(
                f"{self.operation_id} returned no rows. Use .json() to inspect the full payload."
            )
        return rows[0]

    def grain(self) -> dict:
        """Return a compact shape summary for the payload.

        `key_count` is the full key count of the first row; `keys` is capped, so a
        caller can see when the sample is partial.
        """
        data = self.data
        items = self._rows(data)
        keys = sorted(items[0].keys()) if items and isinstance(items[0], dict) else []
        return {
            "items": len(items),
            "keys": keys[:30],
            "key_count": len(keys),
            "type": type(data).__name__,
        }

    def __repr__(self):
        state = "ready" if self.response is None else f"HTTP {self.response.status}"
        return f"<OperationResult {self.method} {self.path_template} {state}>"


def _parse_json(text: str):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


def _items(data, *, list_key=None, scalar_result=False) -> list:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Spec-driven first: the IR told us exactly where the collection lives.
        if list_key and isinstance(data.get(list_key), list):
            return data[list_key]
        # Spec says this is a single object: never unwrap a stray array field.
        if scalar_result:
            return [data]
        # Unknown shape: heuristic. "features" covers GeoJSON (weather/geo/civic).
        for key in ("items", "data", "results", "records", "values", "features"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return [data]
    return [{"value": data}]


def _positive_int(value, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


_DISTILL_KEY_CAP = 50


def _distill_item(item, *, key_cap: int = _DISTILL_KEY_CAP) -> dict:
    if not isinstance(item, dict):
        return {"value": item}
    out = {}
    for key, value in item.items():
        if len(out) >= key_cap:
            # Signal the drop instead of silently NULLing later keys: a caller
            # asking for a missing field can tell it was withheld, not absent.
            out["__truncated_keys__"] = (
                f"{len(item) - key_cap} more key(s); use .json() for the full object"
            )
            break
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, list):
            out[key] = f"[{len(value)} items]"
        elif isinstance(value, dict):
            out[key] = f"{{{len(value)} keys}}"
        else:
            out[key] = str(value)
    return out
'''
