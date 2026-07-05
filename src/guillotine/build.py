from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .emit.mcp import emit_mcp
from .emit.python import emit_python
from .emit.skills import emit_skills
from .ingest.openapi import load_openapi


@dataclass(frozen=True)
class BuildResult:
    """Locations written by one `guillotine build` run."""

    package_dir: Path
    skills_dir: Path
    mcp_dir: Path


def build(
    spec_path: str | Path,
    *,
    output_dir: str | Path,
    package_name: str | None = None,
    lang: str = "python",
) -> BuildResult:
    """Build every projection from one OpenAPI spec.

    The generated DSL, skills, and MCP wrapper are projections of the same IR. This
    function intentionally overwrites only the projection folders it owns.
    """
    if lang != "python":
        raise ValueError("Only --lang python is implemented in v0.1.")

    spec = load_openapi(spec_path, package_name=package_name)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    package_dir = emit_python(spec, out)
    skills_dir = emit_skills(spec, out)
    mcp_dir = emit_mcp(spec, out)
    return BuildResult(package_dir=package_dir, skills_dir=skills_dir, mcp_dir=mcp_dir)
