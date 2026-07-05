# Quickstart

Install from a local checkout:

```bash
python3 -m pip install -e ".[dev]"
```

Inspect a spec before generating code:

```bash
guillotine inspect tests/fixtures/todo_openapi.yaml --format markdown
```

Build the projections:

```bash
guillotine build tests/fixtures/todo_openapi.yaml -o ./out
```

Use the generated DSL:

```python
import acme_tasks

c = acme_tasks.connect(base_url="https://api.example.test", token="...")
tasks = c.tasks.list(status="open", per_page=50).all(max_pages=2)
print(tasks[:3])
```

Generated folders:

```text
out/acme_tasks/   Python DSL package
out/skills/       Agent Skills pack
out/mcp/          single-tool MCP wrapper
```

Compile generated code as a smoke test:

```bash
python3 -m compileall -q out/acme_tasks out/mcp
```
