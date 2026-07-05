# Roadmap

Guillotine is useful as a Phase 0 compiler today, but the high-value frontier is still
ahead.

## Phase 0 - OSS MVP

Status: implemented; release hardening in progress.

- OpenAPI 3 input.
- Python DSL projection.
- Agent Skills projection.
- Single-tool MCP wrapper.
- Local subprocess runtime.
- Static inspection report.
- Real-spec smoke on GitHub REST OpenAPI.

## Phase 1 - Landmine Loop

- Live probe harness for generated DSLs.
- Probe-sourced silent-failure guards.
- Probe-validated examples for generated skills.
- Guard/report feedback loop into the IR.

## Phase 2 - Broader Inputs And Stronger Runtime

- SDK reflection input.
- GraphQL and gRPC input.
- Typed body models.
- Stronger hosted sandbox adapter.
- Benchmark harness against OpenAPI-to-MCP and SDK-as-code baselines.

## Dogfood Milestone

Regenerate the mechanical 70-80% of the reference Dataiku Headless DSL from a DSS REST
spec or `dataikuapi` reflection and compare generated shape, token footprint, and task
success.
