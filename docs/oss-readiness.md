# OSS Readiness Notes

Guillotine's repository conventions deliberately follow proven patterns from small,
focused OSS developer tools:

- lead with install and immediate usage,
- keep package metadata complete enough for PyPI search and trust,
- provide issue templates and a PR checklist,
- publish security/runtime boundaries clearly,
- keep release steps reproducible,
- make the first generated artifact easy to inspect.

Reference projects and guidance:

- [Simon Willison's LLM](https://github.com/simonw/llm): compact CLI README, install
  path, plugin-friendly docs, and examples-first presentation.
- [PyPA sampleproject](https://github.com/pypa/sampleproject): modern `pyproject.toml`
  metadata shape, classifiers, URLs, and package-build expectations.
- [pydantic/mcp-run-python](https://github.com/pydantic/mcp-run-python): adjacent
  code-execution/MCP positioning and the need to be explicit about sandbox boundaries.
- [Astral uv](https://github.com/astral-sh/uv): polished developer-tool repository
  hygiene, docs, contributing, security, and release discipline.

## Applied To Guillotine

- `pyproject.toml` now has PyPI-facing metadata, classifiers, keywords, project URLs,
  sdist curation, and a bounded optional MCP dependency.
- GitHub workflows cover lint, tests, inspect smoke, generated compile smoke, package
  build, and tag-based PyPI publishing.
- `.github/ISSUE_TEMPLATE`, `.github/pull_request_template.md`, and Dependabot are in
  place.
- `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, `CHANGELOG.md`,
  and `ROADMAP.md` are in place.
- `docs/quickstart.md`, `docs/generated-dsl-contract.md`, `docs/security-model.md`, and
  `docs/release.md` cover the practical path from install to release.
- `guillotine inspect` gives users a trust-building pre-generation report.

## Roadmap, Not A Launch Blocker

- Publish a benchmark result once the harness exists.
