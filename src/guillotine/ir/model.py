from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any


class SafetyTier(IntEnum):
    READ = 0
    WRITE = 1
    DELETE = 2
    CASCADE = 3


class ParameterLocation(str, Enum):
    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    COOKIE = "cookie"


@dataclass(frozen=True)
class Parameter:
    name: str
    wire_name: str
    location: ParameterLocation
    annotation: str = "str"
    required: bool = False
    default: Any = None
    enum: tuple[Any, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class BodyField:
    """One top-level field of a JSON request body, surfaced for discoverability."""

    name: str
    annotation: str = "str"
    required: bool = False
    enum: tuple[Any, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class RequestBody:
    required: bool = False
    content_type: str = "application/json"
    description: str = ""
    fields: tuple[BodyField, ...] = ()


@dataclass
class Operation:
    name: str
    operation_id: str
    method: str
    path: str
    resource: str
    summary: str = ""
    description: str = ""
    parameters: list[Parameter] = field(default_factory=list)
    request_body: RequestBody | None = None
    safety_tier: SafetyTier = SafetyTier.READ
    # Spec-driven result shape (so distillation never has to guess by key name):
    #   list_key="features" -> the collection lives at body["features"]
    #   scalar_result=True  -> success response is a single object (do not unwrap)
    #   both unset           -> unknown; fall back to the generic heuristic
    list_key: str | None = None
    scalar_result: bool = False

    @property
    def path_parameters(self) -> list[Parameter]:
        return [p for p in self.parameters if p.location is ParameterLocation.PATH]

    @property
    def query_parameters(self) -> list[Parameter]:
        return [p for p in self.parameters if p.location is ParameterLocation.QUERY]

    @property
    def header_parameters(self) -> list[Parameter]:
        return [p for p in self.parameters if p.location is ParameterLocation.HEADER]

    @property
    def pagination(self) -> dict[str, str]:
        """Recognized pagination wiring, or {} when no usable cursor pair exists.

        Single source of truth for both the emitter and `inspect`. Only a complete
        page+size or offset+limit pair counts, so a lone `page` (with no page-size
        param) is not advertised as paginated and `.all()` will not walk it blindly.
        """
        query = {p.name for p in self.query_parameters}
        config: dict[str, str] = {}
        size_key = next(
            (key for key in ("per_page", "page_size", "limit") if key in query), None
        )
        if "page" in query and size_key:
            config["page"] = "page"
            config["per_page"] = size_key
        if "offset" in query and "limit" in query:
            config["offset"] = "offset"
            config["limit"] = "limit"
        return config


@dataclass
class Resource:
    name: str
    class_name: str
    label: str
    operations: list[Operation] = field(default_factory=list)


@dataclass
class ApiSpec:
    title: str
    version: str
    package_name: str
    servers: list[str]
    resources: list[Resource]
    security_schemes: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def default_server(self) -> str:
        return self.servers[0] if self.servers else ""
