# Generated DSL Contract

Generated packages follow the same agent-facing contract.

## Entry Point

```python
import my_api
c = my_api.connect(base_url="https://api.example.com", token="...")
```

Credentials resolve from explicit arguments first, then package-specific environment
variables, then generic fallbacks:

```bash
export MY_API_BASE_URL=https://api.example.com
export MY_API_TOKEN=...
```

`token=` is mapped to the first supported OpenAPI security scheme, including bearer
auth and common `apiKey` header/query/cookie schemes.

## Namespaces And Verbs

Tags/resources become namespaces:

```python
c.repos.get("owner", "repo").one()
c.issues.list_for_repo("owner", "repo").head(20)
```

Generated verbs return an `OperationResult`. The API call is lazy until `.run()`,
`.head()`, `.one()`, `.all()`, `.json()`, or `.text()` is called.

## Distillation

Use:

- `.head(n)` for one page of distilled rows,
- `.all(max_pages=...)` for generated paginated operations,
- `.one()` for a single distilled object,
- `.grain()` for a compact shape summary,
- `.json()` only when the full payload is necessary.

Distilled rows flatten nested dictionaries and lists into size summaries so large API
payloads do not flood model context by default.

Truncation is signalled, not silent: a row with more than 50 keys gains a
`__truncated_keys__` marker, and `.head(n)` reports `N of M row(s) shown` on stderr when
the payload holds more rows than were returned. Reach for `.json()` to get the full,
untruncated payload when a field looks missing.

Unwrapping is spec-driven. The generator reads each operation's success-response schema,
so `.head()/.one()` know whether the body is a collection (and at which key, e.g. GeoJSON
`features`) or a single object. A single object that happens to have an array field is
never mistaken for a collection. When the spec is too vague to classify, the runtime
falls back to a heuristic over common wrapper keys (`items`, `data`, `results`,
`records`, `values`, `features`).

## Discoverability

```python
print(my_api.cheatsheet(section="repos", grep="branch"))
print(my_api.help_json("repos.list_branches"))
```

For write operations, `help_json` includes a `body` list of the top-level request-body
fields (name, type, required, enum), and the docstring lists them under "Body fields", so
the request shape is discoverable without reading the raw spec. Body fields with an enum
are validated before the API call, the same as enum query parameters.

`help_json()` is the structured twin of the cheatsheet and includes enum choices.

## Safety

Generated DELETE operations require explicit intent:

```python
c.repos.delete("owner", "repo", yes=True).run()
```

Cascade-tier operations, when detected, also require `confirm_name=...`.
For cascade-tier operations with path parameters, `confirm_name` must match the final
path target so accidental broad deletes do not pass on a merely truthy value.

Every namespace and client exposes `.raw`, the underlying transport, so generated DSLs
are not a ceiling when an operation needs an escape hatch.
