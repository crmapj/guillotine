# Changelog

All notable changes to Guillotine will be documented here.

This project follows semantic versioning once public releases begin.

## 0.1.0 - Unreleased

Initial OSS MVP:

- OpenAPI 3 YAML/JSON ingest.
- Curated Core IR for resources, operations, parameters, request bodies, enum choices,
  servers, and safety tiers.
- Generated Python DSL package with `connect()`, namespaced verbs, `.raw`, enum guards,
  destructive-operation speed bumps, scoped `cheatsheet()`, `help()`, and `help_json()`.
- Lazy `OperationResult` handles with `.run()`, `.head(n)`, `.one()`, `.all()`,
  `.json()`, `.text()`, and `.grain()`.
- Generated Agent Skills pack.
- Generated single-tool MCP wrapper.
- Local subprocess runtime contract. No sandbox: the executor runs agent code with the
  full privileges of the calling process. It enforces a timeout (process-group kill) and
  withholds non-prefixed host env vars; the generated `exec` MCP tool is disabled until
  `GUILLOTINE_ALLOW_EXEC=1`.
- `guillotine inspect` compiler-surface report with a rough, clearly-labelled
  discovery-surface estimate (JSON tool schemas vs generated cheatsheet, static chars/4).
- Reproducible GitHub REST OpenAPI smoke, regenerated locally into the git-ignored
  `examples/generated/` (excluded from the published package).

Hardening in this MVP:

- Safety tiers match whole tokens (no more `clearance` → `clear`), cover more destructive
  verbs (`wipe`, `truncate`, `terminate`, `ban`, ...), and accept a per-operation
  `x-guillotine-safety-tier` override.
- Enum guards now cover multi-value (array-of-enum) query filters, validating each list
  element before the API call — not just scalar enums.
- Result distillation is spec-driven: the IR records whether a response is a collection
  (and at which key, e.g. GeoJSON `features`) or a single object, so `.head()/.one()`
  unwrap the right thing instead of guessing — and never mistake a single object's array
  field for the payload.
- Request bodies are discoverable: top-level body fields (name, type, required, enum) are
  surfaced in the docstring and `help_json`, and body enum fields are guarded before the
  API call. Niche write endpoints no longer require reading the raw spec.
- Spec loading falls back from JSON to YAML when a `.json` file is actually YAML (common
  in the wild), instead of failing to parse.
- Result distillation signals truncation instead of dropping silently
  (`__truncated_keys__` marker; `N of M row(s) shown`).
- Untagged/versioned specs (for example every Stripe path under `/v1/`) group by a
  meaningful path segment instead of collapsing into one namespace.
- Generated transport restricts requests to `http(s)`, form-encodes
  `x-www-form-urlencoded` bodies, and fails loudly on `multipart/form-data`.
- One shared pagination predicate for the emitter and `inspect`, so `.all()` only walks
  operations with a real cursor pair.
