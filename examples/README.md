# Examples

Generated examples are smoke artifacts used to inspect Guillotine's product UX against
real OpenAPI descriptions. `examples/generated/` is ignored by git; regenerate these
artifacts locally when needed.

## GitHub REST API

To regenerate the local smoke:

```bash
curl -L https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json \
  -o /tmp/github.openapi.json
guillotine build /tmp/github.openapi.json -o examples/generated/github --package-name github_api
```

This writes:

```text
examples/generated/github/github_api/   Python DSL package
examples/generated/github/skills/       Agent Skills pack
examples/generated/github/mcp/          MCP wrapper
```

The source spec used for the smoke was GitHub's public REST OpenAPI description:

```text
https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json
```

Example:

```python
import github_api
c = github_api.connect()
c.repos.get("octocat", "Hello-World").one()
c.repos.list_branches("octocat", "Hello-World").all(max_pages=2, per_page=50)
```
