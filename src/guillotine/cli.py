from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import __version__
from .build import build
from .report import inspect_spec, render_report


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guillotine",
        description="Generate a compact Python DSL, skill pack, and MCP wrapper from OpenAPI.",
    )
    parser.add_argument(
        "--version", action="version", version=f"guillotine {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser(
        "build",
        help="Build DSL, skills, and MCP projections from an OpenAPI 3 spec.",
    )
    build_p.add_argument("spec", type=Path, help="OpenAPI YAML or JSON file.")
    build_p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("./out"),
        help="Output directory. Default: ./out",
    )
    build_p.add_argument(
        "--lang",
        default="python",
        choices=["python"],
        help="Generated DSL language. v0.1 supports python.",
    )
    build_p.add_argument(
        "--package-name",
        help="Python package name for the generated DSL. Defaults to the API title.",
    )

    inspect_p = sub.add_parser(
        "inspect",
        help="Inspect an OpenAPI spec and estimate the generated DSL surface.",
    )
    inspect_p.add_argument("spec", type=Path, help="OpenAPI YAML or JSON file.")
    inspect_p.add_argument(
        "--package-name",
        help="Python package name to use for estimates. Defaults to the API title.",
    )
    inspect_p.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Report format. Default: text",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)

    try:
        return _dispatch(args)
    except FileNotFoundError as exc:
        path = exc.filename or getattr(args, "spec", "")
        print(f"guillotine: error: spec file not found: {path}", file=sys.stderr)
        return 2
    except (ValueError, OSError, yaml.YAMLError) as exc:
        print(f"guillotine: error: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "build":
        result = build(
            args.spec,
            output_dir=args.output,
            package_name=args.package_name,
            lang=args.lang,
        )
        print(f"DSL:    {result.package_dir}")
        print(f"Skills: {result.skills_dir}")
        print(f"MCP:    {result.mcp_dir}")
        return 0

    # inspect is the only other subcommand; subparsers are required=True.
    report = inspect_spec(args.spec, package_name=args.package_name)
    print(render_report(report, fmt=args.format), end="")
    return 0
