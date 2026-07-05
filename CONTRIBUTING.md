# Contributing

Guillotine is early but intentionally structured like a releasable OSS project.

## Development Setup

```bash
uv venv
uv pip install -e ".[dev]"
```

Run the validation loop before submitting changes:

```bash
python3 -m pytest -q
ruff check .
guillotine inspect tests/fixtures/todo_openapi.yaml --format json
```

If you change an emitter, also build and compile a generated package:

```bash
guillotine build tests/fixtures/todo_openapi.yaml -o /tmp/guillotine-smoke
python3 -m compileall -q /tmp/guillotine-smoke/acme_tasks /tmp/guillotine-smoke/mcp
```

## Design Rules

- Keep the generated DSL Python-first and agent-readable.
- Prefer deterministic generation from the IR over hand-maintained projection code.
- Keep errors prescriptive: state what failed and what the next action is.
- Add tests at the generated-surface level, not only the IR level.
- Do not add vendor-specific positioning or customer references to this repo.

## Generated Artifacts

Generated output should be reproducible. If a generated fixture is needed for review,
put it under `examples/generated/` and document the source spec URL or file.
