## Summary

-

## Validation

- [ ] `python3 -m pytest -q`
- [ ] `python3 -m ruff check .`
- [ ] `python3 -m ruff format --check .`
- [ ] `python3 -m build`
- [ ] Generated-code smoke if emitters changed:
  - [ ] `guillotine build tests/fixtures/todo_openapi.yaml -o /tmp/guillotine-smoke`
  - [ ] `python3 -m compileall -q /tmp/guillotine-smoke/acme_tasks /tmp/guillotine-smoke/mcp`

## Notes For Reviewers

- Generated DSL UX changed: yes / no
- Runtime/security boundary changed: yes / no
- Docs or OSS metadata changed: yes / no
