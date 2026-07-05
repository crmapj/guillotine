# Release Checklist

This checklist is for maintainers preparing a public package release.

## Local Validation

```bash
python3 -m pytest -q
python3 -m ruff check .
python3 -m ruff format --check .
uv run --extra dev python -m build
uv run --extra dev python -m twine check dist/*
uv export --locked --no-emit-project --no-dev --output-file /tmp/guillotine-requirements-audit.txt >/dev/null
uv run --extra dev pip-audit --strict --no-deps --disable-pip --requirement /tmp/guillotine-requirements-audit.txt
guillotine inspect tests/fixtures/todo_openapi.yaml --format json
guillotine build tests/fixtures/todo_openapi.yaml -o /tmp/guillotine-smoke
python3 -m compileall -q /tmp/guillotine-smoke/acme_tasks /tmp/guillotine-smoke/mcp
```

If the GitHub REST OpenAPI spec is available locally:

```bash
guillotine inspect /tmp/guillotine-real/github.openapi.json --package-name github_api
```

## Metadata

- `pyproject.toml` has current version, classifiers, keywords, and project URLs.
- `CHANGELOG.md` has an entry for the release.
- `README.md` install and quickstart commands work from a clean environment.
- `SECURITY.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md`, and `CONTRIBUTING.md` are present.

## First Release Only

- Confirm the final GitHub organization/repository URL and update the `pyproject.toml`
  project URLs if it differs from `crmapj/guillotine`.
- Configure the PyPI trusted publisher for `.github/workflows/release.yml`.
- Replace `Unreleased` in `CHANGELOG.md` with the release date.
- Publish to PyPI before (or immediately after) making the repository public so the
  README install command works from day one.

## Publish

Release tags should use:

```text
vX.Y.Z
```

The generated release workflow builds the package and publishes to PyPI through trusted
publishing. Configure the PyPI trusted publisher before pushing the first public tag.
